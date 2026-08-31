from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


APP_NAME = "ValorantClipUploader"
CONFIG_FILE_NAME = "config.json"
CONFIG_VERSION = 2
UPLOADED_DIR_NAME = "ClipDis Uploaded"
MAX_PROFILE_CAPTION_CHARS = 1800


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"


@dataclass
class WatchFolderProfile:
    id: str
    name: str
    path: str
    show_valorant_stats: bool = False
    caption_enabled: bool = False
    caption_text: str = ""

    @property
    def uploaded_path(self) -> str:
        return str(profile_uploaded_folder(self))


@dataclass
class AppConfig:
    config_version: int = CONFIG_VERSION
    watch_folders: list[WatchFolderProfile] = field(default_factory=list)

    # v1 compatibility mirrors. New code must use watch_folders instead.
    # They remain during the v1.1 migration so old call sites can be converted
    # incrementally without resetting existing installations.
    watch_folder: str = ""
    uploaded_folder: str = ""
    use_henrik_stats: bool = False

    ffmpeg_source_mode: str = "bundled"
    ffmpeg_path: str = ""
    riot_username: str = ""
    riot_tagline: str = ""
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


def new_watch_folder_profile(
    path: str | Path,
    *,
    name: str | None = None,
    show_valorant_stats: bool = False,
    caption_enabled: bool = False,
    caption_text: str = "",
    profile_id: str | None = None,
) -> WatchFolderProfile:
    normalized = normalize_watch_path(path)
    default_name = Path(normalized).name or normalized
    return WatchFolderProfile(
        id=profile_id or str(uuid.uuid4()),
        name=(name or default_name or "Watch Folder").strip(),
        path=normalized,
        show_valorant_stats=bool(show_valorant_stats),
        caption_enabled=bool(caption_enabled),
        caption_text=_normalize_caption(caption_text),
    )


def normalize_watch_path(path: str | Path) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    return str(Path(value).expanduser().resolve(strict=False))


def profile_uploaded_folder(profile: WatchFolderProfile | dict[str, Any]) -> Path:
    raw_path = profile.path if isinstance(profile, WatchFolderProfile) else str(profile.get("path", ""))
    return Path(raw_path) / UPLOADED_DIR_NAME


def get_watch_folder_profile(config: AppConfig, profile_id: str) -> WatchFolderProfile | None:
    target = str(profile_id or "").strip()
    for profile in config.watch_folders:
        if profile.id == target:
            return profile
    return None


def path_is_within(path: str | Path, parent: str | Path) -> bool:
    candidate = Path(path).expanduser().resolve(strict=False)
    root = Path(parent).expanduser().resolve(strict=False)
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def path_is_profile_archive(path: str | Path, profile: WatchFolderProfile) -> bool:
    candidate = Path(path).expanduser().resolve(strict=False)
    expected = profile_uploaded_folder(profile).expanduser().resolve(strict=False)
    return os.path.normcase(str(candidate)) == os.path.normcase(str(expected))


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    if not path.exists():
        cfg = AppConfig()
        save_config(cfg, path)
        return cfg

    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise TypeError("Configuration root must be an object.")

        migrated = _needs_v2_migration(raw)
        if migrated:
            _backup_v1_config_once(path)
            raw = _migrate_v1_config(raw)

        cfg = AppConfig(**_known_config_values(raw))
        cfg.config_version = CONFIG_VERSION
        cfg.watch_folders = [_coerce_profile(profile) for profile in cfg.watch_folders]
        _sync_legacy_mirrors(cfg)

        changed = migrated
        if cfg.ffmpeg_source_mode != "bundled" or cfg.ffmpeg_path:
            cfg.ffmpeg_source_mode = "bundled"
            cfg.ffmpeg_path = ""
            changed = True
        if changed:
            save_config(cfg, path)
        return cfg
    except (json.JSONDecodeError, TypeError, ValueError, KeyError):
        backup_path = path.with_suffix(".invalid.json")
        if backup_path.exists():
            backup_path.unlink()
        path.replace(backup_path)
        cfg = AppConfig()
        save_config(cfg, path)
        return cfg


