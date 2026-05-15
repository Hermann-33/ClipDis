from __future__ import annotations

import logging
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

import requests

from app.qt_runtime import configure_qt_runtime

configure_qt_runtime()

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog

from app.config import AppConfig, config_path, load_config, logs_dir, save_config, validate_config
from app.discord_uploader import validate_webhook_url
from app.ffmpeg_runner import (
    get_bundled_ffmpeg_path,
    get_bundled_ffprobe_path,
    resolve_ffmpeg_path,
    validate_ffmpeg,
)
from app.logging_setup import recent_logs
from app.secrets import DISCORD_WEBHOOK_KEY, HENRIK_API_KEY, get_secret, redact, set_secret
from app.startup import disable_startup, enable_startup, get_startup_command, is_startup_enabled, is_supported as startup_supported
from app.state import StateStore
from app.thumbnailer import cached_thumbnail_for_job, ensure_thumbnail, thumbnail_path_for_job
from app.valorant_stats import clear_valorant_stats_cache, fetch_valorant_stats
from app.worker import ClipWorker


logger = logging.getLogger(__name__)


class GuiBridge(QObject):
    thumbnailsChanged = Signal()
    dashboardDataChanged = Signal()

    def __init__(self, app: QApplication | None = None, worker: ClipWorker | None = None) -> None:
        super().__init__()
        self._app = app
        self._paused = False
        self._worker = worker
        self._state = StateStore()
        self._state.initialize_database()
        self._thumbnail_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ClipThumbnail")
        self._thumbnail_lock = threading.Lock()
        self._thumbnail_inflight: set[int] = set()
        self._thumbnail_failed_at: dict[int, float] = {}
        self._thumbnail_failure_retry_seconds = 300.0
        self._clip_upload_lock = threading.Lock()
        self._clip_upload_inflight: set[int] = set()
        self._selected_upload_lock = threading.Lock()
        self._selected_upload_inflight: set[int] = set()

    @Slot(result=dict)
    def getConfig(self) -> dict[str, Any]:
        try:
            cfg = asdict(load_config())
            return cfg | {
                # Camel-case aliases make QML bindings resilient if a page uses
                # either JS-style or Python-style field names.
                "watchFolder": cfg.get("watch_folder", ""),
                "uploadedFolder": cfg.get("uploaded_folder", ""),
                "valorantRegion": cfg.get("valorant_region", "ap"),
                "startWithWindows": cfg.get("start_with_windows", False),
                "useHenrikStats": cfg.get("use_henrik_stats", False),
            }
        except Exception as exc:
            logger.exception("Failed to load configuration for GUI.")
            return asdict(AppConfig()) | {"_error": redact(str(exc))}

    @Slot(dict, result=dict)
    def saveConfig(self, configObject: dict[str, Any]) -> dict[str, Any]:
        try:
            incoming = _normalize_config_input(configObject)
            current = asdict(load_config())
            current.update(incoming)
            current["ffmpeg_source_mode"] = "bundled"
            current["ffmpeg_path"] = ""
            cfg = AppConfig(**_coerce_config(current))
            issues = validate_config(cfg)
            save_config(cfg)
            logger.info(
                "Configuration saved from GUI: watch_folder_present=%s uploaded_folder_present=%s config_path=%s watch_folder_ok=%s uploaded_folder_ok=%s",
                bool(cfg.watch_folder),
                bool(cfg.uploaded_folder),
                config_path(),
                Path(cfg.watch_folder).is_dir() if cfg.watch_folder else False,
                Path(cfg.uploaded_folder).is_dir() if cfg.uploaded_folder else False,
            )
            if any(key in incoming for key in ("use_henrik_stats", "riot_username", "riot_tagline", "valorant_region")):
                clear_valorant_stats_cache()
            startup_result = None
            if "start_with_windows" in incoming:
                startup_result = enable_startup() if cfg.start_with_windows else disable_startup()
                if startup_result.ok and cfg.start_with_windows != startup_result.enabled:
                    cfg.start_with_windows = startup_result.enabled
                    save_config(cfg)
            message = "Settings saved." if not issues else "Settings saved with validation warnings."
            if startup_result is not None:
                message = f"{message} {startup_result.message}"
            saved = asdict(load_config())
            return {
                "ok": not any(issue.severity == "error" for issue in issues) and (startup_result.ok if startup_result else True),
                "message": message,
                "issues": [_issue_to_dict(issue) for issue in issues],
                "startup": _startup_result_to_dict(startup_result) if startup_result else self.getStartupStatus(),
                "config": saved,
                "watch_folder": saved.get("watch_folder", ""),
                "uploaded_folder": saved.get("uploaded_folder", ""),
            }
        except Exception as exc:
            logger.exception("Failed to save configuration.")
            return {"ok": False, "message": f"Could not save settings: {redact(str(exc))}", "issues": []}

    @Slot(result=dict)
    def getRedactedSecretsStatus(self) -> dict[str, Any]:
        try:
            webhook = get_secret(DISCORD_WEBHOOK_KEY)
            henrik = get_secret(HENRIK_API_KEY)
            return {
                "webhookConfigured": bool(webhook),
                "webhookDisplay": _redacted_webhook(webhook),
                "henrikConfigured": bool(henrik),
                "henrikDisplay": _redacted_token(henrik),
            }
        except Exception as exc:
            logger.exception("Failed to read secret status for GUI.")
            return {
                "webhookConfigured": False,
                "webhookDisplay": "Not configured",
                "henrikConfigured": False,
                "henrikDisplay": "Not configured",
                "henrikStatsEnabled": False,
                "valorantRegion": "ap",
                "error": redact(str(exc)),
            }

    @Slot(str, str, result=dict)
    def saveSecrets(self, webhookUrl: str, henrikApiKey: str) -> dict[str, Any]:
        try:
            webhook_updated = False
            henrik_updated = False
            if webhookUrl and not _looks_redacted(webhookUrl):
                webhook_value = webhookUrl.strip()
                valid, message = validate_webhook_url(webhook_value)
                if not valid:
                    return {"ok": False, "message": message, "status": self.getRedactedSecretsStatus()}
                set_secret(DISCORD_WEBHOOK_KEY, webhook_value)
                webhook_updated = True
            if henrikApiKey and not _looks_redacted(henrikApiKey):
                set_secret(HENRIK_API_KEY, henrikApiKey.strip())
                clear_valorant_stats_cache()
                henrik_updated = True
            logger.info("Secrets updated from GUI.")
            status = self.getRedactedSecretsStatus()
            refresh = self.refreshAppState()
            return {
                "ok": True,
                "message": "Secrets saved.",
                "status": status,
                "webhookConfigured": status["webhookConfigured"],
                "henrikConfigured": status["henrikConfigured"],
                "webhookUpdated": webhook_updated,
                "henrikUpdated": henrik_updated,
                "refresh": refresh,
            }
        except Exception as exc:
            logger.exception("Failed to save secrets.")
            return {"ok": False, "message": f"Could not save secrets: {redact(str(exc))}"}

    @Slot(result=dict)
    def testWebhook(self) -> dict[str, Any]:
        webhook = get_secret(DISCORD_WEBHOOK_KEY)
        if not webhook:
            return {"ok": False, "message": "Discord webhook is not configured."}
        try:
            response = requests.post(
                webhook,
                params={"wait": "true"},
                json={"content": "ClipDis webhook test."},
                timeout=10,
            )
            if response.status_code in (200, 204):
                logger.info("Webhook test succeeded.")
                return {"ok": True, "message": "Webhook test succeeded."}
            logger.warning("Webhook test failed with HTTP %s.", response.status_code)
            return {"ok": False, "message": f"Webhook test failed: HTTP {response.status_code}."}
        except requests.RequestException as exc:
            logger.warning("Webhook test failed: %s", redact(str(exc)))
            return {"ok": False, "message": f"Webhook test failed: {redact(str(exc))}"}

    @Slot(result=dict)
    def testFfmpeg(self) -> dict[str, Any]:
        cfg = load_config()
        executable = resolve_ffmpeg_path(cfg)
        if not Path(executable).is_file():
            return {
                "ok": False,
                "message": f"Bundled FFmpeg is missing. Expected: {get_bundled_ffmpeg_path()}",
                "expectedPath": str(get_bundled_ffmpeg_path()),
            }
        result = validate_ffmpeg(executable)
        return {
            "ok": result.ok,
            "message": result.message if result.ok else f"Bundled FFmpeg test failed: {result.message}",
            "path": result.ffmpeg_path,
            "category": result.category,
        }

    @Slot(result=dict)
    def validateFolders(self) -> dict[str, Any]:
        cfg = load_config()
        issues = [
            issue
            for issue in validate_config(cfg)
            if issue.field in {"watch_folder", "uploaded_folder", "ffmpeg", "ffprobe"}
        ]
        return {
            "ok": not issues,
            "message": "Folders and bundled FFmpeg look valid." if not issues else "Some paths need attention.",
            "issues": [_issue_to_dict(issue) for issue in issues],
        }

    @Slot(result=dict)
    def testValorantStats(self) -> dict[str, Any]:
        try:
            cfg = load_config()
            clear_valorant_stats_cache()
            result = fetch_valorant_stats(cfg)
            rank = result.rank or "Unknown"
            level = "Unknown" if result.account_level is None else str(result.account_level)
            message = f"Rank: {rank}. Level: {level}." if result.available else result.message
            return {
                "ok": result.available,
                "message": message,
                "data": {
                    "enabled": bool(cfg.use_henrik_stats),
                    "namePresent": bool((cfg.riot_username or "").strip()),
                    "tagPresent": bool((cfg.riot_tagline or "").strip()),
                    "region": cfg.valorant_region or "ap",
                    "keyPresent": bool(get_secret(HENRIK_API_KEY)),
                    "rank": rank,
                    "level": level,
                    "category": result.category,
                    "rankCategory": result.rank_category,
                    "levelCategory": result.level_category,
                },
            }
        except Exception as exc:
            logger.exception("Valorant stats test failed.")
            return {
                "ok": False,
                "message": f"Could not test Valorant stats: {redact(str(exc))}",
                "data": {"rank": "Unknown", "level": "Unknown", "category": "stats_test_error"},
            }

    @Slot(result=dict)
    def refreshAppState(self) -> dict[str, Any]:
        try:
            # All underlying helpers read from disk/keyring on demand; this
            # method provides one explicit "refresh everything" boundary for QML.
            cfg = load_config()
            if self._worker:
                self._worker.reload_runtime_config()
            dashboard = self.getCompactDashboardStatus()
            setup = self.getSetupStatus()
            clips = self.getDashboardClips()
            return {
                "ok": True,
                "message": "App state refreshed.",
                "data": {
                    "config": asdict(cfg),
                    "secrets": self.getRedactedSecretsStatus(),
                    "dashboard": dashboard,
                    "setup": setup,
                    "clips": clips,
                    "counts": self._state.count_by_status(),
                    "worker": self._worker.get_status() if self._worker else _default_worker_status(),
                },
            }
        except Exception as exc:
            logger.exception("Refresh app state failed.")
            return {"ok": False, "message": f"Could not refresh app state: {redact(str(exc))}", "data": {}}

    @Slot(result=dict)
    def checkWebhookLive(self) -> dict[str, Any]:
        webhook = get_secret(DISCORD_WEBHOOK_KEY)
        valid, message = validate_webhook_url(webhook)
        if not valid:
            return {"ok": False, "message": message, "configured": bool(webhook), "shapeValid": False}
        try:
            response = requests.get(webhook, timeout=10)
            if response.status_code == 200:
                return {"ok": True, "message": "Discord webhook exists.", "configured": True, "shapeValid": True, "statusCode": response.status_code}
            if response.status_code == 404:
                return {"ok": False, "message": "Discord webhook was not found.", "configured": True, "shapeValid": True, "statusCode": response.status_code}
            return {"ok": False, "message": f"Discord webhook check returned HTTP {response.status_code}.", "configured": True, "shapeValid": True, "statusCode": response.status_code}
        except requests.RequestException as exc:
            return {"ok": False, "message": f"Webhook check failed: {redact(str(exc))}", "configured": True, "shapeValid": True}

    @Slot(str, result=dict)
    def openExternalUrl(self, url: str) -> dict[str, Any]:
        try:
            target = str(url or "").strip()
            if not target.startswith(("https://", "http://")):
                return {"ok": False, "message": "Invalid URL."}
            opened = QDesktopServices.openUrl(QUrl(target))
            return {"ok": bool(opened), "message": "Opened link." if opened else "Could not open link."}
        except Exception as exc:
            logger.exception("Open external URL failed.")
            return {"ok": False, "message": f"Could not open link: {redact(str(exc))}"}

    @Slot(str, str, result=dict)
    def browseForFolder(self, currentPath: str = "", purpose: str = "Select folder") -> dict[str, Any]:
        try:
            if QApplication.instance() is None:
                return {"ok": False, "message": "Folder picker is only available while the GUI is running.", "path": ""}
            start = currentPath if currentPath and Path(currentPath).exists() else str(Path.home())
            selected = QFileDialog.getExistingDirectory(None, purpose or "Select folder", start)
            if not selected:
                return {"ok": False, "message": "Folder selection cancelled.", "path": ""}
            return {"ok": True, "message": "Folder selected.", "path": selected}
        except Exception as exc:
            logger.exception("Folder picker failed.")
            return {"ok": False, "message": f"Could not open folder picker: {redact(str(exc))}", "path": ""}

    @Slot(result=dict)
    def getDashboardStatus(self) -> dict[str, Any]:
        try:
            cfg = load_config()
            issues = validate_config(cfg)
            secrets = self.getRedactedSecretsStatus()
            summary = self._state.get_queue_summary()
            worker_status = self._worker.get_status() if self._worker else _default_worker_status()
            auto_status = self._worker.get_auto_pipeline_status() if self._worker else _default_auto_status()
            current_job = summary["current_job"]
            last_uploaded = summary["last_uploaded"]
            runtime_error = worker_status["last_error"] or ""
            return {
            "appStatus": worker_status["state"],
            "watcherStatus": worker_status["state"],
            "watcherEnabled": worker_status["watcher_enabled"],
            "lastScanTime": worker_status["last_scan_time"] or "Never",
            "lastWatcherError": worker_status["last_error"] or "None",
            "configStatus": "Ready" if not issues else "Setup needed",
            "watchFolder": worker_status["watch_folder"] or cfg.watch_folder or "Not configured",
            "uploadedFolder": cfg.uploaded_folder or "Not configured",
            "webhookConfigured": secrets["webhookConfigured"],
            "henrikConfigured": secrets["henrikConfigured"],
            "queueCount": summary["queue_count"],
            "failedCount": summary["failed_count"],
            "processedCount": summary["processed_count"],
            "uploadedCount": summary["uploaded_count"],
            "archivedCount": summary["archived_count"],
            "currentJob": _job_label(current_job),
            "lastUploaded": _job_label(last_uploaded),
            "lastError": runtime_error or "None",
            "lastFailedJobError": _job_error(summary["last_failed"]),
            "autoModeEnabled": auto_status["enabled"],
            "autoPipelineStatus": auto_status["state"],
            "lastAutoCycleTime": auto_status["last_cycle_time"] or "Never",
            "lastAutoCycleSummary": auto_status["last_cycle_summary"] or "None",
            "repeatedFailureCount": auto_status["repeated_failure_count"],
            }
        except Exception as exc:
            logger.exception("Failed to build dashboard status.")
            status = _default_worker_status()
            return {
                "appStatus": "error",
                "watcherStatus": "error",
                "watcherEnabled": False,
                "lastScanTime": "Never",
                "lastWatcherError": redact(str(exc)),
                "configStatus": "Error",
                "watchFolder": "Not configured",
                "uploadedFolder": "Not configured",
                "webhookConfigured": False,
                "henrikConfigured": False,
                "queueCount": 0,
                "failedCount": 0,
                "processedCount": 0,
                "uploadedCount": 0,
                "archivedCount": 0,
                "currentJob": "None",
                "lastUploaded": "None",
                "lastError": redact(str(exc)),
                "autoModeEnabled": False,
                "autoPipelineStatus": status["state"],
                "lastAutoCycleTime": "Never",
                "lastAutoCycleSummary": "None",
                "repeatedFailureCount": 0,
            }

    @Slot(result=dict)
    def getCompactDashboardStatus(self) -> dict[str, Any]:
        try:
            status = self.getDashboardStatus()
            setup = self.getSetupStatus()
        except Exception as exc:
            logger.exception("Failed to build compact dashboard status.")
            return {
                "mainStatus": "Error",
                "autoStatus": "Auto Off",
                "autoModeEnabled": False,
                "queueSummary": "0 waiting / 0 active / 0 failed",
                "currentJob": "None",
                "currentStage": "Error",
                "lastUploaded": "None",
                "lastError": redact(str(exc)),
                "setupComplete": False,
                "setupMessage": "Setup required: choose folders and webhook in Settings.",
                "hasError": True,
            }
        queue = int(status.get("queueCount", 0) or 0)
        processing = 1 if status.get("currentJob") and status.get("currentJob") != "None" else 0
        failed = int(status.get("failedCount", 0) or 0)
        last_watcher_error = status.get("lastWatcherError", "")
        last_error = status.get("lastError", "")
        has_error = bool(last_watcher_error and last_watcher_error != "None") or bool(last_error and last_error != "None")

        if not setup["complete"]:
            main = "Needs Setup"
        elif has_error:
            main = "Error"
        elif status.get("watcherStatus") == "paused":
            main = "Paused"
        else:
            main = "Running"

        auto_state = str(status.get("autoPipelineStatus") or "stopped")
        if auto_state == "auto_paused_due_to_failures":
            auto = "Auto Paused"
        elif status.get("autoModeEnabled"):
            auto = "Auto On"
        else:
            auto = "Auto Off"

        return {
            **status,
            "mainStatus": main,
            "autoStatus": auto,
            "queueSummary": f"{queue} waiting / {processing} active / {failed} failed",
            "currentStage": status.get("watcherStatus") or "Idle",
            "setupComplete": setup["complete"],
            "setupMessage": setup["message"],
            "hasError": has_error,
        }

    @Slot(result=dict)
    def getSetupStatus(self) -> dict[str, Any]:
        try:
            cfg = load_config()
            secrets = self.getRedactedSecretsStatus()
            startup_status = self.getStartupStatus()
            watch_ok = bool(cfg.watch_folder and Path(cfg.watch_folder).is_dir())
            uploaded_ok = bool(cfg.uploaded_folder and Path(cfg.uploaded_folder).is_dir())
            ffmpeg_expected = get_bundled_ffmpeg_path()
            ffprobe_expected = get_bundled_ffprobe_path()
            ffmpeg_executable = resolve_ffmpeg_path(cfg) if ffmpeg_expected.is_file() else ""
            ffprobe_ok = ffprobe_expected.is_file()
            ffmpeg_ok = bool(ffmpeg_executable) and ffprobe_ok
            webhook = get_secret(DISCORD_WEBHOOK_KEY)
            webhook_ok = validate_webhook_url(webhook)[0]
            henrik_ok = secrets["henrikConfigured"]
            required_ok = watch_ok and uploaded_ok and ffmpeg_ok and webhook_ok
            missing = []
            if not watch_ok:
                missing.append("watch folder")
            if not uploaded_ok:
                missing.append("uploaded folder")
            if not ffmpeg_ok:
                missing.append("FFmpeg")
            if not webhook_ok:
                missing.append("webhook")
            return {
            "complete": required_ok,
            "message": "Setup complete." if required_ok else "Setup required: choose folders and webhook in Settings.",
            "missing": ", ".join(missing),
            "watchFolderOk": watch_ok,
            "uploadedFolderOk": uploaded_ok,
            "ffmpegOk": ffmpeg_ok,
            "ffmpeg_ok": ffmpeg_ok,
            "ffmpegMode": cfg.ffmpeg_source_mode,
            "ffmpeg_mode": "bundled",
            "ffmpegDisplay": "Bundled FFmpeg: OK" if ffmpeg_ok else "Bundled FFmpeg: Missing",
            "ffmpegExpectedPath": str(ffmpeg_expected),
            "ffmpeg_expected_path": str(ffmpeg_expected),
            "ffprobeExpectedPath": str(ffprobe_expected),
            "ffmpegResolvedPath": ffmpeg_executable,
            "ffmpeg_resolved_path": ffmpeg_executable,
            "webhookOk": webhook_ok,
            "henrikOk": henrik_ok,
            "webhookDisplay": secrets["webhookDisplay"],
            "henrikDisplay": secrets["henrikDisplay"],
            "henrikStatsEnabled": bool(cfg.use_henrik_stats),
            "valorantRegion": cfg.valorant_region,
            "startupSupported": startup_status["supported"],
            "startupEnabled": startup_status["enabled"],
            "startupMessage": startup_status["message"],
            "startupCommand": startup_status["command"],
            }
        except Exception as exc:
            logger.exception("Failed to build setup status.")
            return {
                "complete": False,
                "message": "Setup required: choose folders and webhook in Settings.",
                "missing": "configuration",
                "watchFolderOk": False,
                "uploadedFolderOk": False,
                "ffmpegOk": False,
                "ffmpeg_ok": False,
                "ffmpegMode": "bundled",
                "ffmpeg_mode": "bundled",
                "ffmpegDisplay": "Bundled FFmpeg: Missing",
                "ffmpegExpectedPath": str(get_bundled_ffmpeg_path()),
                "ffmpeg_expected_path": str(get_bundled_ffmpeg_path()),
                "ffprobeExpectedPath": str(get_bundled_ffprobe_path()),
                "ffmpegResolvedPath": "",
                "ffmpeg_resolved_path": "",
                "webhookOk": False,
                "henrikOk": False,
                "webhookDisplay": "Not configured",
                "henrikDisplay": "Not configured",
                "henrikStatsEnabled": False,
                "valorantRegion": "ap",
                "startupSupported": False,
                "startupEnabled": False,
                "startupMessage": "Startup status unavailable.",
                "startupCommand": "",
                "error": redact(str(exc)),
            }

    @Slot(result=dict)
    def getStartupStatus(self) -> dict[str, Any]:
        try:
            supported = startup_supported()
            enabled = is_startup_enabled() if supported else False
            return {
                "ok": True,
                "supported": supported,
                "enabled": enabled,
                "message": "Start with Windows is enabled." if enabled else ("Start with Windows is disabled." if supported else "Start with Windows is unsupported on this OS."),
                "command": get_startup_command() if supported else "",
            }
        except Exception as exc:
            logger.exception("Startup status failed.")
            return {"ok": False, "supported": False, "enabled": False, "message": redact(str(exc)), "command": ""}

    @Slot(result=dict)
    def openWatchFolder(self) -> dict[str, Any]:
        try:
            return self._open_path(load_config().watch_folder, "Watch folder")
        except Exception as exc:
            logger.exception("Open watch folder failed.")
            return {"ok": False, "message": f"Could not open watch folder: {redact(str(exc))}"}

    @Slot(result=dict)
    def openUploadedFolder(self) -> dict[str, Any]:
        try:
            return self._open_path(load_config().uploaded_folder, "Uploaded folder")
        except Exception as exc:
            logger.exception("Open uploaded folder failed.")
            return {"ok": False, "message": f"Could not open uploaded folder: {redact(str(exc))}"}

    @Slot(result=dict)
    def openLogsFolder(self) -> dict[str, Any]:
        try:
            logs_dir().mkdir(parents=True, exist_ok=True)
            return self._open_path(str(logs_dir()), "Logs folder")
        except Exception as exc:
            logger.exception("Open logs folder failed.")
            return {"ok": False, "message": f"Could not open logs folder: {redact(str(exc))}"}

    @Slot(result=dict)
    def pauseWatching(self) -> dict[str, Any]:
        try:
            self._paused = True
            if self._worker:
                return self._worker.pause()
            logger.info("Watching paused from GUI/tray.")
            return {"ok": True, "message": "Watching paused."}
        except Exception as exc:
            logger.exception("Pause watching failed.")
            return {"ok": False, "message": f"Could not pause watching: {redact(str(exc))}"}

    @Slot(result=dict)
    def resumeWatching(self) -> dict[str, Any]:
        try:
            self._paused = False
            if self._worker:
                return self._worker.resume()
            logger.info("Watching resumed from GUI/tray.")
            return {"ok": True, "message": "Watching resumed."}
        except Exception as exc:
            logger.exception("Resume watching failed.")
            return {"ok": False, "message": f"Could not resume watching: {redact(str(exc))}"}

    @Slot(result=dict)
    def processQueueNow(self) -> dict[str, Any]:
        if self._worker:
            return self._worker.process_queue_now()
        summary = self._state.get_queue_summary()
        logger.info("Process Queue Now requested with %s queued job(s), but worker is not implemented yet.", summary["queue_count"])
        return {
            "ok": False,
            "message": f"Worker is not implemented yet. {summary['queue_count']} job(s) are queued.",
            "queueCount": summary["queue_count"],
        }

    @Slot(result=dict)
    def uploadProcessedNow(self) -> dict[str, Any]:
        if self._worker:
            return self._worker.upload_processed_now()
        return {"ok": False, "message": "Worker is not running.", "uploaded": 0, "failed": 0}

    @Slot(result=dict)
    def archiveUploadedNow(self) -> dict[str, Any]:
        if self._worker:
            return self._worker.archive_uploaded_now()
        return {"ok": False, "message": "Worker is not running.", "archived": 0, "failed": 0}

    @Slot(result=dict)
    def runEndToEndNow(self) -> dict[str, Any]:
        return self.runPendingUploads()

    @Slot(result=dict)
    def runPendingUploads(self) -> dict[str, Any]:
        try:
            if self._worker:
                result = self._worker.run_end_to_end_now()
                result.setdefault("message", "Pending upload run started.")
                return result
            return {"ok": False, "message": "Worker is not running.", "errors": ["worker missing"]}
        except Exception as exc:
            logger.exception("Pending upload run failed.")
            return {"ok": False, "message": f"Could not start pending uploads: {redact(str(exc))}", "errors": [redact(str(exc))]}

    @Slot(bool, result=dict)
    def enableAutoMode(self, enabled: bool) -> dict[str, Any]:
        try:
            current = asdict(load_config())
            current["auto_process_enabled"] = bool(enabled)
            current["auto_upload_enabled"] = bool(enabled)
            current["auto_archive_enabled"] = bool(enabled)
            save_config(AppConfig(**_coerce_config(current)))
            if self._worker:
                return self._worker.set_auto_pipeline_enabled(bool(enabled))
            return {"ok": True, "message": f"Auto mode {'enabled' if enabled else 'disabled'}."}
        except Exception as exc:
            logger.exception("Set auto mode failed.")
            return {"ok": False, "message": f"Could not update auto mode: {redact(str(exc))}"}

    @Slot(result=dict)
    def scanNow(self) -> dict[str, Any]:
        try:
            if self._worker:
                return self._worker.scan_now()
            return {"ok": False, "message": "Worker is not running.", "queued": 0, "ignored": 0}
        except Exception as exc:
            logger.exception("Scan now failed.")
            return {"ok": False, "message": f"Could not scan watch folder: {redact(str(exc))}", "queued": 0, "ignored": 0}

    @Slot(result="QVariant")
    def getClipHistory(self) -> list[dict[str, Any]]:
        try:
            return [_job_for_qml(job) for job in self._state.list_recent_jobs(limit=100)]
        except Exception as exc:
            logger.exception("Failed to load clip history for GUI.")
            return [{"id": 0, "filename": "Could not load clips", "status": "failed", "statusLabel": "Error", "summary": redact(str(exc)), "selectable": False}]

    @Slot(int, result="QVariant")
    def getRecentClips(self, limit: int = 8) -> list[dict[str, Any]]:
        try:
            limit = max(1, min(int(limit), 25))
            return [_job_for_qml(job) for job in self._state.list_recent_jobs(limit=limit)]
        except Exception as exc:
            logger.exception("Failed to load recent clips for GUI.")
            return [{"id": 0, "filename": "Could not load clips", "status": "failed", "statusLabel": "Error", "summary": redact(str(exc)), "selectable": False}]

    @Slot(result="QVariant")
    def getDashboardClips(self) -> list[dict[str, Any]]:
        try:
            cfg = load_config()
            watch_folder = Path(cfg.watch_folder).resolve(strict=False) if cfg.watch_folder else None
            visible_statuses = {
                "detected",
                "waiting_for_file_ready",
                "queued",
                "processing",
                "processed",
                "uploading",
                "uploaded",
                "failed",
            }
            clips: list[dict[str, Any]] = []
            for job in self._state.list_recent_jobs(limit=150):
                if job.get("status") not in visible_statuses:
                    continue
                source = Path(str(job.get("source_path") or ""))
                if watch_folder and not _is_inside(source, watch_folder):
                    continue
                clips.append(self._dashboard_clip_for_qml(job, cfg))
            return clips[:60]
        except Exception as exc:
            logger.exception("Failed to load dashboard clips for GUI.")
            return [
                {
                    "id": 0,
                    "job_id": 0,
                    "filename": "Could not load clips",
                    "raw_status": "failed",
                    "friendly_status": "Error",
                    "statusLabel": "Error",
                    "summary": redact(str(exc)),
                    "selectable": False,
                    "thumbnail_url": "",
                }
            ]

    @Slot(result=str)
    def getDashboardClipsJson(self) -> str:
        try:
            return json.dumps(self.getDashboardClips())
        except Exception as exc:
            logger.exception("Failed to serialize dashboard clips for GUI.")
            return json.dumps(
                [
                    {
                        "id": 0,
                        "job_id": 0,
                        "filename": "Could not load clips",
                        "raw_status": "failed",
                        "friendly_status": "Error",
                        "statusLabel": "Error",
                        "summary": redact(str(exc)),
                        "selectable": False,
                        "thumbnail_url": "",
                    }
                ]
            )

    @Slot(result=str)
    def refreshDashboardClips(self) -> str:
        return self.getDashboardClipsJson()

    @Slot(int, result=dict)
    def getClipDetails(self, jobId: int) -> dict[str, Any]:
        try:
            job = self._state.get_job(int(jobId))
            if not job:
                return {"ok": False, "message": "Clip was not found.", "data": {}}
            return {"ok": True, "message": "Clip loaded.", "data": self._dashboard_clip_for_qml(job, load_config())}
        except Exception as exc:
            logger.exception("Failed to load clip details.")
            return {"ok": False, "message": f"Could not load clip details: {redact(str(exc))}", "data": {}}

    @Slot(int, result=dict)
    def ensureThumbnail(self, jobId: int) -> dict[str, Any]:
        try:
            job_id = int(jobId)
            job = self._state.get_job(job_id)
            if not job:
                return {"ok": False, "message": "Clip was not found.", "data": {"job_id": job_id, "thumbnail_path": "", "thumbnail_url": ""}}
            cfg = load_config()
            cached = cached_thumbnail_for_job(job, cfg)
            if cached.ok:
                with self._thumbnail_lock:
                    self._thumbnail_failed_at.pop(job_id, None)
                return {
                    "ok": True,
                    "message": "Thumbnail cached.",
                    "data": {
                        "job_id": job_id,
                        "thumbnail_path": cached.path,
                        "thumbnail_url": _thumbnail_file_url(cached.path),
                        "thumbnail_status": "ready",
                        "thumbnail_mtime": _path_mtime(cached.path),
                        "cached": True,
                    },
                }
            with self._thumbnail_lock:
                failed_at = self._thumbnail_failed_at.get(job_id)
                if failed_at and time.monotonic() - failed_at < self._thumbnail_failure_retry_seconds:
                    return {
                        "ok": False,
                        "message": "Thumbnail generation failed recently.",
                        "data": {
                            "job_id": job_id,
                            "thumbnail_path": "",
                            "thumbnail_url": "",
                            "thumbnail_status": "failed",
                            "retry_after_seconds": int(self._thumbnail_failure_retry_seconds - (time.monotonic() - failed_at)),
                        },
                    }
                if job_id in self._thumbnail_inflight:
                    return {
                        "ok": True,
                        "message": "Thumbnail is already queued.",
                        "data": {"job_id": job_id, "thumbnail_path": "", "thumbnail_url": "", "thumbnail_status": "generating", "queued": True},
                    }
                self._thumbnail_inflight.add(job_id)
            self._thumbnail_executor.submit(self._generate_thumbnail_background, job_id)
            return {"ok": True, "message": "Thumbnail queued.", "data": {"job_id": job_id, "thumbnail_path": "", "thumbnail_url": "", "thumbnail_status": "generating", "queued": True}}
        except Exception as exc:
            logger.exception("Thumbnail request failed.")
            return {"ok": False, "message": f"Could not queue thumbnail: {redact(str(exc))}", "data": {"job_id": int(jobId or 0), "thumbnail_path": "", "thumbnail_url": ""}}

    def _generate_thumbnail_background(self, job_id: int) -> None:
        try:
            job = self._state.get_job(job_id)
            if not job:
                return
            result = ensure_thumbnail(job, load_config())
            with self._thumbnail_lock:
                if result.ok:
                    self._thumbnail_failed_at.pop(job_id, None)
                else:
                    self._thumbnail_failed_at[job_id] = time.monotonic()
            if result.ok:
                logger.debug("Thumbnail generation completed for job %s.", job_id)
            else:
                logger.debug("Thumbnail generation skipped/failed for job %s: %s", job_id, result.message)
        except Exception as exc:
            logger.debug("Thumbnail generation failed for job %s: %s", job_id, redact(str(exc)))
            with self._thumbnail_lock:
                self._thumbnail_failed_at[job_id] = time.monotonic()
        finally:
            with self._thumbnail_lock:
                self._thumbnail_inflight.discard(job_id)
            self.thumbnailsChanged.emit()

    def _dashboard_clip_for_qml(self, job: dict[str, Any], config: AppConfig | None = None) -> dict[str, Any]:
        item = _dashboard_clip_for_qml(job, config)
        job_id = int(item.get("job_id") or 0)
        with self._thumbnail_lock:
            if job_id in self._thumbnail_inflight:
                item["thumbnail_status"] = "generating"
            elif self._thumbnail_failed_at.get(job_id) and not item.get("thumbnail_url"):
                item["thumbnail_status"] = "failed"
        return item

    @Slot(result="QVariant")
    def getSelectableDashboardClips(self) -> list[dict[str, Any]]:
        try:
            return self.getDashboardClips()
        except Exception as exc:
            logger.exception("Failed to load selectable clips for GUI.")
            return [{"id": 0, "filename": "Could not load clips", "status": "failed", "statusLabel": "Error", "summary": redact(str(exc)), "selectable": False}]

    @Slot(result=str)
    def getSelectableDashboardClipsJson(self) -> str:
        try:
            return self.getDashboardClipsJson()
        except Exception as exc:
            logger.exception("Failed to serialize dashboard clips for GUI.")
            return json.dumps([{"id": 0, "filename": "Could not load clips", "status": "failed", "statusLabel": "Error", "summary": redact(str(exc)), "selectable": False}])

    @Slot(result="QVariant")
    def getFailedJobs(self) -> list[dict[str, Any]]:
        try:
            return [_job_for_qml(job) for job in self._state.list_failed_jobs(limit=100)]
        except Exception as exc:
            logger.exception("Failed to load failed jobs for GUI.")
            return [{"id": 0, "filename": "Could not load failed clips", "status": "failed", "statusLabel": "Error", "summary": redact(str(exc)), "selectable": False}]

    @Slot(int, result=dict)
    def retryFailedJob(self, jobId: int) -> dict[str, Any]:
        try:
            job = self._state.retry_job(jobId)
            return {"ok": True, "message": "Failed job queued for retry.", "job": _job_for_qml(job)}
        except Exception as exc:
            logger.warning("Retry failed for job %s: %s", jobId, redact(str(exc)))
            return {"ok": False, "message": redact(str(exc))}

    @Slot(int, result=dict)
    def retryClip(self, jobId: int) -> dict[str, Any]:
        return self.retryFailedJob(jobId)

    @Slot(int, result=dict)
    def uploadClip(self, jobId: int) -> dict[str, Any]:
        try:
            job_id = int(jobId)
            job = self._state.get_job(job_id)
            if not job:
                return {"ok": False, "message": "Clip was not found.", "data": {"job_id": job_id, "status": ""}}
            if job.get("status") in {"processing", "uploading"}:
                return {"ok": False, "message": "This clip is already active.", "data": {"job_id": job_id, "status": job.get("status")}}
            if job.get("status") in {"archived"}:
                return {"ok": True, "message": "This clip is already done.", "data": {"job_id": job_id, "status": job.get("status")}}
            if job.get("status") not in {"failed", "queued", "processed", "uploaded"}:
                return {
                    "ok": False,
                    "message": "This clip is still being prepared. Refresh after it reaches Waiting.",
                    "data": {"job_id": job_id, "status": job.get("status")},
                }
            if not self._worker:
                return {"ok": False, "message": "Worker is not running.", "data": {"job_id": job_id, "status": job.get("status")}}
            with self._clip_upload_lock:
                if job_id in self._clip_upload_inflight:
                    return {"ok": False, "message": "This clip upload is already running.", "data": {"job_id": job_id, "status": job.get("status")}}
                self._clip_upload_inflight.add(job_id)
            thread = threading.Thread(target=self._upload_clip_background, args=(job_id,), name=f"ClipUpload-{job_id}", daemon=True)
            thread.start()
            return {"ok": True, "message": "Upload started for this clip only.", "data": {"job_id": job_id, "status": job.get("status")}}
        except Exception as exc:
            logger.exception("Upload clip failed.")
            return {"ok": False, "message": f"Could not start clip upload: {redact(str(exc))}", "data": {"job_id": int(jobId or 0), "status": ""}}

    def _upload_clip_background(self, job_id: int) -> None:
        try:
            if self._worker:
                result = self._worker.run_job_end_to_end(job_id)
                logger.info("Single clip upload run finished for job %s: %s", job_id, redact(str(result)))
        except Exception as exc:
            logger.exception("Single clip upload run crashed for job %s: %s", job_id, redact(str(exc)))
        finally:
            with self._clip_upload_lock:
                self._clip_upload_inflight.discard(job_id)

    @Slot(int, result=dict)
    def deleteClip(self, jobId: int) -> dict[str, Any]:
        result = self.deleteSelectedClips([int(jobId)])
        result["data"] = {"job_id": int(jobId), "deleted": int(result.get("deleted", 0)), "skipped": int(result.get("skipped", 0))}
        return result

    @Slot("QVariant", result=dict)
    def uploadSelectedClips(self, jobIds: Any) -> dict[str, Any]:
        try:
            ids = _coerce_ids(jobIds)
            requested = len(ids)
            logger.info("GUI selected upload requested for job ids: %s", ids)
            if not ids:
                return {
                    "ok": False,
                    "message": "No clips selected.",
                    "data": {"requested": 0, "started": 0, "completed": 0, "failed": 0, "skipped": 0},
                }
            if not self._worker:
                return {
                    "ok": False,
                    "message": "Worker is not running.",
                    "data": {"requested": requested, "started": 0, "completed": 0, "failed": 0, "skipped": requested},
                }

            startable: list[int] = []
            skipped = 0
            skipped_reasons: list[str] = []
            runnable_statuses = {"failed", "queued", "processed", "uploaded"}
            active_statuses = {"processing", "uploading"}
            for job_id in ids:
                job = self._state.get_job(job_id)
                if not job:
                    skipped += 1
                    skipped_reasons.append(f"{job_id}: missing")
                    continue
                status = str(job.get("status") or "")
                if status in active_statuses or status not in runnable_statuses:
                    skipped += 1
                    skipped_reasons.append(f"{job_id}: {status or 'unknown'}")
                    continue
                startable.append(job_id)

            logger.info("Selected upload accepted ids=%s skipped=%s reasons=%s", startable, skipped, skipped_reasons)
            if not startable:
                return {
                    "ok": False,
                    "message": "No selected clips are ready to upload.",
                    "data": {"requested": requested, "started": 0, "completed": 0, "failed": 0, "skipped": skipped},
                }

            with self._selected_upload_lock:
                already_running = [job_id for job_id in startable if job_id in self._selected_upload_inflight]
                startable = [job_id for job_id in startable if job_id not in self._selected_upload_inflight]
                skipped += len(already_running)
                if already_running:
                    logger.info("Selected upload skipped already-running ids=%s", already_running)
                if not startable:
                    return {
                        "ok": False,
                        "message": "Selected upload is already running for these clips.",
                        "data": {"requested": requested, "started": 0, "completed": 0, "failed": 0, "skipped": skipped},
                    }
                self._selected_upload_inflight.update(startable)

            thread = threading.Thread(target=self._upload_selected_background, args=(startable,), name="SelectedClipUpload", daemon=True)
            thread.start()
            logger.info("Selected upload background thread started for ids=%s", startable)
            return {
                "ok": True,
                "message": "Selected upload started.",
                "data": {
                    "requested": requested,
                    "started": len(startable),
                    "completed": 0,
                    "failed": 0,
                    "skipped": skipped,
                },
            }
        except Exception as exc:
            logger.exception("Upload selected clips failed.")
            return {
                "ok": False,
                "message": f"Could not start selected upload: {redact(str(exc))}",
                "data": {"requested": len(_coerce_ids(jobIds)), "started": 0, "completed": 0, "failed": 0, "skipped": 0},
            }

    def _upload_selected_background(self, job_ids: list[int]) -> None:
        try:
            if self._worker:
                result = self._worker.run_jobs_end_to_end(job_ids)
                logger.info("Selected clip upload run finished for %s: %s", job_ids, redact(str(result)))
        except Exception as exc:
            logger.exception("Selected clip upload run crashed for %s: %s", job_ids, redact(str(exc)))
        finally:
            with self._selected_upload_lock:
                for job_id in job_ids:
                    self._selected_upload_inflight.discard(job_id)

    @Slot("QVariant", result=dict)
    def deleteSelectedClips(self, jobIds: Any) -> dict[str, Any]:
        try:
            ids = _coerce_ids(jobIds)
            logger.info("GUI selected delete requested for job ids: %s", ids)
            if not ids:
                return {
                    "ok": False,
                    "message": "No clips selected.",
                    "deleted": 0,
                    "skipped": 0,
                    "errors": [],
                    "data": {"requested": 0, "deleted": 0, "skipped": 0, "failed": 0},
                }
            cfg = load_config()
            watch_folder = Path(cfg.watch_folder).resolve(strict=False) if cfg.watch_folder else None
            if not watch_folder:
                return {
                    "ok": False,
                    "message": "Watch folder is not configured.",
                    "deleted": 0,
                    "skipped": len(ids),
                    "errors": ["watch folder missing"],
                    "data": {"requested": len(ids), "deleted": 0, "skipped": len(ids), "failed": 0},
                }

            deletable_statuses = {"detected", "waiting_for_file_ready", "queued", "failed", "skipped"}
            deleted = 0
            skipped = 0
            failed = 0
            errors: list[str] = []
            for job_id in ids:
                job = self._state.get_job(job_id)
                if not job:
                    skipped += 1
                    errors.append(f"{job_id}: missing")
                    continue
                status = str(job.get("status") or "")
                source = Path(str(job.get("source_path") or "")).resolve(strict=False)
                if status not in deletable_statuses:
                    skipped += 1
                    errors.append(f"{job.get('original_filename') or job_id}: busy or already uploaded")
                    continue
                if not _is_inside(source, watch_folder) or not source.is_file():
                    skipped += 1
                    errors.append(f"{job.get('original_filename') or job_id}: file not found in watch folder")
                    continue
                try:
                    source.unlink()
                    if status != "skipped":
                        try:
                            self._state.transition_job(int(job_id), "skipped", "Deleted from dashboard.")
                        except Exception:
                            self._state.add_event(int(job_id), "deleted_from_dashboard", "Source file deleted.")
                    deleted += 1
                except OSError as exc:
                    failed += 1
                    errors.append(f"{job.get('original_filename') or job_id}: {redact(str(exc))}")
            logger.info("Selected delete result requested=%s deleted=%s skipped=%s failed=%s errors=%s", len(ids), deleted, skipped, failed, errors)
            return {
                "ok": deleted > 0 and failed == 0,
                "message": f"Deleted {deleted} clip(s); skipped {skipped}; failed {failed}.",
                "deleted": deleted,
                "skipped": skipped,
                "failed": failed,
                "errors": errors,
                "data": {"requested": len(ids), "deleted": deleted, "skipped": skipped, "failed": failed},
            }
        except Exception as exc:
            logger.exception("Delete selected clips failed.")
            ids = _coerce_ids(jobIds)
            return {
                "ok": False,
                "message": f"Could not delete selected clips: {redact(str(exc))}",
                "deleted": 0,
                "skipped": 0,
                "failed": len(ids),
                "errors": [redact(str(exc))],
                "data": {"requested": len(ids), "deleted": 0, "skipped": 0, "failed": len(ids)},
            }

    @Slot(result=dict)
    def clearUploadedFolder(self) -> dict[str, Any]:
        try:
            cfg = load_config()
            if not cfg.uploaded_folder:
                return {"ok": False, "message": "Uploaded folder is not configured.", "deleted": 0, "skipped": 0}
            folder = Path(cfg.uploaded_folder)
            if not folder.is_dir():
                return {"ok": False, "message": "Uploaded folder does not exist.", "deleted": 0, "skipped": 0}
            deleted = 0
            skipped = 0
            for path in folder.iterdir():
                try:
                    if path.is_file():
                        path.unlink()
                        deleted += 1
                    else:
                        skipped += 1
                except OSError as exc:
                    skipped += 1
                    logger.warning("Could not clear uploaded file %s: %s", path, redact(str(exc)))
            return {"ok": skipped == 0, "message": f"Cleared {deleted} archived file(s); skipped {skipped}.", "deleted": deleted, "skipped": skipped}
        except Exception as exc:
            logger.exception("Clear uploaded folder failed.")
            return {"ok": False, "message": f"Could not clear uploaded folder: {redact(str(exc))}", "deleted": 0, "skipped": 0}

    @Slot(int, result=dict)
    def openClipFolder(self, jobId: int) -> dict[str, Any]:
        try:
            job = self._state.get_job(jobId)
            if not job:
                return {"ok": False, "message": "Clip was not found."}
            candidates = [job.get("archive_path"), job.get("source_path"), job.get("compressed_path")]
            for value in candidates:
                if value:
                    path = Path(str(value))
                    folder = path if path.is_dir() else path.parent
                    if folder.exists():
                        return self._open_path(str(folder), "Clip folder")
            return {"ok": False, "message": "Clip folder does not exist."}
        except Exception as exc:
            logger.exception("Open clip folder failed.")
            return {"ok": False, "message": f"Could not open clip folder: {redact(str(exc))}"}

    @Slot(result=dict)
    def clearCompletedHistory(self) -> dict[str, Any]:
        removed = self._state.cleanup_old_completed(days=30)
        return {"ok": True, "message": f"Removed {removed} old completed job(s).", "removed": removed}

    @Slot(result="QVariant")
    def getRecentLogs(self) -> list[str]:
        try:
            return [redact(line) for line in recent_logs(250)]
        except Exception as exc:
            logger.exception("Failed to read recent logs for GUI.")
            return [f"Could not load logs: {redact(str(exc))}"]

    @Slot(result=str)
    def getLogsFolderPath(self) -> str:
        try:
            return str(logs_dir())
        except Exception:
            return ""

    @Slot()
    def exitApp(self) -> None:
        logger.info("Exit requested from GUI/tray.")
        if self._app is not None:
            self._app.quit()
        else:
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def _open_path(self, path: str, label: str) -> dict[str, Any]:
        if not path:
            return {"ok": False, "message": f"{label} is not configured."}
        target = Path(path)
        if not target.exists():
            return {"ok": False, "message": f"{label} does not exist."}
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        return {"ok": bool(opened), "message": f"Opened {label.lower()}." if opened else f"Could not open {label.lower()}."}


