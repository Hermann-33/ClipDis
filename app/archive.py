from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.secrets import redact


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArchiveResult:
    ok: bool
    archive_path: str = ""
    category: str = ""
    message: str = ""


def ensure_archive_folder(path: str | Path) -> Path:
    if not path:
        raise FileNotFoundError("Archive folder is not configured.")
    archive_folder = Path(path)
    archive_folder.mkdir(parents=True, exist_ok=True)
    if not archive_folder.is_dir():
        raise NotADirectoryError(f"Archive path is not a folder: {archive_folder}")
    return archive_folder


def build_archive_destination(source_path: str | Path, archive_folder: str | Path) -> Path:
    source = Path(source_path)
    folder = ensure_archive_folder(archive_folder)
    return resolve_filename_collision(folder / source.name)


def resolve_filename_collision(destination_path: str | Path) -> Path:
    destination = Path(destination_path)
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    counter = 1
    while True:
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def archive_original(source_path: str | Path, archive_folder: str | Path) -> ArchiveResult:
    try:
        source = Path(source_path)
        if not source.is_file():
            return ArchiveResult(False, category="original_missing_after_upload", message="Original clip is missing after upload.")
        destination = build_archive_destination(source, archive_folder)
        logger.info("Archiving original clip: %s -> %s", source, destination)
        moved_path = shutil.move(str(source), str(destination))
        return ArchiveResult(True, archive_path=str(moved_path), message="Original archived.")
    except Exception as exc:
        category = classify_archive_error(exc)
        logger.warning("Archive failed for %s: %s", source_path, redact(str(exc)))
        return ArchiveResult(False, category=category, message=redact(str(exc)))


def cleanup_compressed_file(path: str | Path) -> ArchiveResult:
    try:
        candidate = Path(path)
        if not candidate:
            return ArchiveResult(True, message="No compressed file to clean.")
        if not candidate.exists():
            return ArchiveResult(True, message="Compressed file already absent.")
        logger.info("Cleaning compressed output: %s", candidate)
        candidate.unlink()
        return ArchiveResult(True, message="Compressed output cleaned.")
    except Exception as exc:
        return ArchiveResult(False, category="cleanup_compressed_error", message=redact(str(exc)))


def archive_uploaded_job(job: dict[str, Any], config: AppConfig) -> ArchiveResult:
    if job.get("status") != "uploaded":
        return ArchiveResult(False, category="archive_invalid_state", message="Only uploaded jobs can be archived.")
    return archive_original(str(job.get("source_path") or ""), config.uploaded_folder)


def classify_archive_error(exception: Exception) -> str:
    if isinstance(exception, FileNotFoundError):
        return "archive_folder_missing"
    if isinstance(exception, PermissionError):
        return "archive_permission_error"
    if isinstance(exception, FileExistsError):
        return "archive_destination_collision_error"
    return "archive_move_error"
