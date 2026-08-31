from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.archive import archive_uploaded_job, cleanup_compressed_file
from app.config import AppConfig, WatchFolderProfile, load_config, profile_uploaded_folder
from app.discord_uploader import upload_processed_job
from app.ffmpeg_runner import compress_clip
from app.file_ready import should_ignore_path, wait_until_file_ready
from app.secrets import redact
from app.state import InvalidTransitionError, StateStore


logger = logging.getLogger(__name__)


@dataclass
class WorkerStatus:
    state: str = "stopped"
    watcher_enabled: bool = False
    # Legacy summary field retained for older GUI bindings. It contains the
    # first configured watch root; new UI should use profile_statuses.
    watch_folder: str = ""
    watch_folder_count: int = 0
    missing_watch_folder_count: int = 0
    profile_statuses: list[dict[str, Any]] = field(default_factory=list)
    last_scan_time: str = ""
    last_error: str = ""
    scanned_files: int = 0
    queued_files: int = 0
    ignored_files: int = 0
    in_progress_path: str = ""
    message: str = ""
    processing_active: bool = False
    auto_pipeline_enabled: bool = False
    auto_pipeline_state: str = "stopped"
    last_auto_cycle_time: str = ""
    last_auto_cycle_summary: str = ""
    repeated_failure_count: int = 0


