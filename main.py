from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import logging
import os
import sys
from pathlib import Path

from app.qt_runtime import configure_qt_runtime

configure_qt_runtime()

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QIcon, QWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from app.config import app_data_dir, config_path, load_config, state_db_path, work_dir
from app.discord_uploader import redact_webhook_url, validate_webhook_url
from app.ffmpeg_runner import (
    get_bundled_ffmpeg_path,
    get_bundled_ffprobe_path,
    resolve_ffmpeg_path,
    validate_ffmpeg,
)
from app.file_ready import wait_until_file_ready
from app.gui_bridge import GuiBridge
from app.logging_setup import setup_logging
from app.secrets import DISCORD_WEBHOOK_KEY, HENRIK_API_KEY, get_secret, redact, secrets_backend_summary
from app.single_instance import SingleInstanceServer, notify_existing_instance
from app.startup import get_startup_command, is_startup_enabled, is_supported as startup_supported
from app.state import StateStore
from app.tray import TrayController
from app.valorant_stats import clear_valorant_stats_cache, fetch_valorant_stats
from app.worker import ClipWorker


logger = logging.getLogger(__name__)


class DashboardController(QObject):
    def __init__(self, bridge: GuiBridge, icon_path: Path | None = None) -> None:
        super().__init__()
        self.bridge = bridge
        self.icon_path = icon_path
        self.engine: QQmlApplicationEngine | None = None
        self.window = None

    @Slot()
    def open_dashboard(self) -> None:
        if self.engine is None:
            self.engine = QQmlApplicationEngine()
            self.engine.rootContext().setContextProperty("bridge", self.bridge)
            qml_path = Path(__file__).resolve().parent / "app" / "gui" / "main.qml"
            self.engine.load(QUrl.fromLocalFile(str(qml_path)))
            if not self.engine.rootObjects():
                logger.error("Failed to load QML dashboard from %s.", qml_path)
                return
            self.window = self.engine.rootObjects()[0]
            if self.icon_path and self.icon_path.is_file():
                self.window.setIcon(QIcon(str(self.icon_path)))
        if self.window is not None:
            if self.window.visibility() == QWindow.Visibility.Minimized:
                self.window.showNormal()
            self.window.show()
            self.window.raise_()
            self.window.requestActivate()


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ClipDis")
    parser.add_argument("--smoke-check", action="store_true", help="Initialize core app objects and exit.")
    parser.add_argument("--qml-smoke-check", action="store_true", help="Load the QML dashboard and exit.")
    parser.add_argument("--diagnose", action="store_true", help="Print redacted runtime diagnostics and exit.")
    parser.add_argument("--test-one-clip", help="Process, upload, and archive exactly one clip path, then exit.")
    parser.add_argument("--test-valorant-stats", action="store_true", help="Test stored Henrik/Valorant stats settings and exit.")
    parser.add_argument("--name", help="Optional Riot name override for --test-valorant-stats.")
    parser.add_argument("--tag", help="Optional Riot tag override for --test-valorant-stats.")
    parser.add_argument("--region", choices=["ap", "eu", "na", "kr", "latam", "br"], help="Optional Valorant region override for --test-valorant-stats.")
    parser.add_argument("--list-watch-clips", action="store_true", help="Print a redacted summary of manageable watch-folder clips and exit.")
    parser.add_argument("--retry-failed-category", help="Queue failed jobs with this category, or 'all'.")
    parser.add_argument("--limit", type=int, default=1, help="Limit for retry/list-style maintenance commands.")
    args = parser.parse_args(argv)

    log_path = setup_logging()
    logger.info("Starting Qt tray shell. Log file: %s", log_path)

    if args.diagnose:
        _diagnose_runtime()
        return 0

    if args.test_one_clip:
        return _test_one_clip(Path(args.test_one_clip))

    if args.test_valorant_stats:
        _test_valorant_stats(args.name, args.tag, args.region)
        return 0

    if args.list_watch_clips:
        _list_watch_clips()
        return 0

    if args.retry_failed_category:
        return _retry_failed_category(args.retry_failed_category, args.limit)

    if args.qml_smoke_check:
        return _qml_smoke_check()

    _set_windows_app_user_model_id()
    load_config()
    recovered_jobs = StateStore().reset_incomplete_jobs_on_startup()
    if recovered_jobs:
        logger.info("Recovered %s incomplete job(s) on startup.", recovered_jobs)

    app = QApplication(sys.argv[:1])
    app.setApplicationName("ClipDis")
    app.setQuitOnLastWindowClosed(False)
    icon_path = _app_icon_path()
    app.setWindowIcon(QIcon(str(icon_path)))

    if not args.smoke_check and notify_existing_instance():
        logger.info("Existing ClipDis instance found; requested dashboard show and exiting.")
        return 0

    worker = ClipWorker()
    worker.start()
    app.aboutToQuit.connect(worker.stop)

    bridge = GuiBridge(app, worker)
    dashboard = DashboardController(bridge, icon_path)
    tray = TrayController(app, bridge, dashboard.open_dashboard, icon_path)
    tray.show()

    if args.smoke_check:
        logger.info("Smoke check completed.")
        worker.stop()
        return 0

    single_instance_server = SingleInstanceServer(dashboard.open_dashboard)
    single_instance_server.listen()
    app.aboutToQuit.connect(single_instance_server.close)

    dashboard.open_dashboard()

    return app.exec()