def _coerce_config(raw: dict[str, Any]) -> dict[str, Any]:
    valid = set(AppConfig.__dataclass_fields__)
    coerced = {key: raw[key] for key in valid if key in raw}
    for integer_field in ("max_upload_size_mb", "crf", "poll_interval_seconds", "max_ffmpeg_attempts", "max_jobs_per_process_run"):
        if integer_field in coerced:
            coerced[integer_field] = int(coerced[integer_field])
    for float_field in ("file_stability_interval_seconds", "file_ready_timeout_seconds", "watcher_poll_interval_seconds"):
        if float_field in coerced:
            coerced[float_field] = float(coerced[float_field])
    for float_field in ("discord_timeout_seconds", "discord_retry_base_seconds", "discord_retry_max_seconds"):
        if float_field in coerced:
            coerced[float_field] = float(coerced[float_field])
    for float_field in ("auto_pipeline_interval_seconds",):
        if float_field in coerced:
            coerced[float_field] = float(coerced[float_field])
    for integer_field in (
        "file_stability_checks",
        "discord_max_retries",
        "max_upload_jobs_per_run",
        "max_archive_jobs_per_run",
        "max_auto_jobs_per_cycle",
        "repeated_failure_limit",
        "thumbnail_width",
    ):
        if integer_field in coerced:
            coerced[integer_field] = int(coerced[integer_field])
    for bool_field in (
        "process_while_valorant_running",
        "discord_wait_for_response",
        "cleanup_compressed_after_upload",
        "cleanup_compressed_after_archive",
        "keep_failed_compressed_files",
        "auto_process_enabled",
        "auto_upload_enabled",
        "auto_archive_enabled",
        "auto_retry_failed_jobs",
        "pause_on_repeated_failures",
        "generate_thumbnails_enabled",
        "use_henrik_stats",
        "start_with_windows",
    ):
        if bool_field in coerced:
            coerced[bool_field] = bool(coerced[bool_field])
    return coerced