class ClipWorker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process_thread: threading.Thread | None = None
        self._upload_thread: threading.Thread | None = None
        self._archive_thread: threading.Thread | None = None
        self._end_to_end_thread: threading.Thread | None = None
        self._auto_thread: threading.Thread | None = None
        self._processing_lock = threading.Lock()
        self._upload_lock = threading.Lock()
        self._archive_lock = threading.Lock()
        self._end_to_end_lock = threading.Lock()
        self._auto_cycle_lock = threading.Lock()
        self._auto_stop_event = threading.Event()
        self._auto_enabled_override: bool | None = None
        self._status = WorkerStatus()
        self._upload_processed_job = upload_processed_job
        self._compress_clip = compress_clip

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {"ok": True, "message": "Worker already running."}
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="ClipWorker", daemon=True)
            self._set_status(state="running", watcher_enabled=True, message="Worker running.")
            self._thread.start()
        logger.info("Clip worker started.")
        self.start_auto_pipeline()
        return {"ok": True, "message": "Worker started."}

    def stop(self, timeout: float = 5.0) -> dict[str, Any]:
        logger.info("Clip worker stopping.")
        self._stop_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self.stop_auto_pipeline(timeout=timeout)
        self._set_status(state="stopped", watcher_enabled=False, in_progress_path="", message="Worker stopped.")
        return {"ok": True, "message": "Worker stopped."}

    def pause(self) -> dict[str, Any]:
        self._pause_event.set()
        self._set_status(state="paused", watcher_enabled=False, auto_pipeline_state="paused", message="Watching paused.")
        logger.info("Clip worker paused.")
        return {"ok": True, "message": "Watching paused."}

    def resume(self) -> dict[str, Any]:
        self._pause_event.clear()
        self._set_status(state="running", watcher_enabled=True, auto_pipeline_state="running", message="Watching resumed.")
        logger.info("Clip worker resumed.")
        return {"ok": True, "message": "Watching resumed."}

    def process_queue_now(self, wait: bool = False) -> dict[str, Any]:
        if self._processing_lock.locked():
            return {"ok": False, "message": "Queue processing is already running.", "processed": 0, "failed": 0}
        if wait:
            return self._process_queue_run()
        self._process_thread = threading.Thread(target=self._process_queue_run, name="ClipProcessor", daemon=True)
        self._process_thread.start()
        summary = StateStore().get_queue_summary()
        return {
            "ok": True,
            "message": f"Queue processing started for up to {load_config().max_jobs_per_process_run} job(s).",
            "queueCount": summary["queue_count"],
        }

    def upload_processed_now(self, wait: bool = False) -> dict[str, Any]:
        if self._upload_lock.locked():
            return {"ok": False, "message": "Upload is already running.", "uploaded": 0, "failed": 0}
        if wait:
            return self._upload_processed_run()
        self._upload_thread = threading.Thread(target=self._upload_processed_run, name="ClipUploader", daemon=True)
        self._upload_thread.start()
        summary = StateStore().get_queue_summary()
        return {
            "ok": True,
            "message": f"Upload started for up to {load_config().max_upload_jobs_per_run} processed job(s).",
            "processedCount": summary["processed_count"],
        }

    def archive_uploaded_now(self, wait: bool = False) -> dict[str, Any]:
        if self._archive_lock.locked():
            return {"ok": False, "message": "Archive is already running.", "archived": 0, "failed": 0}
        if wait:
            return self._archive_uploaded_run()
        self._archive_thread = threading.Thread(target=self._archive_uploaded_run, name="ClipArchiver", daemon=True)
        self._archive_thread.start()
        return {"ok": True, "message": f"Archive started for up to {load_config().max_archive_jobs_per_run} uploaded job(s)."}

    def run_end_to_end_now(self, wait: bool = False) -> dict[str, Any]:
        if self._end_to_end_lock.locked():
            return {"ok": False, "message": "End-to-end run is already running.", "errors": ["already running"]}
        if wait:
            return self._run_end_to_end()
        self._end_to_end_thread = threading.Thread(target=self._run_end_to_end, name="ClipEndToEnd", daemon=True)
        self._end_to_end_thread.start()
        return {"ok": True, "message": "End-to-end run started.", "errors": []}

    def process_job_now(self, job_id: int) -> dict[str, Any]:
        if not self._processing_lock.acquire(blocking=False):
            return {"ok": False, "message": "Queue processing is already running.", "processed": 0, "failed": 0}
        try:
            state = StateStore()
            config = load_config()
            job = state.get_job(int(job_id))
            if not job:
                return {"ok": False, "message": f"Job {job_id} was not found.", "processed": 0, "failed": 1}
            if job["status"] == "failed":
                job = state.retry_job(int(job_id))
            if job["status"] == "processed":
                return {"ok": True, "message": "Job is already processed.", "processed": 0, "failed": 0}
            if job["status"] != "queued":
                return {"ok": False, "message": f"Job must be queued before processing; current status is {job['status']}.", "processed": 0, "failed": 1}
            ok = self._process_one_job(state, job, config)
            return {"ok": ok, "message": "Job processed." if ok else "Job processing failed.", "processed": 1 if ok else 0, "failed": 0 if ok else 1}
        finally:
            self._processing_lock.release()

    def upload_job_now(self, job_id: int) -> dict[str, Any]:
        if not self._upload_lock.acquire(blocking=False):
            return {"ok": False, "message": "Upload is already running.", "uploaded": 0, "failed": 0}
        try:
            state = StateStore()
            config = load_config()
            job = state.get_job(int(job_id))
            if not job:
                return {"ok": False, "message": f"Job {job_id} was not found.", "uploaded": 0, "failed": 1}
            if job["status"] == "uploaded":
                return {"ok": True, "message": "Job is already uploaded.", "uploaded": 0, "failed": 0}
            if job["status"] != "processed":
                return {"ok": False, "message": f"Job must be processed before upload; current status is {job['status']}.", "uploaded": 0, "failed": 1}
            ok = self._upload_one_job(state, job, config)
            return {"ok": ok, "message": "Job uploaded." if ok else "Job upload failed.", "uploaded": 1 if ok else 0, "failed": 0 if ok else 1}
        finally:
            self._upload_lock.release()

    def archive_job_now(self, job_id: int) -> dict[str, Any]:
        if not self._archive_lock.acquire(blocking=False):
            return {"ok": False, "message": "Archive is already running.", "archived": 0, "failed": 0}
        try:
            state = StateStore()
            config = load_config()
            job = state.get_job(int(job_id))
            if not job:
                return {"ok": False, "message": f"Job {job_id} was not found.", "archived": 0, "failed": 1}
            if job["status"] == "archived":
                return {"ok": True, "message": "Job is already archived.", "archived": 0, "failed": 0}
            if job["status"] != "uploaded":
                return {"ok": False, "message": f"Job must be uploaded before archive; current status is {job['status']}.", "archived": 0, "failed": 1}
            ok = self._archive_one_job(state, job, config)
            return {"ok": ok, "message": "Job archived." if ok else "Job archive failed.", "archived": 1 if ok else 0, "failed": 0 if ok else 1}
        finally:
            self._archive_lock.release()

    def run_job_end_to_end(self, job_id: int) -> dict[str, Any]:
        if not self._end_to_end_lock.acquire(blocking=False):
            return {"ok": False, "message": "End-to-end run is already running.", "errors": ["already running"]}
        try:
            state = StateStore()
            job = state.get_job(int(job_id))
            if not job:
                return {"ok": False, "message": f"Job {job_id} was not found.", "errors": ["job missing"]}

            errors: list[str] = []
            if job["status"] in {"failed", "queued"}:
                result = self.process_job_now(job_id)
                if not result.get("ok"):
                    errors.append(result.get("message", "Processing failed."))
                    return {"ok": False, "message": "Single-job run stopped during processing.", "processed_count": 0, "uploaded_count": 0, "archived_count": 0, "failed_count": 1, "errors": errors}
                job = state.get_job(int(job_id)) or job

            if job["status"] == "processed":
                result = self.upload_job_now(job_id)
                if not result.get("ok"):
                    errors.append(result.get("message", "Upload failed."))
                    return {"ok": False, "message": "Single-job run stopped during upload.", "processed_count": 1, "uploaded_count": 0, "archived_count": 0, "failed_count": 1, "errors": errors}
                job = state.get_job(int(job_id)) or job

            archived_count = 0
            if job["status"] == "uploaded":
                result = self.archive_job_now(job_id)
                if result.get("ok"):
                    archived_count = 1
                else:
                    errors.append(result.get("message", "Archive failed."))
                    return {"ok": False, "message": "Single-job run uploaded but archive failed.", "processed_count": 1, "uploaded_count": 1, "archived_count": 0, "failed_count": 0, "errors": errors}

            final_job = state.get_job(int(job_id)) or job
            return {
                "ok": final_job["status"] in {"uploaded", "archived"},
                "message": f"Single-job run finished with status {final_job['status']}.",
                "processed_count": 1 if final_job["status"] in {"processed", "uploaded", "archived"} else 0,
                "uploaded_count": 1 if final_job["status"] in {"uploaded", "archived"} else 0,
                "archived_count": archived_count if final_job["status"] == "archived" else 0,
                "failed_count": 1 if final_job["status"] == "failed" else 0,
                "errors": errors,
            }
        finally:
            self._end_to_end_lock.release()

    def run_jobs_end_to_end(self, job_ids: list[int] | tuple[int, ...]) -> dict[str, Any]:
        """Run the safe end-to-end pipeline for exactly the requested jobs.

        This deliberately avoids the broad queue processors so selected uploads
        cannot accidentally process unrelated queued clips.
        """
        requested_ids: list[int] = []
        for raw_id in job_ids:
            try:
                job_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if job_id > 0 and job_id not in requested_ids:
                requested_ids.append(job_id)

        state = StateStore()
        requested = len(requested_ids)
        started = completed = failed = skipped = 0
        errors: list[str] = []
        runnable_statuses = {"failed", "queued", "processed", "uploaded"}
        active_statuses = {"processing", "uploading"}
        logger.info("Worker selected upload received ids=%s", requested_ids)

        for job_id in requested_ids:
            job = state.get_job(job_id)
            if not job:
                skipped += 1
                logger.info("Worker selected upload skipped job %s: missing", job_id)
                errors.append(f"Job {job_id} was not found.")
                continue
            status = str(job.get("status") or "")
            if status in active_statuses:
                skipped += 1
                logger.info("Worker selected upload skipped job %s: active status %s", job_id, status)
                errors.append(f"{job.get('original_filename') or job_id}: already active")
                continue
            if status == "archived":
                skipped += 1
                logger.info("Worker selected upload skipped job %s: archived", job_id)
                continue
            if status not in runnable_statuses:
                skipped += 1
                logger.info("Worker selected upload skipped job %s: status %s not runnable", job_id, status)
                errors.append(f"{job.get('original_filename') or job_id}: not ready")
                continue

            started += 1
            logger.info("Worker selected upload starting job %s.", job_id)
            try:
                result = self.run_job_end_to_end(job_id)
            except Exception as exc:
                failed += 1
                errors.append(f"{job.get('original_filename') or job_id}: {redact(str(exc))}")
                continue
            if result.get("ok"):
                completed += 1
            else:
                failed += 1
                errors.append(str(result.get("message") or f"Job {job_id} failed."))

        return {
            "ok": failed == 0 and started > 0,
            "message": f"Selected upload finished: completed={completed} failed={failed} skipped={skipped}.",
            "data": {
                "requested": requested,
                "started": started,
                "completed": completed,
                "failed": failed,
                "skipped": skipped,
            },
            "errors": errors,
        }

    def start_auto_pipeline(self) -> dict[str, Any]:
        with self._lock:
            if self._auto_thread and self._auto_thread.is_alive():
                return {"ok": True, "message": "Auto pipeline already running."}
            self._auto_stop_event.clear()
            self._auto_thread = threading.Thread(target=self._auto_loop, name="ClipAutoPipeline", daemon=True)
            self._auto_thread.start()
            self._set_status(auto_pipeline_enabled=self._auto_mode_enabled(load_config()), auto_pipeline_state="running")
        logger.info("Auto pipeline started.")
        return {"ok": True, "message": "Auto pipeline started."}

    def stop_auto_pipeline(self, timeout: float = 5.0) -> dict[str, Any]:
        self._auto_stop_event.set()
        thread = self._auto_thread
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
        self._set_status(auto_pipeline_enabled=False, auto_pipeline_state="stopped")
        logger.info("Auto pipeline stopped.")
        return {"ok": True, "message": "Auto pipeline stopped."}

    def get_auto_pipeline_status(self) -> dict[str, Any]:
        status = self.get_status()
        return {
            "enabled": status["auto_pipeline_enabled"],
            "state": status["auto_pipeline_state"],
            "last_cycle_time": status["last_auto_cycle_time"],
            "last_cycle_summary": status["last_auto_cycle_summary"],
            "repeated_failure_count": status["repeated_failure_count"],
        }

    def set_auto_pipeline_enabled(self, enabled: bool) -> dict[str, Any]:
        self._auto_enabled_override = bool(enabled)
        state = "running" if enabled else "disabled"
        self._set_status(auto_pipeline_enabled=bool(enabled), auto_pipeline_state=state)
        logger.info("Auto pipeline override set to %s.", enabled)
        return {"ok": True, "message": f"Auto mode {'enabled' if enabled else 'disabled'}."}

    def reload_runtime_config(self) -> dict[str, Any]:
        """Refresh profile-dependent status without restarting active jobs."""
        try:
            config = load_config()
            profile_statuses = _profile_statuses(config)
            valid_count = sum(1 for item in profile_statuses if item["exists"])
            missing_count = len(profile_statuses) - valid_count
            first_path = config.watch_folders[0].path if config.watch_folders else ""
            updates: dict[str, Any] = {
                "auto_pipeline_enabled": self._auto_mode_enabled(config),
                "watch_folder": first_path,
                "watch_folder_count": len(config.watch_folders),
                "missing_watch_folder_count": missing_count,
                "profile_statuses": profile_statuses,
                "message": "Runtime configuration refreshed.",
            }
            status = self.get_status()
            if not config.watch_folders:
                updates.update(
                    state="config_required",
                    watcher_enabled=False,
                    last_error="No watch folders are configured.",
                )
            elif valid_count == 0:
                updates.update(
                    state="watch_folders_missing",
                    watcher_enabled=False,
                    last_error="All configured watch folders are missing.",
                )
            else:
                updates["last_error"] = "" if missing_count == 0 else f"{missing_count} watch folder(s) are missing."
                updates["watcher_enabled"] = not self._pause_event.is_set()
                if status.get("state") in {"config_required", "watch_folder_missing", "watch_folders_missing", "error", "stopped"}:
                    updates["state"] = "paused" if self._pause_event.is_set() else "running"
            self._set_status(**updates)
            logger.info("Worker runtime configuration refreshed for %s profile(s).", len(config.watch_folders))
            return {
                "ok": bool(config.watch_folders),
                "message": "Runtime configuration refreshed.",
                "watchFolderCount": len(config.watch_folders),
                "missingWatchFolderCount": missing_count,
                "profiles": profile_statuses,
            }
        except Exception as exc:
            logger.exception("Worker runtime configuration refresh failed.")
            self._set_status(state="error", last_error=redact(str(exc)))
            return {"ok": False, "message": f"Runtime refresh failed: {redact(str(exc))}"}

    def run_auto_cycle(self) -> dict[str, Any]:
        if self._pause_event.is_set():
            return {"ok": False, "message": "Auto pipeline is paused.", "errors": ["paused"]}
        if not self._auto_cycle_lock.acquire(blocking=False):
            logger.warning("Skipping auto cycle because another cycle is already running.")
            return {"ok": False, "message": "Auto cycle already running.", "errors": ["already running"], "skipped": True}
        try:
            config = load_config()
            if not self._auto_mode_enabled(config):
                self._set_status(auto_pipeline_enabled=False, auto_pipeline_state="disabled")
                return {"ok": True, "message": "Auto pipeline disabled.", "errors": [], "skipped": True}
            self._set_status(auto_pipeline_enabled=True, auto_pipeline_state="running")
            logger.info("Starting auto pipeline cycle.")
            processed = uploaded = archived = failed = 0
            errors: list[str] = []
            if config.auto_process_enabled:
                result = self._process_queue_run(limit=int(config.max_auto_jobs_per_cycle))
                processed = int(result.get("processed", 0))
                failed += int(result.get("failed", 0))
                if not result.get("ok", False):
                    errors.append(result.get("message", "Processing failed."))
            if config.auto_upload_enabled:
                result = self._upload_processed_run(limit=min(int(config.max_upload_jobs_per_run), int(config.max_auto_jobs_per_cycle)))
                uploaded = int(result.get("uploaded", 0))
                failed += int(result.get("failed", 0))
                if not result.get("ok", False):
                    errors.append(result.get("message", "Upload failed."))
            if config.auto_archive_enabled:
                result = self._archive_uploaded_run(limit=min(int(config.max_archive_jobs_per_run), int(config.max_auto_jobs_per_cycle)))
                archived = int(result.get("archived", 0))
                failed += int(result.get("failed", 0))
                if not result.get("ok", False):
                    errors.append(result.get("message", "Archive failed."))
            summary = f"Auto cycle: processed={processed} uploaded={uploaded} archived={archived} failed={failed}"
            if failed:
                self._record_auto_failures(failed, config, errors)
            else:
                self._set_status(repeated_failure_count=0)
            self._set_status(last_auto_cycle_time=_timestamp(), last_auto_cycle_summary=summary, message=summary)
            logger.info(summary)
            return {
                "ok": failed == 0,
                "message": summary,
                "processed_count": processed,
                "uploaded_count": uploaded,
                "archived_count": archived,
                "failed_count": failed,
                "skipped_count": 0,
                "errors": errors,
            }
        finally:
            self._auto_cycle_lock.release()

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status.__dict__)

    def scan_now(self) -> dict[str, Any]:
        if self._pause_event.is_set():
            return {"ok": False, "message": "Watcher is paused.", "queued": 0, "ignored": 0}
        return self._scan_once(load_config())

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._pause_event.is_set():
                self._stop_event.wait(0.5)
                continue
            config = load_config()
            self._scan_once(config)
            self._stop_event.wait(float(config.watcher_poll_interval_seconds))

    def _scan_once(self, config: AppConfig) -> dict[str, Any]:
        profiles = list(config.watch_folders)
        if not profiles:
            self._set_status(
                state="config_required",
                watcher_enabled=False,
                watch_folder="",
                watch_folder_count=0,
                missing_watch_folder_count=0,
                profile_statuses=[],
                last_error="No watch folders are configured.",
            )
            return {"ok": False, "message": "No watch folders are configured.", "queued": 0, "ignored": 0, "missing": 0}

        queued = 0
        ignored = 0
        scanned = 0
        missing = 0
        errors: list[str] = []
        statuses: list[dict[str, Any]] = []

        logger.info("Starting watcher scan for %s profile(s).", len(profiles))
        for profile in profiles:
            if self._stop_event.is_set() or self._pause_event.is_set():
                break
            watch_folder = Path(profile.path)
            exists = watch_folder.is_dir()
            statuses.append(_profile_status(profile, exists))
            if not exists:
                missing += 1
                logger.warning("Watch folder missing for profile %s: %s", profile.id, watch_folder)
                continue

            archive_folder = profile_uploaded_folder(profile)
            try:
                for candidate in _iter_files(watch_folder, archive_folder):
                    if self._stop_event.is_set() or self._pause_event.is_set():
                        break
                    scanned += 1
                    ignore, reason = should_ignore_path(candidate, watch_folder, config)
                    if ignore:
                        ignored += 1
                        logger.debug("Ignoring %s: %s", candidate, reason)
                        continue
                    logger.info("Discovered candidate clip in profile %s: %s", profile.id, candidate)
                    if self._handle_candidate(candidate, config, profile):
                        queued += 1
            except PermissionError as exc:
                message = f"Permission denied scanning {profile.name}: {redact(str(exc))}"
                logger.warning(message)
                errors.append(message)
            except OSError as exc:
                message = f"Watcher scan failed for {profile.name}: {redact(str(exc))}"
                logger.warning(message)
                errors.append(message)

        valid_count = len(profiles) - missing
        if valid_count == 0:
            state = "watch_folders_missing"
            watcher_enabled = False
            last_error = "All configured watch folders are missing."
        elif errors:
            state = "running"
            watcher_enabled = True
            last_error = "; ".join(errors[-3:])
        else:
            state = "running"
            watcher_enabled = True
            last_error = "" if missing == 0 else f"{missing} watch folder(s) are missing."

        message = f"Scan complete. Queued {queued} clip(s) from {valid_count} available folder(s)."
        self._set_status(
            state=state,
            watcher_enabled=watcher_enabled,
            watch_folder=profiles[0].path,
            watch_folder_count=len(profiles),
            missing_watch_folder_count=missing,
            profile_statuses=statuses,
            last_scan_time=_timestamp(),
            scanned_files=scanned,
            queued_files=queued,
            ignored_files=ignored,
            in_progress_path="",
            last_error=last_error,
            message=message,
        )
        logger.info("Watcher scan complete: profiles=%s available=%s missing=%s scanned=%s ignored=%s queued=%s", len(profiles), valid_count, missing, scanned, ignored, queued)
        return {
            "ok": valid_count > 0,
            "message": message,
            "queued": queued,
            "ignored": ignored,
            "scanned": scanned,
            "missing": missing,
            "profiles": statuses,
            "errors": errors,
        }

    def _handle_candidate(self, candidate: Path, config: AppConfig, profile: WatchFolderProfile) -> bool:
        state = StateStore()
        try:
            job = state.get_latest_job_by_source_path(candidate)
            if job and not job.get("watch_folder_id"):
                # create_or_get_job backfills profile ownership for legacy jobs.
                job = state.create_or_get_job(candidate, profile.id, profile.path)
            elif not job:
                job = state.create_or_get_job(candidate, profile.id, profile.path)
            job_id = int(job["id"])
            status = job["status"]
            logger.info("Job %s found/created for %s in profile %s with status %s.", job_id, candidate.name, profile.id, status)

            if status == "detected":
                job = state.transition_job(job_id, "waiting_for_file_ready", "Waiting for file to become stable.")
                status = job["status"]
            elif status in {"queued", "processing", "processed", "uploading", "uploaded", "archived", "skipped"}:
                logger.info("Skipping existing job %s already in status %s.", job_id, status)
                return False
            elif status == "failed":
                logger.info("Skipping failed job %s until user requests retry.", job_id)
                return False

            if status != "waiting_for_file_ready":
                return False

            self._set_status(in_progress_path=str(candidate))
            result = wait_until_file_ready(candidate, config, stop_requested=self._stop_event.is_set)
            if result.ready:
                state.transition_job(job_id, "queued", "File is stable and ready.", {"size": result.size, "mtime": result.mtime})
                logger.info("File-ready success for job %s: %s", job_id, candidate)
                return True

            if result.reason == "stopped":
                logger.info("File-ready wait stopped for job %s.", job_id)
                return False
            category = "file_not_ready" if "timeout" in result.reason else "file_access_error"
            state.mark_failed(job_id, category, result.reason, retryable=True)
            logger.warning("File-ready failed for job %s: %s", job_id, result.reason)
            return False
        except InvalidTransitionError as exc:
            logger.warning("State transition failed for %s: %s", candidate, exc)
            return False
        except Exception as exc:
            logger.exception("Unexpected watcher error for %s: %s", candidate, redact(str(exc)))
            return False

    def _process_queue_run(self, limit: int | None = None) -> dict[str, Any]:
        if not self._processing_lock.acquire(blocking=False):
            return {"ok": False, "message": "Queue processing is already running.", "processed": 0, "failed": 0}
        processed = 0
        failed = 0
        try:
            config = load_config()
            if not config.process_while_valorant_running:
                logger.info("Game detection not implemented; skipping game-running guard.")
            state = StateStore()
            jobs = state.list_jobs(status="queued", limit=int(limit or config.max_jobs_per_process_run))
            self._set_status(processing_active=True, message=f"Processing {len(jobs)} queued job(s).")
            logger.info("Starting FFmpeg queue processing for %s job(s).", len(jobs))
            for job in jobs:
                if self._stop_event.is_set():
                    break
                if self._process_one_job(state, job, config):
                    processed += 1
                else:
                    failed += 1
            message = f"Processed {processed} job(s); {failed} failed."
            self._set_status(processing_active=False, in_progress_path="", message=message)
            logger.info(message)
            return {"ok": failed == 0, "message": message, "processed": processed, "failed": failed}
        finally:
            self._processing_lock.release()

    def _upload_processed_run(self, limit: int | None = None) -> dict[str, Any]:
        if not self._upload_lock.acquire(blocking=False):
            return {"ok": False, "message": "Upload is already running.", "uploaded": 0, "failed": 0}
        uploaded = 0
        failed = 0
        try:
            config = load_config()
            state = StateStore()
            jobs = state.list_jobs(status="processed", limit=int(limit or config.max_upload_jobs_per_run))
            logger.info("Starting Discord upload for %s processed job(s).", len(jobs))
            self._set_status(message=f"Uploading {len(jobs)} processed job(s).")
            for job in jobs:
                if self._stop_event.is_set():
                    break
                if self._upload_one_job(state, job, config):
                    uploaded += 1
                else:
                    failed += 1
            message = f"Uploaded {uploaded} job(s); {failed} failed."
            self._set_status(in_progress_path="", message=message)
            logger.info(message)
            return {"ok": failed == 0, "message": message, "uploaded": uploaded, "failed": failed}
        finally:
            self._upload_lock.release()

    def _archive_uploaded_run(self, limit: int | None = None) -> dict[str, Any]:
        if not self._archive_lock.acquire(blocking=False):
            return {"ok": False, "message": "Archive is already running.", "archived": 0, "failed": 0}
        archived = 0
        failed = 0
        try:
            config = load_config()
            state = StateStore()
            jobs = state.list_jobs(status="uploaded", limit=int(limit or config.max_archive_jobs_per_run))
            logger.info("Starting archive for %s uploaded job(s).", len(jobs))
            for job in jobs:
                if self._stop_event.is_set():
                    break
                if self._archive_one_job(state, job, config):
                    archived += 1
                else:
                    failed += 1
            message = f"Archived {archived} job(s); {failed} archive failure(s)."
            self._set_status(in_progress_path="", message=message)
            logger.info(message)
            return {"ok": failed == 0, "message": message, "archived": archived, "failed": failed}
        finally:
            self._archive_lock.release()

    def _run_end_to_end(self) -> dict[str, Any]:
        if not self._end_to_end_lock.acquire(blocking=False):
            return {"ok": False, "message": "End-to-end run is already running.", "errors": ["already running"]}
        try:
            process_result = self._process_queue_run()
            upload_result = self._upload_processed_run()
            archive_result = self._archive_uploaded_run()
            failed_count = int(process_result.get("failed", 0)) + int(upload_result.get("failed", 0)) + int(archive_result.get("failed", 0))
            errors = [
                result.get("message", "")
                for result in (process_result, upload_result, archive_result)
                if not result.get("ok", False)
            ]
            summary = {
                "ok": failed_count == 0,
                "message": "End-to-end run complete.",
                "processed_count": int(process_result.get("processed", 0)),
                "uploaded_count": int(upload_result.get("uploaded", 0)),
                "archived_count": int(archive_result.get("archived", 0)),
                "failed_count": failed_count,
                "skipped_count": 0,
                "errors": errors,
            }
            logger.info("End-to-end summary: %s", summary)
            return summary
        finally:
            self._end_to_end_lock.release()

    def _auto_loop(self) -> None:
        logger.info("Auto pipeline loop started.")
        while not self._auto_stop_event.is_set() and not self._stop_event.is_set():
            config = load_config()
            if self._pause_event.is_set():
                self._set_status(auto_pipeline_state="paused")
                self._auto_stop_event.wait(0.5)
                continue
            if self._auto_mode_enabled(config):
                if self._auto_cycle_lock.locked():
                    logger.warning("Skipping scheduled auto cycle because previous cycle is still running.")
                else:
                    self.run_auto_cycle()
            else:
                self._set_status(auto_pipeline_enabled=False, auto_pipeline_state="disabled")
            self._auto_stop_event.wait(float(config.auto_pipeline_interval_seconds))
        logger.info("Auto pipeline loop stopped.")

    def _auto_mode_enabled(self, config: AppConfig) -> bool:
        if self._auto_enabled_override is not None:
            return self._auto_enabled_override
        return bool(config.auto_process_enabled or config.auto_upload_enabled or config.auto_archive_enabled)

    def _process_one_job(self, state: StateStore, job: dict[str, Any], config: AppConfig) -> bool:
        job_id = int(job["id"])
        source_path = job["source_path"]
        try:
            state.transition_job(job_id, "processing", "Starting FFmpeg compression.")
            self._set_status(in_progress_path=source_path)
            result = self._compress_clip(source_path, None, config)
            if result.ok:
                state.set_compressed_output(job_id, result.output_path, result.output_size)
                state.transition_job(
                    job_id,
                    "processed",
                    "FFmpeg compression completed.",
                    {"attempts": result.attempts, "compressed_size": result.output_size},
                )
                logger.info("Job %s compressed successfully: %s", job_id, result.output_path)
                return True
            state.mark_failed(job_id, result.category or "ffmpeg_failed", result.message or "FFmpeg failed.", retryable=True)
            logger.warning("Job %s FFmpeg failed: %s", job_id, result.message)
            return False
        except InvalidTransitionError as exc:
            logger.warning("Invalid queue transition for job %s: %s", job_id, exc)
            return False
        except Exception as exc:
            logger.exception("Unexpected processing error for job %s: %s", job_id, redact(str(exc)))
            try:
                state.mark_failed(job_id, "ffmpeg_worker_error", redact(str(exc)), retryable=True)
            except Exception:
                logger.exception("Could not mark job %s failed after processing error.", job_id)
            return False

    def _upload_one_job(self, state: StateStore, job: dict[str, Any], config: AppConfig) -> bool:
        job_id = int(job["id"])
        try:
            state.transition_job(job_id, "uploading", "Starting Discord upload.")
            uploading_job = state.get_job(job_id) or job
            self._set_status(in_progress_path=str(uploading_job.get("compressed_path") or uploading_job.get("source_path") or ""))
            result = self._upload_processed_job(uploading_job, config)
            if result.response_code is not None:
                state.set_discord_result(job_id, result.response_code, result.message_id)
            if result.ok:
                state.transition_job(
                    job_id,
                    "uploaded",
                    "Discord upload completed.",
                    {"attempts": result.attempts, "message_id": result.message_id},
                )
                logger.info("Job %s uploaded to Discord. message_id=%s", job_id, result.message_id or "")
                return True
            state.mark_failed(job_id, result.category, result.message, retryable=result.retryable)
            logger.warning("Job %s Discord upload failed: %s", job_id, result.category)
            return False
        except InvalidTransitionError as exc:
            logger.warning("Invalid upload transition for job %s: %s", job_id, exc)
            return False
        except Exception as exc:
            logger.exception("Unexpected upload error for job %s: %s", job_id, redact(str(exc)))
            try:
                state.mark_failed(job_id, "discord_worker_error", redact(str(exc)), retryable=True)
            except Exception:
                logger.exception("Could not mark job %s failed after upload error.", job_id)
            return False

    def _archive_one_job(self, state: StateStore, job: dict[str, Any], config: AppConfig) -> bool:
        job_id = int(job["id"])
        result = archive_uploaded_job(job, config)
        if result.ok:
            state.set_archive_result(job_id, result.archive_path)
            state.transition_job(job_id, "archived", "Original archived.", {"archive_path": result.archive_path})
            cleanup_result = _cleanup_after_archive(job, config)
            if cleanup_result.ok:
                state.set_cleanup_result(job_id, "cleaned" if config.cleanup_compressed_after_archive else "kept")
            else:
                state.set_cleanup_result(job_id, "failed", cleanup_result.message)
                logger.warning("Compressed cleanup failed for job %s: %s", job_id, cleanup_result.message)
            return True
        state.set_archive_error(job_id, result.category, result.message)
        logger.warning("Archive failed for job %s but status remains uploaded: %s", job_id, result.category)
        return False

    def _record_auto_failures(self, failed: int, config: AppConfig, errors: list[str]) -> None:
        status = self.get_status()
        count = int(status.get("repeated_failure_count", 0)) + failed
        updates: dict[str, Any] = {"repeated_failure_count": count}
        if config.pause_on_repeated_failures and count >= int(config.repeated_failure_limit):
            self._auto_enabled_override = False
            updates["auto_pipeline_enabled"] = False
            updates["auto_pipeline_state"] = "auto_paused_due_to_failures"
            updates["last_error"] = "; ".join(errors[-3:]) or "Repeated auto pipeline failures."
            logger.warning("Auto pipeline paused due to repeated failures: %s", count)
        self._set_status(**updates)

    def _set_status(self, **updates: Any) -> None:
        with self._lock:
            for key, value in updates.items():
                if hasattr(self._status, key):
                    setattr(self._status, key, value)