def _diagnose_runtime() -> None:
    cfg = load_config()
    state = StateStore()
    state.initialize_database()
    webhook = get_secret(DISCORD_WEBHOOK_KEY)
    henrik = get_secret(HENRIK_API_KEY)
    ffmpeg_path = resolve_ffmpeg_path(cfg)
    ffmpeg_result = validate_ffmpeg(ffmpeg_path)

    print("ClipDis diagnostics")
    print(f"app_data_dir={app_data_dir()}")
    print(f"config_path={config_path()}")
    print(f"watch_folder={cfg.watch_folder or 'not configured'}")
    print(f"uploaded_folder={cfg.uploaded_folder or 'not configured'}")
    print(f"work_folder={work_dir()}")
    print(f"state_db={state_db_path()}")
    print(f"ffmpeg_resolved={ffmpeg_path}")
    print(f"ffmpeg_exists={Path(ffmpeg_path).is_file()}")
    print(f"ffprobe_path={get_bundled_ffprobe_path()}")
    print(f"ffprobe_exists={get_bundled_ffprobe_path().is_file()}")
    print(f"ffmpeg_validation_ok={ffmpeg_result.ok}")
    print(f"ffmpeg_validation_category={ffmpeg_result.category}")
    print(f"work_writable={_folder_writable(work_dir())}")
    print(f"archive_writable={_folder_writable(Path(cfg.uploaded_folder)) if cfg.uploaded_folder else False}")
    webhook_valid = validate_webhook_url(webhook)
    webhook_live = _webhook_live_status(webhook) if webhook_valid[0] else {"ok": False, "status_code": "", "message": webhook_valid[1]}
    print(f"webhook_configured={bool(webhook)}")
    print(f"webhook_redacted={redact_webhook_url(webhook)}")
    print(f"webhook_shape_valid={webhook_valid[0]}")
    print(f"webhook_live_ok={webhook_live['ok']}")
    print(f"webhook_live_status={webhook_live['status_code']}")
    print(f"webhook_live_message={webhook_live['message']}")
    print(f"henrik_configured={bool(henrik)}")
    print(f"secrets_backend={secrets_backend_summary()}")
    print(f"startup_supported={startup_supported()}")
    print(f"startup_enabled={is_startup_enabled() if startup_supported() else False}")
    print(f"startup_command={get_startup_command() if startup_supported() else ''}")
    counts = state.count_by_status()
    failures = state.list_failed_jobs(limit=500)
    print(f"db_counts={counts}")
    print(f"active_jobs={sum(counts.get(status, 0) for status in ('processing', 'uploading', 'waiting_for_file_ready'))}")
    print(f"failure_categories={dict(Counter(job.get('error_category') or 'unknown' for job in failures))}")


def _qml_smoke_check() -> int:
    _set_windows_app_user_model_id()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ClipDis")
    app.setWindowIcon(QIcon(str(_app_icon_path())))
    bridge = GuiBridge(app, None)
    dashboard = DashboardController(bridge, _app_icon_path())
    dashboard.open_dashboard()
    app.processEvents()
    loaded = dashboard.engine is not None and bool(dashboard.engine.rootObjects())
    if dashboard.window is not None:
        dashboard.window.hide()
    print(f"qml_loaded={loaded}")
    return 0 if loaded else 1


