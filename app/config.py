from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


APP_NAME = "ValorantClipUploader"
CONFIG_FILE_NAME = "config.json"


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"


@dataclass
class AppConfig:
    watch_folder: str = ""
    uploaded_folder: str = ""
    ffmpeg_source_mode: str = "bundled"
    ffmpeg_path: str = ""
    riot_username: str = ""
    riot_tagline: str = ""
    use_henrik_stats: bool = False
    valorant_region: str = "ap"
    start_with_windows: bool = False
    max_upload_size_mb: int = 8
    crf: int = 28
    poll_interval_seconds: int = 5
    supported_extensions: list[str] | None = None
    file_stability_checks: int = 3
    file_stability_interval_seconds: float = 2.0
    file_ready_timeout_seconds: float = 120.0
    watcher_poll_interval_seconds: float = 3.0
    ignore_prefixes: list[str] | None = None
    ignore_suffixes: list[str] | None = None
    target_resolution: str = "720p"
    compression_mode: str = "balanced"
    process_while_valorant_running: bool = False
    ffmpeg_priority: str = "idle"
    ffmpeg_threads: str = "auto"
    max_ffmpeg_attempts: int = 3
    max_jobs_per_process_run: int = 3
    discord_timeout_seconds: float = 30.0
    discord_max_retries: int = 3
    discord_retry_base_seconds: float = 2.0
    discord_retry_max_seconds: float = 60.0
    discord_wait_for_response: bool = True
    max_upload_jobs_per_run: int = 3
    cleanup_compressed_after_upload: bool = False
    cleanup_compressed_after_archive: bool = True
    keep_failed_compressed_files: bool = True
    max_archive_jobs_per_run: int = 3
    auto_process_enabled: bool = True
    auto_upload_enabled: bool = True
    auto_archive_enabled: bool = True
    auto_pipeline_interval_seconds: float = 5.0
    max_auto_jobs_per_cycle: int = 1
    auto_retry_failed_jobs: bool = False
    pause_on_repeated_failures: bool = True
    repeated_failure_limit: int = 3
    thumbnail_cache_dir: str = ""
    thumbnail_width: int = 320
    generate_thumbnails_enabled: bool = True