def save_config(config: AppConfig, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config.config_version = CONFIG_VERSION
    config.watch_folders = [_coerce_profile(profile) for profile in config.watch_folders]
    _sync_legacy_mirrors(config)
    payload = asdict(config)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def validate_config(config: AppConfig) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(validate_watch_folders(config.watch_folders))

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


def validate_watch_folders(profiles: list[WatchFolderProfile]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not profiles:
        issues.append(ValidationIssue("watch_folders", "At least one watch folder must be configured."))
        return issues

    normalized: list[tuple[WatchFolderProfile, str]] = []
    seen_ids: set[str] = set()
    for index, profile in enumerate(profiles):
        field_name = f"watch_folders[{index}]"
        if not profile.id or profile.id in seen_ids:
            issues.append(ValidationIssue(field_name, "Each watch folder needs a unique stable ID."))
        seen_ids.add(profile.id)
        if not profile.name.strip():
            issues.append(ValidationIssue(field_name, "Watch folder name cannot be empty."))
        if not profile.path:
            issues.append(ValidationIssue(field_name, "Watch folder path is not configured."))
            continue
        normalized_path = normalize_watch_path(profile.path)
        normalized.append((profile, normalized_path))
        if not Path(normalized_path).is_dir():
            issues.append(
                ValidationIssue(field_name, f'Watch folder "{profile.name}" does not exist or is not a folder.', "warning")
            )
        if len(_normalize_caption(profile.caption_text)) > MAX_PROFILE_CAPTION_CHARS:
            issues.append(
                ValidationIssue(field_name, f"Caption must be {MAX_PROFILE_CAPTION_CHARS} characters or fewer.")
            )

    for left_index, (left, left_path) in enumerate(normalized):
        for right, right_path in normalized[left_index + 1 :]:
            left_case = os.path.normcase(left_path)
            right_case = os.path.normcase(right_path)
            if left_case == right_case:
                issues.append(
                    ValidationIssue(
                        "watch_folders",
                        f'Watch folders "{left.name}" and "{right.name}" point to the same directory.',
                    )
                )
                continue
            if path_is_within(left_path, right_path) or path_is_within(right_path, left_path):
                issues.append(
                    ValidationIssue(
                        "watch_folders",
                        f'Watch folders "{left.name}" and "{right.name}" overlap. Parent/child watch folders are not allowed.',
                    )
                )
    return issues


def _needs_v2_migration(raw: dict[str, Any]) -> bool:
    try:
        version = int(raw.get("config_version", 1))
    except (TypeError, ValueError):
        version = 1
    return version < CONFIG_VERSION or (not raw.get("watch_folders") and bool(str(raw.get("watch_folder", "")).strip()))


def _migrate_v1_config(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(raw)
    profiles: list[dict[str, Any]] = []
    legacy_watch = str(raw.get("watch_folder", "") or "").strip()
    if legacy_watch:
        profile = new_watch_folder_profile(
            legacy_watch,
            show_valorant_stats=bool(raw.get("use_henrik_stats", False)),
        )
        profiles.append(asdict(profile))
    migrated["config_version"] = CONFIG_VERSION
    migrated["watch_folders"] = profiles
    return migrated


def _backup_v1_config_once(path: Path) -> None:
    backup = path.with_name("config.v1.backup.json")
    if not backup.exists() and path.exists():
        shutil.copy2(path, backup)


def _sync_legacy_mirrors(config: AppConfig) -> None:
    if config.watch_folders:
        first = config.watch_folders[0]
        config.watch_folder = first.path
        config.uploaded_folder = str(profile_uploaded_folder(first))
        config.use_henrik_stats = bool(first.show_valorant_stats)
    else:
        config.watch_folder = ""
        config.uploaded_folder = ""
        config.use_henrik_stats = False


def _coerce_profile(value: WatchFolderProfile | dict[str, Any]) -> WatchFolderProfile:
    if isinstance(value, WatchFolderProfile):
        value.path = normalize_watch_path(value.path)
        value.caption_text = _normalize_caption(value.caption_text)
        return value
    if not isinstance(value, dict):
        raise TypeError("Watch-folder profile must be an object.")
    return new_watch_folder_profile(
        value.get("path", ""),
        name=str(value.get("name", "") or "") or None,
        show_valorant_stats=bool(value.get("show_valorant_stats", False)),
        caption_enabled=bool(value.get("caption_enabled", False)),
        caption_text=str(value.get("caption_text", "") or ""),
        profile_id=str(value.get("id", "") or "") or None,
    )


def _normalize_caption(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:MAX_PROFILE_CAPTION_CHARS]


def _known_config_values(raw: dict[str, Any]) -> dict[str, Any]:
    valid_fields = set(AppConfig.__dataclass_fields__)
    values = {key: value for key, value in raw.items() if key in valid_fields}
    profiles = values.get("watch_folders", [])
    if profiles is None:
        profiles = []
    values["watch_folders"] = [_coerce_profile(profile) for profile in profiles]
    return values
