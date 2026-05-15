from __future__ import annotations

import logging
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import AppConfig, work_dir


logger = logging.getLogger(__name__)

DEFAULT_SUPPORTED_EXTENSIONS = [".mp4"]
DEFAULT_IGNORE_PREFIXES = ["compressed_", "cropped_", "temp_", "tmp_"]
DEFAULT_IGNORE_SUFFIXES = [".part", ".tmp", ".download"]


@dataclass(frozen=True)
class FileReadyResult:
    ready: bool
    reason: str
    path: str
    size: int | None = None
    mtime: float | None = None


def is_supported_clip(path: str | Path, config: AppConfig | None = None) -> bool:
    config = config or AppConfig()
    suffix = Path(path).suffix.lower()
    return suffix in normalized_extensions(config)


def should_ignore_path(path: str | Path, watch_folder: str | Path, config: AppConfig | None = None) -> tuple[bool, str]:
    config = config or AppConfig()
    candidate = Path(path)
    name_lower = candidate.name.lower()

    if _is_in_work_dir(candidate):
        return True, "inside app work directory"
    if not _is_relative_to(candidate, Path(watch_folder)):
        return True, "outside watch folder"
    for prefix in normalized_prefixes(config):
        if name_lower.startswith(prefix):
            return True, f"ignored prefix {prefix}"
    for suffix in normalized_suffixes(config):
        if name_lower.endswith(suffix):
            return True, f"ignored suffix {suffix}"
    if not is_supported_clip(candidate, config):
        return True, "unsupported extension"
    if _is_hidden_or_system(candidate):
        return True, "hidden or system file"
    return False, ""


def wait_until_file_ready(
    path: str | Path,
    config: AppConfig,
    stop_requested: callable | None = None,
) -> FileReadyResult:
    candidate = Path(path)
    deadline = time.monotonic() + float(config.file_ready_timeout_seconds)
    stable_samples = 0
    previous: tuple[int, float] | None = None

    while time.monotonic() <= deadline:
        if stop_requested and stop_requested():
            return FileReadyResult(False, "stopped", str(candidate))

        snapshot = _snapshot(candidate)
        if snapshot is None:
            return FileReadyResult(False, "file disappeared or is not a file", str(candidate))
        size, mtime = snapshot
        if size <= 0:
            stable_samples = 0
            previous = snapshot
        elif not _can_open_for_read(candidate):
            stable_samples = 0
            previous = snapshot
        elif previous == snapshot:
            stable_samples += 1
            if stable_samples >= int(config.file_stability_checks):
                return FileReadyResult(True, "ready", str(candidate), size=size, mtime=mtime)
        else:
            stable_samples = 1
            previous = snapshot

        interval = float(config.file_stability_interval_seconds)
        if interval <= 0:
            continue
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    snapshot = _snapshot(candidate)
    size = snapshot[0] if snapshot else None
    mtime = snapshot[1] if snapshot else None
    return FileReadyResult(False, "file-ready timeout", str(candidate), size=size, mtime=mtime)


def normalized_extensions(config: AppConfig) -> set[str]:
    values = config.supported_extensions or DEFAULT_SUPPORTED_EXTENSIONS
    return {_normalize_extension(value) for value in values if value}


def normalized_prefixes(config: AppConfig) -> list[str]:
    return [value.lower() for value in (config.ignore_prefixes or DEFAULT_IGNORE_PREFIXES)]


def normalized_suffixes(config: AppConfig) -> list[str]:
    return [value.lower() for value in (config.ignore_suffixes or DEFAULT_IGNORE_SUFFIXES)]


def _normalize_extension(value: str) -> str:
    value = value.strip().lower()
    return value if value.startswith(".") else f".{value}"


def _snapshot(path: Path) -> tuple[int, float] | None:
    try:
        if not path.exists() or not path.is_file():
            return None
        stat = path.stat()
        return int(stat.st_size), float(stat.st_mtime)
    except OSError:
        return None


def _can_open_for_read(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            handle.read(1)
        return True
    except OSError:
        return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _is_in_work_dir(path: Path) -> bool:
    return _is_relative_to(path, work_dir())


def _is_hidden_or_system(path: Path) -> bool:
    if os.name != "nt":
        return path.name.startswith(".")
    try:
        attrs = path.stat().st_file_attributes
    except (AttributeError, OSError):
        return path.name.startswith(".")
    hidden = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2)
    system = getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0x4)
    return bool(attrs & (hidden | system))