def _normalize_config_input(value: Any) -> dict[str, Any]:
    if hasattr(value, "toVariant"):
        value = value.toVariant()
    try:
        raw = dict(value or {})
    except Exception:
        raw = {}
    aliases = {
        "watchFolder": "watch_folder",
        "uploadedFolder": "uploaded_folder",
        "valorantRegion": "valorant_region",
        "startWithWindows": "start_with_windows",
        "useHenrikStats": "use_henrik_stats",
    }
    normalized: dict[str, Any] = {}
    for key, raw_value in raw.items():
        name = aliases.get(str(key), str(key))
        if name in {"watch_folder", "uploaded_folder", "riot_username", "riot_tagline", "valorant_region", "ffmpeg_path", "ffmpeg_source_mode"}:
            normalized[name] = str(raw_value or "").strip()
        else:
            normalized[name] = raw_value
    if "valorant_region" in normalized:
        normalized["valorant_region"] = str(normalized["valorant_region"] or "ap").strip().lower()
    return normalized


def _startup_result_to_dict(result: Any | None) -> dict[str, Any]:
    if result is None:
        return {"ok": True, "supported": startup_supported(), "enabled": is_startup_enabled() if startup_supported() else False, "message": "", "command": ""}
    return {
        "ok": bool(result.ok),
        "supported": bool(result.supported),
        "enabled": bool(result.enabled),
        "message": str(result.message),
        "command": str(result.command),
    }