def _iter_files(watch_folder: Path, archive_folder: Path) -> list[Path]:
    """Return files while pruning the app-owned archive subtree.

    `ClipDis Uploaded` lives inside the watch root in v1.1.0. It must be
    excluded before discovery so archived clips can never become jobs again.
    """
    files: list[Path] = []
    archive_resolved = archive_folder.resolve(strict=False)
    for root, dirs, names in os.walk(watch_folder):
        root_path = Path(root)
        kept_dirs: list[str] = []
        for dirname in dirs:
            child = (root_path / dirname).resolve(strict=False)
            try:
                child.relative_to(archive_resolved)
                logger.debug("Pruning archive subtree from watcher scan: %s", child)
                continue
            except ValueError:
                kept_dirs.append(dirname)
        dirs[:] = kept_dirs
        for name in names:
            files.append(root_path / name)
    return files


def _profile_status(profile: WatchFolderProfile, exists: bool | None = None) -> dict[str, Any]:
    available = Path(profile.path).is_dir() if exists is None else bool(exists)
    return {
        "id": profile.id,
        "name": profile.name,
        "path": profile.path,
        "uploadedPath": str(profile_uploaded_folder(profile)),
        "exists": available,
        "showValorantStats": bool(profile.show_valorant_stats),
        "captionEnabled": bool(profile.caption_enabled),
    }


def _profile_statuses(config: AppConfig) -> list[dict[str, Any]]:
    return [_profile_status(profile) for profile in config.watch_folders]


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cleanup_after_archive(job: dict[str, Any], config: AppConfig):
    if not config.cleanup_compressed_after_archive:
        return type("CleanupResult", (), {"ok": True, "message": "Compressed output kept."})()
    compressed_path = job.get("compressed_path")
    if not compressed_path:
        return type("CleanupResult", (), {"ok": True, "message": "No compressed output recorded."})()
    return cleanup_compressed_file(str(compressed_path))