def _resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def _app_icon_path() -> Path:
    candidates = [
        _resource_path("app", "gui", "assets", "app_icon.ico"),
        _resource_path("omen.ico"),
        Path(__file__).resolve().parent / "app" / "gui" / "assets" / "app_icon.ico",
        Path(__file__).resolve().parent / "omen.ico",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[-1]


def _set_windows_app_user_model_id() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Hermann.ClipDis")
    except Exception as exc:
        logger.debug("Could not set Windows AppUserModelID: %s", exc)


def _test_valorant_stats(name: str | None = None, tag: str | None = None, region: str | None = None) -> None:
    cfg = load_config()
    if name:
        cfg = replace(cfg, riot_username=name)
    if tag:
        cfg = replace(cfg, riot_tagline=tag)
    if region:
        cfg = replace(cfg, valorant_region=region)
    key_present = bool(get_secret(HENRIK_API_KEY))
    clear_valorant_stats_cache()
    print("ClipDis Valorant stats test")
    print(f"henrik_enabled={bool(cfg.use_henrik_stats)}")
    print(f"name_present={bool((cfg.riot_username or '').strip())}")
    print(f"tag_present={bool((cfg.riot_tagline or '').strip())}")
    print(f"region={cfg.valorant_region or 'ap'}")
    print(f"key_present={key_present}")
    result = fetch_valorant_stats(cfg, timeout_seconds=10)
    print(f"available={result.available}")
    print(f"category={result.category}")
    print(f"rank={result.rank or 'Unknown'}")
    print(f"account_level={'Unknown' if result.account_level is None else result.account_level}")
    print(f"rank_category={result.rank_category}")
    print(f"level_category={result.level_category}")
    print(f"message={redact(result.message)}")


def _test_one_clip(path: Path) -> int:
    cfg = load_config()
    state = StateStore()
    state.initialize_database()
    clip = path.expanduser().resolve(strict=False)
    print(f"clip={clip}")
    if not clip.is_file():
        print("ok=False")
        print("error=clip file does not exist")
        return 2
    ready = wait_until_file_ready(clip, cfg)
    print(f"file_ready={ready.ready}")
    print(f"file_ready_reason={ready.reason}")
    if not ready.ready:
        print("ok=False")
        return 3

    job = state.get_latest_job_by_source_path(clip) or state.create_or_get_job(clip)
    job_id = int(job["id"])
    if job["status"] == "detected":
        state.transition_job(job_id, "waiting_for_file_ready", "Diagnostic single-clip test.")
        state.transition_job(job_id, "queued", "Diagnostic clip is ready.")
    elif job["status"] == "waiting_for_file_ready":
        state.transition_job(job_id, "queued", "Diagnostic clip is ready.")

    worker = ClipWorker()
    result = worker.run_job_end_to_end(job_id)
    final_job = state.get_job(job_id) or {}
    print(f"job_id={job_id}")
    print(f"ok={result.get('ok')}")
    print(f"message={redact(str(result.get('message', '')))}")
    print(f"final_status={final_job.get('status')}")
    print(f"compressed_path={final_job.get('compressed_path') or ''}")
    print(f"compressed_size={final_job.get('compressed_size') or ''}")
    print(f"discord_response_code={final_job.get('discord_response_code') or ''}")
    print(f"discord_message_id={final_job.get('discord_message_id') or ''}")
    print(f"archive_path={final_job.get('archive_path') or ''}")
    print(f"error_category={final_job.get('error_category') or ''}")
    print(f"error_message={redact(str(final_job.get('error_message') or ''))[:500]}")
    print(f"original_exists={clip.exists()}")
    return 0 if result.get("ok") else 1


def _list_watch_clips() -> None:
    from app.file_ready import should_ignore_path

    cfg = load_config()
    watch = Path(cfg.watch_folder) if cfg.watch_folder else None
    if not watch or not watch.is_dir():
        print("watch_folder_missing=True")
        return
    manageable: list[tuple[int, Path]] = []
    ignored = 0
    for candidate in watch.rglob("*.mp4"):
        if not candidate.is_file():
            continue
        ignore, _reason = should_ignore_path(candidate, watch, cfg)
        if ignore:
            ignored += 1
            continue
        try:
            manageable.append((candidate.stat().st_size, candidate))
        except OSError:
            ignored += 1
    manageable.sort()
    print(f"watch_folder={watch}")
    print(f"manageable_mp4_count={len(manageable)}")
    print(f"ignored_mp4_count={ignored}")
    print("smallest")
    for size, path in manageable[:5]:
        print(f"{path.name}\t{size}\t{size / 1024 / 1024:.2f} MB")
    print("largest")
    for size, path in manageable[-5:]:
        print(f"{path.name}\t{size}\t{size / 1024 / 1024:.2f} MB")


def _retry_failed_category(category: str, limit: int) -> int:
    state = StateStore()
    state.initialize_database()
    limit = max(1, min(int(limit), 25))
    category = category.strip()
    retried = 0
    skipped = 0
    for job in state.list_failed_jobs(limit=500):
        if category.lower() != "all" and job.get("error_category") != category:
            continue
        if retried >= limit:
            break
        source = Path(str(job.get("source_path") or ""))
        if not source.is_file():
            skipped += 1
            print(f"skipped_missing_source={job.get('id')} {job.get('original_filename')}")
            continue
        try:
            updated = state.retry_job(int(job["id"]))
            retried += 1
            print(f"retried={updated['id']} {updated['original_filename']}")
        except Exception as exc:
            skipped += 1
            print(f"skipped={job.get('id')} {redact(str(exc))}")
    print(f"retried_count={retried}")
    print(f"skipped_count={skipped}")
    return 0 if retried else 1


def _folder_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".diagnostic_write.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception as exc:
        logger.warning("Folder is not writable: %s", redact(str(exc)))
        return False


def _webhook_live_status(webhook: str) -> dict[str, object]:
    try:
        import requests

        response = requests.get(webhook, timeout=10)
        if response.status_code == 200:
            return {"ok": True, "status_code": response.status_code, "message": "Discord webhook exists."}
        if response.status_code == 404:
            return {"ok": False, "status_code": response.status_code, "message": "Discord webhook was not found."}
        if response.status_code in (401, 403):
            return {"ok": False, "status_code": response.status_code, "message": "Discord webhook is forbidden or invalid."}
        return {"ok": False, "status_code": response.status_code, "message": f"Unexpected Discord HTTP {response.status_code}."}
    except Exception as exc:
        return {"ok": False, "status_code": "", "message": redact(str(exc))}


if __name__ == "__main__":
    raise SystemExit(run())