def _issue_to_dict(issue: Any) -> dict[str, str]:
    return {"field": issue.field, "message": issue.message, "severity": issue.severity}


def _redacted_webhook(value: str) -> str:
    if not value:
        return "Not configured"
    tail = value[-4:] if len(value) >= 4 else "****"
    return f"https://discord.com/api/webhooks/...{tail}"


def _redacted_token(value: str) -> str:
    if not value:
        return "Not configured"
    tail = value[-4:] if len(value) >= 4 else "****"
    return f"****{tail}"


def _looks_redacted(value: str) -> bool:
    stripped = value.strip()
    return not stripped or "..." in stripped or stripped.startswith("****") or "REDACTED" in stripped.upper()


def _coerce_ids(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        text = value.decode("utf-8", errors="ignore") if isinstance(value, bytes) else value
        try:
            parsed = json.loads(text)
            raw_values = parsed if isinstance(parsed, list) else [parsed]
        except (TypeError, json.JSONDecodeError):
            raw_values = [text]
    else:
        try:
            raw_values = list(value)
        except TypeError:
            raw_values = [value]
    ids: list[int] = []
    for raw in raw_values:
        try:
            job_id = int(raw)
        except (TypeError, ValueError):
            continue
        if job_id > 0 and job_id not in ids:
            ids.append(job_id)
    return ids


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _job_label(job: dict[str, Any] | None) -> str:
    if not job:
        return "None"
    return str(job.get("original_filename") or job.get("source_path") or "Unknown")


def _job_error(job: dict[str, Any] | None) -> str:
    if not job:
        return ""
    category = job.get("error_category") or "failed"
    message = _one_line(job.get("error_message") or "")
    friendly = _friendly_error_category(str(category))
    if not message:
        return friendly
    if message.startswith(friendly):
        return _truncate(message, 180)
    return _truncate(f"{friendly}: {message}", 180)


def _dashboard_clip_for_qml(job: dict[str, Any], config: AppConfig | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    item = _job_for_qml(job)
    status = str(job.get("status") or "")
    cached = cached_thumbnail_for_job(job, cfg)
    thumbnail_path = cached.path if cached.ok else ""
    thumbnail_mtime = _path_mtime(thumbnail_path) if thumbnail_path else 0
    compressed_size = job.get("compressed_size")
    item.update(
        {
            "job_id": int(job.get("id") or 0),
            "raw_status": status,
            "friendly_status": _status_label(status),
            "statusLabel": _status_label(status),
            "size_display": item.get("compressedSize") or item.get("originalSize") or "",
            "thumbnail_path": thumbnail_path,
            "thumbnail_url": _thumbnail_file_url(thumbnail_path) if thumbnail_path else "",
            "thumbnail_expected_path": str(thumbnail_path_for_job(job, cfg)),
            "thumbnail_status": "ready" if thumbnail_path else "missing",
            "thumbnail_mtime": thumbnail_mtime,
            "source_path": str(job.get("source_path") or ""),
            "safe_id": int(job.get("id") or 0),
            "selectable": status in {"detected", "waiting_for_file_ready", "queued", "failed"},
            "uploadable": status in {"failed", "queued", "processed", "uploaded"},
            "deletable": status in {"detected", "waiting_for_file_ready", "queued", "failed", "skipped"},
            "detailSummary": _clip_summary(job),
            "createdOrDetectedAt": str(job.get("detected_at") or job.get("created_at") or ""),
            "uploadArchiveStatus": _upload_archive_status(job),
            "compressedSizeBytes": "" if compressed_size is None else str(compressed_size),
        }
    )
    item["summary"] = _truncate(_one_line(str(item.get("summary") or "")), 140)
    item["errorSummary"] = _truncate(_one_line(str(item.get("errorSummary") or "")), 140)
    return item


def _job_for_qml(job: dict[str, Any]) -> dict[str, Any]:
    size = job.get("original_size")
    compressed_size = job.get("compressed_size")
    status = str(job.get("status") or "")
    return {
        "id": int(job.get("id") or 0),
        "job_id": int(job.get("id") or 0),
        "filename": str(job.get("original_filename") or ""),
        "status": status,
        "statusLabel": _status_label(status),
        "sourcePath": str(job.get("source_path") or ""),
        "originalSize": "" if size is None else _format_bytes(int(size)),
        "compressedSize": "" if compressed_size is None else _format_bytes(int(compressed_size)),
        "compressedPath": str(job.get("compressed_path") or ""),
        "discordResponseCode": "" if job.get("discord_response_code") is None else str(job.get("discord_response_code")),
        "discordMessageId": str(job.get("discord_message_id") or ""),
        "archivePath": str(job.get("archive_path") or ""),
        "cleanupStatus": str(job.get("cleanup_status") or ""),
        "cleanupError": str(job.get("cleanup_error") or ""),
        "createdAt": str(job.get("created_at") or ""),
        "detectedAt": str(job.get("detected_at") or ""),
        "uploadedAt": str(job.get("uploaded_at") or ""),
        "summary": _clip_summary(job),
        "errorSummary": _job_error(job) if job.get("status") == "failed" else "",
    }


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def _default_worker_status() -> dict[str, Any]:
    return {
        "state": "stopped",
        "watcher_enabled": False,
        "watch_folder": "",
        "last_scan_time": "",
        "last_error": "",
    }


def _default_auto_status() -> dict[str, Any]:
    return {
        "enabled": False,
        "state": "stopped",
        "last_cycle_time": "",
        "last_cycle_summary": "",
        "repeated_failure_count": 0,
    }


def _status_label(status: str) -> str:
    labels = {
        "queued": "Ready",
        "processing": "Compressing",
        "processed": "Ready",
        "uploading": "Uploading",
        "uploaded": "Uploaded",
        "archived": "Done",
        "failed": "Failed",
        "skipped": "Skipped",
        "detected": "Detected",
        "waiting_for_file_ready": "Preparing",
    }
    return labels.get(status, status or "Unknown")


def _clip_summary(job: dict[str, Any]) -> str:
    if job.get("status") == "failed":
        return _job_error(job)
    cleanup_status = job.get("cleanup_status")
    cleanup_error = job.get("cleanup_error")
    if cleanup_status == "failed" and cleanup_error:
        return f"Cleanup issue: {cleanup_error}"
    if job.get("status") == "archived":
        return "Archived"
    if job.get("status") == "uploaded":
        return "Waiting for archive"
    if job.get("status") == "processed":
        return "Compressed"
    return ""


def _friendly_error_category(category: str) -> str:
    labels = {
        "ffmpeg_missing": "FFmpeg missing",
        "ffmpeg_validation_error": "FFmpeg validation failed",
        "ffmpeg_workdir_unwritable": "FFmpeg work folder is not writable",
        "ffmpeg_output_error": "FFmpeg output error",
        "ffmpeg_output_missing_or_invalid": "FFmpeg output folder missing",
        "ffmpeg_output_permission_error": "FFmpeg cannot write output",
        "ffmpeg_input_missing": "Input clip missing",
        "ffmpeg_input_permission_error": "FFmpeg cannot read clip",
        "ffmpeg_invalid_input": "Clip appears corrupted",
        "ffmpeg_no_output": "FFmpeg made no output",
        "ffmpeg_output_too_large": "Compressed clip too large",
        "ffmpeg_failed": "FFmpeg failed",
        "discord_webhook_not_found": "Webhook not found",
        "discord_webhook_missing": "Webhook missing",
        "discord_webhook_invalid": "Webhook invalid",
        "discord_webhook_forbidden_or_invalid": "Webhook forbidden or invalid",
        "discord_payload_too_large": "Clip is too large for Discord",
        "discord_bad_request": "Discord rejected the upload",
        "discord_rate_limited": "Discord rate limited the upload",
        "discord_network_error": "Network error during upload",
        "discord_timeout": "Discord upload timed out",
        "discord_server_error": "Discord server error",
    }
    return labels.get(category, category.replace("_", " ").capitalize() if category else "Failed")


def _one_line(value: str) -> str:
    return " ".join(redact(str(value)).split())


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _local_file_url(path: str | Path) -> str:
    if not path:
        return ""
    return QUrl.fromLocalFile(str(Path(path))).toString()


def _thumbnail_file_url(path: str | Path) -> str:
    url = _local_file_url(path)
    mtime = _path_mtime(path)
    return f"{url}?v={mtime}" if url and mtime else url


def _path_mtime(path: str | Path) -> int:
    if not path:
        return 0
    try:
        return int(Path(path).stat().st_mtime)
    except OSError:
        return 0


def _upload_archive_status(job: dict[str, Any]) -> str:
    status = str(job.get("status") or "")
    if status == "archived":
        return "Archived"
    if status == "uploaded":
        return "Uploaded, waiting for archive"
    if status == "uploading":
        return "Uploading"
    if status == "processed":
        return "Compressed, ready to upload"
    return _status_label(status)
