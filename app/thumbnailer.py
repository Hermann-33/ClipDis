from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import AppConfig, load_config, thumbnails_dir, work_dir
from app.ffmpeg_runner import resolve_ffmpeg_path
from app.secrets import redact


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThumbnailResult:
    ok: bool
    path: str = ""
    message: str = ""
    category: str = ""
    cached: bool = False


def thumbnail_cache_dir(config: AppConfig | None = None) -> Path:
    cfg = config or load_config()
    return thumbnails_dir(cfg)


def thumbnail_path_for_job(job: dict[str, Any], config: AppConfig | None = None) -> Path:
    cfg = config or load_config()
    cache_dir = thumbnail_cache_dir(cfg)
    identity = str(job.get("fingerprint") or "") or "|".join(
        [
            str(job.get("source_path") or ""),
            str(job.get("original_size") or ""),
            str(job.get("original_mtime") or ""),
        ]
    )
    digest = hashlib.sha256(identity.encode("utf-8", errors="ignore")).hexdigest()[:32]
    return cache_dir / f"{digest}.jpg"


def cached_thumbnail_for_job(job: dict[str, Any], config: AppConfig | None = None) -> ThumbnailResult:
    cfg = config or load_config()
    path = thumbnail_path_for_job(job, cfg)
    source = Path(str(job.get("source_path") or ""))
    if not path.is_file() or path.stat().st_size <= 0:
        return ThumbnailResult(False, message="Thumbnail is not cached.", category="thumbnail_missing")
    try:
        source_mtime = float(job.get("original_mtime") or source.stat().st_mtime)
    except OSError:
        source_mtime = None
    if source_mtime is not None and path.stat().st_mtime + 0.001 < source_mtime:
        return ThumbnailResult(False, message="Thumbnail cache is stale.", category="thumbnail_stale")
    return ThumbnailResult(True, str(path), "Thumbnail cached.", cached=True)


def ensure_thumbnail(job: dict[str, Any], config: AppConfig | None = None) -> ThumbnailResult:
    cfg = config or load_config()
    if not cfg.generate_thumbnails_enabled:
        return ThumbnailResult(False, message="Thumbnail generation is disabled.", category="thumbnail_disabled")

    cached = cached_thumbnail_for_job(job, cfg)
    if cached.ok:
        return cached

    source = Path(str(job.get("source_path") or ""))
    if not source.is_file():
        return ThumbnailResult(False, message="Clip file is missing.", category="thumbnail_source_missing")

    cache_dir = thumbnail_cache_dir(cfg)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create thumbnail cache %s: %s", cache_dir, redact(str(exc)))
        return ThumbnailResult(False, message="Thumbnail cache is not writable.", category="thumbnail_cache_error")

    final_path = thumbnail_path_for_job(job, cfg)
    temp_dir = _prepare_temp_thumbnail_dir()
    if temp_dir is None:
        return ThumbnailResult(False, message="Thumbnail work folder is not writable.", category="thumbnail_workdir_error")
    temp_path = temp_dir / f"thumb_{uuid.uuid4().hex}.jpg"

    ffmpeg = resolve_ffmpeg_path(cfg)
    commands = [
        _thumbnail_command(ffmpeg, source, temp_path, int(cfg.thumbnail_width), seek=True),
        _thumbnail_command(ffmpeg, source, temp_path, int(cfg.thumbnail_width), seek=False),
    ]
    last_message = ""
    for index, command in enumerate(commands, start=1):
        logger.debug("Starting thumbnail attempt %s for job %s.", index, job.get("id"))
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=45,
                startupinfo=_startupinfo(),
                creationflags=_creationflags(),
            )
        except FileNotFoundError:
            return ThumbnailResult(False, message="Bundled FFmpeg is missing.", category="thumbnail_ffmpeg_missing")
        except subprocess.TimeoutExpired:
            cleanup_thumbnail_temp(temp_path)
            last_message = "Thumbnail generation timed out."
            continue
        except OSError as exc:
            cleanup_thumbnail_temp(temp_path)
            last_message = redact(str(exc))
            continue

        if result.returncode == 0 and temp_path.is_file() and temp_path.stat().st_size > 0:
            try:
                shutil.move(str(temp_path), str(final_path))
                logger.info("Thumbnail generated for job %s: %s", job.get("id"), final_path)
                return ThumbnailResult(True, str(final_path), "Thumbnail generated.", cached=False)
            except OSError as exc:
                cleanup_thumbnail_temp(temp_path)
                logger.warning("Could not move thumbnail to cache %s: %s", final_path, redact(str(exc)))
                return ThumbnailResult(False, message="Could not save thumbnail.", category="thumbnail_cache_error")

        cleanup_thumbnail_temp(temp_path)
        last_message = _stderr_summary(result.stderr) or f"FFmpeg thumbnail attempt returned {result.returncode}."

    logger.debug("Thumbnail generation failed for job %s: %s", job.get("id"), last_message)
    return ThumbnailResult(False, message=_one_line(last_message) or "Thumbnail generation failed.", category="thumbnail_failed")


def cleanup_thumbnail_temp(path: str | Path) -> None:
    try:
        candidate = Path(path)
        if candidate.exists() and _is_inside(candidate, work_dir()):
            candidate.unlink()
    except OSError as exc:
        logger.debug("Could not clean thumbnail temp file %s: %s", path, redact(str(exc)))


def _thumbnail_command(ffmpeg: str, source: Path, output_path: Path, width: int, seek: bool) -> list[str]:
    command = [ffmpeg, "-y"]
    if seek:
        command.extend(["-ss", "00:00:01"])
    command.extend(
        [
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            f"scale={max(64, width)}:-1",
            str(output_path),
        ]
    )
    return command


def _prepare_temp_thumbnail_dir() -> Path | None:
    try:
        folder = work_dir() / "thumbnail_work"
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write_test_{uuid.uuid4().hex}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return folder
    except OSError as exc:
        logger.warning("Thumbnail temp folder is not writable: %s", redact(str(exc)))
        return None


def _startupinfo() -> subprocess.STARTUPINFO | None:
    import os

    if os.name != "nt":
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo


def _creationflags() -> int:
    import os

    if os.name != "nt":
        return 0
    return 0x08000000 | 0x00000040


def _stderr_summary(stderr: str | None, limit: int = 500) -> str:
    if not stderr:
        return ""
    text = redact(stderr.strip())
    if len(text) <= limit:
        return text
    return text[-limit:]


def _one_line(value: str) -> str:
    return " ".join(redact(value).split())


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False