def app_data_dir() -> Path:
    base = os.getenv("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME}"


def config_path() -> Path:
    return app_data_dir() / CONFIG_FILE_NAME


def logs_dir() -> Path:
    return app_data_dir() / "logs"


def work_dir() -> Path:
    # FFmpeg is an external native process. In some Python runtimes, APPDATA and
    # LOCALAPPDATA can be filesystem-virtualized in a way Python can see but
    # child processes cannot. The OS temp directory is visible to both.
    return Path(tempfile.gettempdir()) / APP_NAME / "work"


def state_db_path() -> Path:
    return app_data_dir() / "state.db"


def thumbnails_dir(config: AppConfig | None = None) -> Path:
    if config and config.thumbnail_cache_dir:
        return Path(config.thumbnail_cache_dir)
    return app_data_dir() / "thumbnails"


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    if not path.exists():
        cfg = AppConfig()
        save_config(cfg, path)
        return cfg

    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        cfg = AppConfig(**_known_config_values(raw))
        if cfg.ffmpeg_source_mode != "bundled":
            cfg.ffmpeg_source_mode = "bundled"
            cfg.ffmpeg_path = ""
            save_config(cfg, path)
        return cfg
    except (json.JSONDecodeError, TypeError, ValueError):
        backup_path = path.with_suffix(".invalid.json")
        path.replace(backup_path)
        cfg = AppConfig()
        save_config(cfg, path)
        return cfg


def save_config(config: AppConfig, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(asdict(config), handle, indent=2, sort_keys=True)
        handle.write("\n")


def validate_config(config: AppConfig) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _validate_directory("watch_folder", config.watch_folder, issues)
    _validate_directory("uploaded_folder", config.uploaded_folder, issues)

    if config.ffmpeg_source_mode != "bundled":
        issues.append(ValidationIssue("ffmpeg_source_mode", "FFmpeg source must be bundled."))
    try:
        from app.ffmpeg_runner import get_bundled_ffmpeg_path, get_bundled_ffprobe_path

        if not get_bundled_ffmpeg_path().is_file():
            issues.append(ValidationIssue("ffmpeg", "Bundled FFmpeg is missing."))
        if not get_bundled_ffprobe_path().is_file():
            issues.append(ValidationIssue("ffprobe", "Bundled FFprobe is missing."))
    except Exception as exc:
        issues.append(ValidationIssue("ffmpeg", f"Could not check bundled FFmpeg: {exc}"))

    if config.max_upload_size_mb < 1:
        issues.append(ValidationIssue("max_upload_size_mb", "Max upload size must be at least 1 MB."))
    if not 16 <= config.crf <= 40:
        issues.append(ValidationIssue("crf", "CRF should be between 16 and 40."))
    if config.poll_interval_seconds < 1:
        issues.append(ValidationIssue("poll_interval_seconds", "Polling interval must be at least 1 second."))
    if config.file_stability_checks < 1:
        issues.append(ValidationIssue("file_stability_checks", "File stability checks must be at least 1."))
    if config.file_stability_interval_seconds < 0:
        issues.append(ValidationIssue("file_stability_interval_seconds", "File stability interval cannot be negative."))
    if config.file_ready_timeout_seconds < 1:
        issues.append(ValidationIssue("file_ready_timeout_seconds", "File-ready timeout must be at least 1 second."))
    if config.watcher_poll_interval_seconds < 1:
        issues.append(ValidationIssue("watcher_poll_interval_seconds", "Watcher poll interval must be at least 1 second."))
    if config.target_resolution not in {"720p", "1080p"}:
        issues.append(ValidationIssue("target_resolution", "Target resolution must be 720p or 1080p."))
    if config.valorant_region not in {"ap", "eu", "na", "kr", "latam", "br"}:
        issues.append(ValidationIssue("valorant_region", "Valorant region must be ap, eu, na, kr, latam, or br."))
    if config.compression_mode not in {"balanced", "smallest", "fast"}:
        issues.append(ValidationIssue("compression_mode", "Compression mode must be balanced, smallest, or fast."))
    if config.ffmpeg_priority not in {"idle", "low", "normal"}:
        issues.append(ValidationIssue("ffmpeg_priority", "FFmpeg priority must be idle, low, or normal."))
    if config.ffmpeg_threads not in {"1", "2", "auto"}:
        issues.append(ValidationIssue("ffmpeg_threads", "FFmpeg threads must be 1, 2, or auto."))
    if config.max_ffmpeg_attempts < 1:
        issues.append(ValidationIssue("max_ffmpeg_attempts", "Max FFmpeg attempts must be at least 1."))
    if config.max_jobs_per_process_run < 1:
        issues.append(ValidationIssue("max_jobs_per_process_run", "Max jobs per process run must be at least 1."))
    if config.discord_timeout_seconds < 1:
        issues.append(ValidationIssue("discord_timeout_seconds", "Discord timeout must be at least 1 second."))
    if config.discord_max_retries < 0:
        issues.append(ValidationIssue("discord_max_retries", "Discord max retries cannot be negative."))
    if config.discord_retry_base_seconds < 0:
        issues.append(ValidationIssue("discord_retry_base_seconds", "Discord retry base cannot be negative."))
    if config.discord_retry_max_seconds < 0:
        issues.append(ValidationIssue("discord_retry_max_seconds", "Discord retry max cannot be negative."))
    if config.max_upload_jobs_per_run < 1:
        issues.append(ValidationIssue("max_upload_jobs_per_run", "Max upload jobs per run must be at least 1."))
    if config.max_archive_jobs_per_run < 1:
        issues.append(ValidationIssue("max_archive_jobs_per_run", "Max archive jobs per run must be at least 1."))
    if config.auto_pipeline_interval_seconds < 1:
        issues.append(ValidationIssue("auto_pipeline_interval_seconds", "Auto pipeline interval must be at least 1 second."))
    if config.max_auto_jobs_per_cycle < 1:
        issues.append(ValidationIssue("max_auto_jobs_per_cycle", "Max auto jobs per cycle must be at least 1."))
    if config.repeated_failure_limit < 1:
        issues.append(ValidationIssue("repeated_failure_limit", "Repeated failure limit must be at least 1."))
    if config.thumbnail_width < 64:
        issues.append(ValidationIssue("thumbnail_width", "Thumbnail width must be at least 64 pixels."))
    return issues


def _validate_directory(field: str, value: str, issues: list[ValidationIssue]) -> None:
    if not value:
        issues.append(ValidationIssue(field, f"{field} is not configured."))
        return
    if not Path(value).is_dir():
        issues.append(ValidationIssue(field, f"{field} does not exist or is not a folder."))


def _known_config_values(raw: dict[str, Any]) -> dict[str, Any]:
    valid_fields = set(AppConfig.__dataclass_fields__)
    return {key: value for key, value in raw.items() if key in valid_fields}
