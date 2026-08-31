# Changelog

## v1.1.0 - Unreleased

### Added

- Added multiple watch-folder profiles with stable IDs, friendly names, independent paths, per-profile Valorant metadata settings, and per-profile custom Discord captions.
- Added an automatic `ClipDis Uploaded` archive directory inside every watch folder. Users no longer need to configure a separate uploaded folder.
- Added durable watch-folder ownership to SQLite jobs through `watch_folder_id` and `watch_folder_path`.
- Added a profile-management backend service for add/edit/remove, derived archive paths, uploaded-folder creation, clear previews, clear-one, and clear-all behavior.
- Added per-profile archive/file-count/size previews for destructive clear operations.
- Added Discord mention suppression for user-defined captions through `allowed_mentions.parse = []`.
- Added regression tests for config migration, profile validation, profile-scoped state, scanner exclusion, archive isolation, clear isolation, removal safety, captions, per-profile Valorant behavior, and Discord mention suppression.

### Changed

- The watcher now scans every configured watch-folder profile while retaining one global processing/upload/archive pipeline.
- Each profile's `<watch root>\ClipDis Uploaded` subtree is pruned before discovery so archived clips cannot be rediscovered and re-uploaded.
- Duplicate and parent/child-overlapping watch roots are rejected to keep clip ownership unambiguous.
- Successful uploads archive into the owning watch profile's derived archive directory rather than a global user-selected uploaded folder.
- Valorant credentials remain global, but whether rank/level is requested and displayed is controlled per watch-folder profile.
- Discord message content can now combine a profile caption and Valorant rank/level with deterministic spacing and the Discord 2,000-character limit enforced.
- Missing watch folders no longer stop scanning of other valid profiles.
- Removing a watch-folder profile is blocked while it owns active or failed jobs that could still require that profile.

### Migration

- Configuration schema is now version 2.
- Existing v1.0.0 installations with a legacy `watch_folder` are migrated automatically into one watch-folder profile.
- A one-time `config.v1.backup.json` is retained beside the live config before migration.
- Existing legacy uploaded-folder contents are not deleted, moved, or silently imported. New successful uploads use `<watch root>\ClipDis Uploaded`.
- `%APPDATA%\ValorantClipUploader` remains the persistence namespace for compatibility.

### Pending before v1.1.0 release

- QML/GuiBridge integration for full multi-profile management, dashboard filtering, open-folder menus, and scoped confirmation dialogs.
- Local Windows source-mode and packaged-build verification.
- Computer-use UX verification and fix loop.
- Final documentation synchronization after verified UI behavior.

## v1.0.0 - Initial Public Release

- Initial public release of ClipDis.
- Added clip folder watching and file-ready detection.
- Added bundled FFmpeg compression.
- Added Discord webhook uploads.
- Added uploaded/archive folder movement after confirmed upload.
- Added PySide6/QML dashboard and tray UI.
- Added thumbnail previews.
- Added manual single/selected clip upload and Auto Upload mode.
- Added optional Valorant rank/level via Henrik API.
- Added persistent settings and SQLite job state.
- Added single-instance behavior.
- Added Start with Windows option.
- Added packaged no-console Windows release build support.
