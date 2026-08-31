from __future__ import annotations

import os
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from app.config import (
    AppConfig,
    MAX_PROFILE_CAPTION_CHARS,
    WatchFolderProfile,
    get_watch_folder_profile,
    load_config,
    new_watch_folder_profile,
    normalize_watch_path,
    path_is_profile_archive,
    profile_uploaded_folder,
    save_config,
    validate_watch_folders,
)
from app.state import ACTIVE_STATES, StateStore


class WatchFolderService:
    """Profile CRUD and archive maintenance behind profile-ID scoped APIs.

    The GUI should call this service with stable profile IDs. Destructive methods
    never accept arbitrary filesystem paths from QML.
    """

    def __init__(self, config_path: Path | None = None, state_store: StateStore | None = None) -> None:
        self.config_path = config_path
        self.state = state_store or StateStore()

    def get_profiles(self) -> dict[str, Any]:
        config = self._load()
        return {
            "ok": True,
            "message": f"Loaded {len(config.watch_folders)} watch folder(s).",
            "data": [profile_payload(profile) for profile in config.watch_folders],
        }

    def add_profile(
        self,
        path: str,
        name: str = "",
        show_valorant_stats: bool = False,
        caption_enabled: bool = False,
        caption_text: str = "",
    ) -> dict[str, Any]:
        config = self._load()
        normalized = normalize_watch_path(path)
        if not normalized or not Path(normalized).is_dir():
            return _error("Selected watch folder does not exist or is not a directory.")
        profile = new_watch_folder_profile(
            normalized,
            name=name or None,
            show_valorant_stats=show_valorant_stats,
            caption_enabled=caption_enabled,
            caption_text=caption_text,
        )
        candidate = [*config.watch_folders, profile]
        issues = [issue for issue in validate_watch_folders(candidate) if issue.severity == "error"]
        if issues:
            return _error(issues[0].message, issues=[asdict(issue) for issue in issues])
        config.watch_folders = candidate
        self._save(config)
        return {"ok": True, "message": f'Added watch folder "{profile.name}".', "data": profile_payload(profile)}

    def update_profile(self, profile_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        config = self._load()
        current = get_watch_folder_profile(config, profile_id)
        if current is None:
            return _error("Watch folder profile was not found.")

        new_path = normalize_watch_path(changes.get("path", current.path))
        if not new_path or not Path(new_path).is_dir():
            return _error("Selected watch folder does not exist or is not a directory.")
        new_name = str(changes.get("name", current.name) or "").strip()
        if not new_name:
            return _error("Watch folder name cannot be empty.")
        caption_text = str(changes.get("caption_text", current.caption_text) or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(caption_text) > MAX_PROFILE_CAPTION_CHARS:
            return _error(f"Caption must be {MAX_PROFILE_CAPTION_CHARS} characters or fewer.")

        updated = replace(
            current,
            name=new_name,
            path=new_path,
            show_valorant_stats=bool(changes.get("show_valorant_stats", current.show_valorant_stats)),
            caption_enabled=bool(changes.get("caption_enabled", current.caption_enabled)),
            caption_text=caption_text,
        )
        candidate = [updated if profile.id == current.id else profile for profile in config.watch_folders]
        issues = [issue for issue in validate_watch_folders(candidate) if issue.severity == "error"]
        if issues:
            return _error(issues[0].message, issues=[asdict(issue) for issue in issues])
        config.watch_folders = candidate
        self._save(config)
        return {"ok": True, "message": f'Updated watch folder "{updated.name}".', "data": profile_payload(updated)}

    def remove_profile(self, profile_id: str) -> dict[str, Any]:
        config = self._load()
        profile = get_watch_folder_profile(config, profile_id)
        if profile is None:
            return _error("Watch folder profile was not found.")

        # Failed jobs are also unresolved because the user may retry them later.
        # Removing their owning profile would make that retry/archive behavior
        # ambiguous, so require active and failed work to be resolved first.
        blocking_states = set(ACTIVE_STATES) | {"failed"}
        unresolved = [
            job
            for job in self.state.list_jobs_for_profile(profile.id, active_only=False, limit=1000)
            if str(job.get("status") or "") in blocking_states
        ]
        if unresolved:
            return _error(
                f'Cannot remove "{profile.name}" while it still has active or failed clip jobs. Resolve, finish, or skip those jobs first.'
            )
        config.watch_folders = [item for item in config.watch_folders if item.id != profile.id]
        self._save(config)
        return {
            "ok": True,
            "message": f'Removed watch folder "{profile.name}". No files were deleted.',
            "data": {"id": profile.id, "name": profile.name},
        }

    def open_paths(self, profile_id: str) -> dict[str, Any]:
        config = self._load()
        profile = get_watch_folder_profile(config, profile_id)
        if profile is None:
            return _error("Watch folder profile was not found.")
        archive = profile_uploaded_folder(profile)
        return {
            "ok": True,
            "message": "Watch-folder paths resolved.",
            "data": {
                "watchPath": profile.path,
                "uploadedPath": str(archive),
                "watchExists": Path(profile.path).is_dir(),
                "uploadedExists": archive.is_dir(),
            },
        }

    def ensure_uploaded_folder(self, profile_id: str) -> dict[str, Any]:
        config = self._load()
        profile = get_watch_folder_profile(config, profile_id)
        if profile is None:
            return _error("Watch folder profile was not found.")
        root = Path(profile.path)
        if not root.is_dir():
            return _error(f'Watch folder "{profile.name}" is missing.')
        archive = profile_uploaded_folder(profile)
        archive.mkdir(parents=False, exist_ok=True)
        if not path_is_profile_archive(archive, profile) or not archive.is_dir():
            return _error("Could not safely create the uploaded folder.")
        return {"ok": True, "message": "Uploaded folder is ready.", "data": {"path": str(archive)}}

    def preview_clear_uploaded(self, profile_id: str) -> dict[str, Any]:
        config = self._load()
        profile = get_watch_folder_profile(config, profile_id)
        if profile is None:
            return _error("Watch folder profile was not found.")
        return _preview_profile(profile)

    def clear_uploaded(self, profile_id: str) -> dict[str, Any]:
        config = self._load()
        profile = get_watch_folder_profile(config, profile_id)
        if profile is None:
            return _error("Watch folder profile was not found.")
        return _clear_profile(profile)

    def preview_clear_all_uploaded(self) -> dict[str, Any]:
        config = self._load()
        previews = [_preview_profile(profile) for profile in config.watch_folders]
        data = _aggregate_previews(previews)
        return {"ok": True, "message": "Clear-all preview ready.", "data": data}

    def clear_all_uploaded(self) -> dict[str, Any]:
        config = self._load()
        results = [_clear_profile(profile) for profile in config.watch_folders]
        deleted = sum(int(result.get("data", {}).get("deleted", 0)) for result in results)
        skipped = sum(int(result.get("data", {}).get("skipped", 0)) for result in results)
        failed = sum(int(result.get("data", {}).get("failed", 0)) for result in results)
        bytes_freed = sum(int(result.get("data", {}).get("bytesFreed", 0)) for result in results)
        return {
            "ok": failed == 0,
            "message": f"Cleared {deleted} archived file(s) across {len(config.watch_folders)} watch folder(s); skipped {skipped}; failed {failed}.",
            "data": {
                "profiles": len(config.watch_folders),
                "deleted": deleted,
                "skipped": skipped,
                "failed": failed,
                "bytesFreed": bytes_freed,
                "results": results,
            },
        }

    def _load(self) -> AppConfig:
        return load_config(self.config_path)

    def _save(self, config: AppConfig) -> None:
        save_config(config, self.config_path)


def profile_payload(profile: WatchFolderProfile) -> dict[str, Any]:
    archive = profile_uploaded_folder(profile)
    return {
        "id": profile.id,
        "name": profile.name,
        "path": profile.path,
        "uploadedPath": str(archive),
        "exists": Path(profile.path).is_dir(),
        "uploadedExists": archive.is_dir(),
        "showValorantStats": bool(profile.show_valorant_stats),
        "captionEnabled": bool(profile.caption_enabled),
        "captionText": profile.caption_text,
        "captionLength": len(profile.caption_text),
    }


def _preview_profile(profile: WatchFolderProfile) -> dict[str, Any]:
    archive = profile_uploaded_folder(profile)
    if not _archive_path_is_safe(profile, archive):
        return _error("Uploaded-folder safety check failed.")
    if not archive.exists():
        return {
            "ok": True,
            "message": "Uploaded folder does not exist yet.",
            "data": _preview_payload(profile, archive, 0, 0, 0, []),
        }
    if not archive.is_dir() or _is_reparse_or_link(archive):
        return _error("Uploaded folder is not a safe ordinary directory.")

    count = 0
    total_bytes = 0
    unexpected: list[str] = []
    for entry in archive.iterdir():
        try:
            if _is_safe_regular_file(entry):
                count += 1
                total_bytes += int(entry.stat().st_size)
            else:
                unexpected.append(entry.name)
        except OSError:
            unexpected.append(entry.name)
    return {
        "ok": True,
        "message": "Uploaded-folder preview ready.",
        "data": _preview_payload(profile, archive, count, total_bytes, len(unexpected), unexpected),
    }


def _clear_profile(profile: WatchFolderProfile) -> dict[str, Any]:
    preview = _preview_profile(profile)
    if not preview.get("ok"):
        return preview
    archive = profile_uploaded_folder(profile)
    if not archive.exists():
        data = preview.get("data", {})
        return {
            "ok": True,
            "message": f'Uploaded folder for "{profile.name}" is already empty.',
            "data": {**data, "deleted": 0, "skipped": 0, "failed": 0, "bytesFreed": 0},
        }

    deleted = skipped = failed = 0
    bytes_freed = 0
    errors: list[str] = []
    for entry in archive.iterdir():
        if not _is_safe_regular_file(entry):
            skipped += 1
            continue
        try:
            size = int(entry.stat().st_size)
            entry.unlink()
            deleted += 1
            bytes_freed += size
        except OSError as exc:
            failed += 1
            errors.append(f"{entry.name}: {exc.__class__.__name__}")
    return {
        "ok": failed == 0,
        "message": f'Cleared {deleted} archived file(s) from "{profile.name}"; skipped {skipped}; failed {failed}.',
        "data": {
            "profileId": profile.id,
            "profileName": profile.name,
            "archivePath": str(archive),
            "deleted": deleted,
            "skipped": skipped,
            "failed": failed,
            "bytesFreed": bytes_freed,
            "errors": errors,
        },
    }


def _preview_payload(
    profile: WatchFolderProfile,
    archive: Path,
    file_count: int,
    total_bytes: int,
    unexpected_count: int,
    unexpected_entries: list[str],
) -> dict[str, Any]:
    return {
        "profileId": profile.id,
        "profileName": profile.name,
        "archivePath": str(archive),
        "fileCount": file_count,
        "totalBytes": total_bytes,
        "unexpectedCount": unexpected_count,
        "unexpectedEntries": unexpected_entries,
    }


def _aggregate_previews(previews: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [preview.get("data", {}) for preview in previews if preview.get("ok")]
    return {
        "profiles": len(previews),
        "archiveFolders": len(successful),
        "fileCount": sum(int(item.get("fileCount", 0)) for item in successful),
        "totalBytes": sum(int(item.get("totalBytes", 0)) for item in successful),
        "unexpectedCount": sum(int(item.get("unexpectedCount", 0)) for item in successful),
        "profilesWithErrors": len(previews) - len(successful),
        "previews": previews,
    }


def _archive_path_is_safe(profile: WatchFolderProfile, archive: Path) -> bool:
    if not path_is_profile_archive(archive, profile):
        return False
    expected_parent = Path(profile.path).expanduser().resolve(strict=False)
    actual_parent = archive.parent.expanduser().resolve(strict=False)
    return os.path.normcase(str(expected_parent)) == os.path.normcase(str(actual_parent))


def _is_safe_regular_file(path: Path) -> bool:
    try:
        return path.is_file() and not _is_reparse_or_link(path)
    except OSError:
        return False


def _is_reparse_or_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        stat_result = path.lstat()
        attrs = getattr(stat_result, "st_file_attributes", 0)
        reparse_flag = getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        return bool(reparse_flag and attrs & reparse_flag)
    except OSError:
        return True


def _error(message: str, *, issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"ok": False, "message": message, "issues": issues or [], "data": {}}
