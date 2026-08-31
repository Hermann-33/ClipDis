# ClipDis Project Audit

## Status

Latest public release: **v1.0.0**.

Current development target on `feature/v1.1.0-multi-watch-folders`: **v1.1.0 — Unreleased**.

The v1.1.0 core backend architecture is implemented on the feature branch. QML/GuiBridge integration, local Windows execution, packaged-build verification, and computer-use UX testing are still required before merge/release.

## Summary

ClipDis is a Windows PySide6/QML tray application for safely uploading gaming clips to Discord. It polls configured clip sources, waits for files to become stable, compresses clips with bundled FFmpeg, uploads via Discord webhook, optionally includes Valorant rank/level through Henrik API, archives originals only after confirmed upload, and stores durable state in SQLite.

v1.1.0 replaces the v1.0.0 single watch-folder/global archive model with stable-ID watch-folder profiles. Each profile derives its own `<watch root>\ClipDis Uploaded` archive, can independently enable Valorant metadata, and can optionally attach a custom Discord caption.

## Architecture

- `main.py` starts diagnostics, Qt runtime setup, single-instance handling, tray/window wiring, worker startup, and CLI checks.
- `app/config.py` owns versioned config schema, watch-folder profiles, migration, path normalization, overlap validation, and the persistent `%APPDATA%\ValorantClipUploader` compatibility namespace.
- `app/watch_folders.py` owns profile CRUD and profile-ID-scoped archive maintenance/clear behavior.
- `app/worker.py` scans all watch profiles while retaining one global processing/upload/archive pipeline and the existing concurrency locks.
- `app/state.py` owns SQLite job state/transitions and persists `watch_folder_id`/`watch_folder_path` ownership for v1.1 jobs.
- `app/archive.py` resolves the owning watch profile and derives its archive destination after confirmed upload.
- `app/discord_uploader.py` validates/uploads to Discord, composes per-profile captions/Valorant metadata, enforces content length, suppresses Discord mentions, and preserves retry classification.
- `app/valorant_stats.py` fetches Henrik MMR rank/account level using the shared global Riot/Henrik identity.
- `app/secrets.py` stores Discord/Henrik secrets through keyring/Windows Credential Manager or local fallback.
- `app/ffmpeg_runner.py` resolves bundled FFmpeg/FFprobe and runs compression.
- `app/thumbnailer.py` creates cached thumbnails using bundled FFmpeg.
- `app/tray.py`, `app/gui_bridge.py`, and QML files provide the tray/QML UI bridge. These still require final v1.1 profile-management integration.
- `app/single_instance.py` prevents multiple tray instances and restores the running app.
- `app/startup.py` manages HKCU Run startup behavior.

## v1.1 Watch-Folder Model

Profile fields:

```text
id
name
path
show_valorant_stats
caption_enabled
caption_text
```

Archive path:

```text
<profile.path>\ClipDis Uploaded
```

Rules:

- profile IDs are stable UUIDs;
- duplicate roots are rejected;
- parent/child overlapping roots are rejected;
- one physical clip belongs to one profile;
- `ClipDis Uploaded` is pruned before recursive discovery;
- one missing watch profile does not stop valid profiles;
- multiple profiles do not create multiple FFmpeg pipelines.

## Config Migration

Schema version: `2`.

Legacy v1 configuration is migrated once:

- legacy `watch_folder` -> one profile;
- legacy `use_henrik_stats` -> that profile's stats toggle;
- caption -> off/empty;
- one-time `config.v1.backup.json` before rewriting;
- legacy uploaded-folder contents are untouched;
- new successful uploads use the derived profile archive.

Temporary legacy config mirrors remain while v1.0-era UI/call sites are converted. They must not become the long-term v1.1 source of truth.

## SQLite Model

New additive job columns:

```text
watch_folder_id TEXT
watch_folder_path TEXT
```

Existing state/history is preserved. Legacy jobs may be backfilled only when their source path maps unambiguously to one profile.

A profile cannot be removed while it owns active or failed jobs that may still require retry/process/upload/archive context.

## Archive Safety

The strongest product invariant is unchanged:

```text
Never move/delete the original clip before Discord confirms upload success.
```

After success, the owning profile determines the derived archive destination. Filename collision behavior remains preserved.

Archive clearing is implemented behind profile-ID-scoped APIs. QML must not send an arbitrary filesystem deletion path. Clear previews report file count/bytes, and clear operations skip unexpected directories/links/reparse points instead of recursively destroying them.

## Discord/Valorant Behavior

Global identity/credentials:

```text
Discord webhook
Riot username
Riot tagline
Valorant region
Henrik API key
```

Per profile:

```text
show_valorant_stats
caption_enabled
caption_text
```

A stats-disabled profile performs no Henrik request for its upload. Stats remain optional if enabled but unavailable.

Profile captions and stats are composed as separate Discord content sections. Final content is limited to Discord's 2,000-character constraint. Multipart uploads use `allowed_mentions.parse = []` so arbitrary caption text cannot produce broad mentions through ClipDis.

## GUI/QML Status

Current v1.0 UI structure:

- `app/gui/main.qml`: main shell/top bar/settings wiring/custom chrome.
- `app/gui/Dashboard.qml`: action strip, clip grid, selected actions, details panel, live thumbnail refresh.
- `app/gui/Settings.qml`: configuration, Performance, and Logs sections.
- `app/gui/components/`: reusable cards/controls/dialogs.

Required v1.1 integration still pending:

- visible watch-profile management list/cards;
- add/edit/remove profile flow;
- no user-facing Uploaded Folder picker;
- per-profile stats/caption controls;
- derived archive path display;
- profile labels on clip cards/details;
- dashboard All Folders/profile filter;
- filtered selection semantics;
- Open Folders command menu;
- Clear Uploaded profile/all command menu;
- preview-backed explicit destructive confirmation dialogs;
- per-profile missing states;
- updated diagnostics.

## Regression Tests Added

`tests/test_v110_multi_watch.py` covers core backend requirements including config migration, path overlap validation, SQLite profile ownership, archive-subtree pruning, archive isolation, clear-one isolation, removal safety, caption/stat formatting, per-profile Henrik gating, and mention suppression.

These tests are committed but **not yet executed in the connected GitHub editing environment**. Local test execution is mandatory before the feature branch is merged.

## Packaging Model

PyInstaller uses `ClipDis.spec`.

- debug onedir: `dist/ClipDis/ClipDis.exe`;
- release onedir: `dist_release/ClipDis/ClipDis.exe`;
- `_internal` remains required;
- bundled FFmpeg/FFprobe/license remain part of the package.

v1.1 does not intentionally change the packaging model.

## Known Technical Debt / Pending Work

- v1.0-era GuiBridge/QML still requires conversion to the profile service.
- temporary config compatibility mirrors exist during migration and should be reviewed after all old call sites are removed.
- Windows source-mode, QML smoke, packaged debug/release, and computer-use UX verification have not yet been run for v1.1.
- clean Windows VM QA remains required before public release.
- appdata name remains `ValorantClipUploader` intentionally for compatibility.
- installer/signing/uninstall cleanup remain outside this feature.

## Definition Of v1.1 Backend Done

Core backend is not considered verified until the following run locally:

```powershell
python -m unittest discover -s tests -v
python -m compileall main.py app tests
python main.py --smoke-check
python main.py --qml-smoke-check
python main.py --diagnose
```

Then the packaged app must be built and exercised on Windows with at least two isolated watch roots and their derived archives.

See `docs/V1.1.0_MULTI_WATCH_DESIGN.md` for the complete design/safety/test contract.
