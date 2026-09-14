# ClipDis Project Audit

## Status

Latest public release: **v1.1.0 — Multi-Watch Folders**, published September 14, 2026.

Release tag: `v1.1.0`

Release source commit: `8affaab92a10932808bc37bee537eb631335b3bd`

Windows release asset: `ClipDis-v1.1.0-windows-x64.zip`

SHA-256: `150ba3612d03638cbe969c2053254172bd71c46bcccb0128db724df4d3c55d45`

The v1.1.0 backend, GuiBridge/QML integration, multi-profile workflows, Windows packaging and release automation are complete and published. The final release was rebuilt and verified on a fresh Windows GitHub Actions runner before publication, including an explicit Windows PE icon-resource check.

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
- `app/tray.py`, `app/gui_bridge.py`, and QML files provide the tray/QML UI bridge, including stable-ID profile management, source labels/filtering and scoped archive actions.
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

Legacy config mirror fields remain for backward-compatibility boundaries, but v1.1 profile-aware runtime/UI behavior uses `watch_folders` as the source of truth.

## SQLite Model

Additive job columns:

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

Archive clearing is implemented behind profile-ID-scoped APIs. QML does not send arbitrary filesystem deletion paths. Clear previews report file count/bytes, and clear operations skip unexpected directories/links/reparse points instead of recursively destroying them.

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

Published v1.1.0 UI structure:

- `app/gui/main.qml`: main shell/top bar/settings wiring/custom chrome.
- `app/gui/Dashboard.qml`: action strip, source-profile filtering, clip grid, selected actions, details panel, live thumbnail refresh.
- `app/gui/Settings.qml`: global configuration plus visible watch-profile management, Performance and Logs sections.
- `app/gui/components/`: reusable cards/controls/dialogs, including profile-management surfaces.

Implemented v1.1 integration:

- visible watch-profile management list/cards;
- add/edit/remove profile flow;
- no user-facing Uploaded Folder picker;
- per-profile stats/caption controls;
- derived archive path display;
- profile labels on clip cards/details;
- dashboard All Folders/profile filter;
- exact filtered selection semantics;
- Open Folders command menu;
- Clear Uploaded profile/all command menu;
- preview-backed explicit destructive confirmation dialogs;
- per-profile missing states;
- profile-aware diagnostics.

## Regression Tests

The completed v1.1.0 suite contains **21 automated tests**, including:

- config migration and stable profile IDs;
- duplicate/nested-root rejection;
- SQLite profile ownership;
- archive-subtree pruning;
- A/B archive isolation;
- clear-one/clear-all safety;
- active/failed/uploaded-job profile-removal protection;
- independent captions and Valorant toggles;
- zero Henrik request for stats-disabled profiles;
- Discord mention suppression;
- GuiBridge profile behavior;
- stable-ID dashboard filtering and exact Select All Visible behavior.

The suite passed both local Windows validation and the final clean GitHub Actions release build.

## Packaging Model

PyInstaller uses `ClipDis.spec`.

- debug onedir: `dist/ClipDis/ClipDis.exe`;
- release onedir: `dist_release/ClipDis/ClipDis.exe`;
- `_internal` remains required;
- bundled FFmpeg/FFprobe/license remain part of the package;
- `app_icon.ico` is embedded into the Windows EXE and the icon assets are also retained in packaged GUI data;
- runtime Qt sets the app/window/tray icon and `Hermann.ClipDis` AppUserModelID;
- incompatible host-PATH ICU DLLs are explicitly excluded from the packaged distribution.

## v1.1.0 Release Verification

The final release workflow on a fresh Windows runner passed all of these gates:

```text
Git LFS checkout and FFmpeg materialization
Python compile check
21 automated tests
PyInstaller no-console release build
required package-file verification
FFmpeg/FFprobe/license presence
QML and app-icon asset presence
no stray icu*.dll payload
Windows PE RT_GROUP_ICON verification
packaged --smoke-check
packaged --qml-smoke-check
packaged --diagnose
clean AppData isolation
release ZIP structure verification
SHA-256 generation
release asset upload
release publication
```

The final Windows ZIP contains `ClipDis.exe` and `_internal/` at the top level, not an extra nested `ClipDis/` directory.

## Known Technical Debt / Follow-Up Work

- legacy config compatibility mirror fields remain and can be revisited in a future breaking-cleanup cycle;
- `%APPDATA%\ValorantClipUploader` remains intentionally unchanged for compatibility;
- installer/signing/uninstall cleanup are not implemented;
- the user's previously existing local `state.db` was found corrupt during v1.1 QA and was intentionally not deleted or rewritten because doing so could discard job history; isolated/fresh state passed all release checks;
- a real Discord clip upload to a confirmed disposable test channel was not performed during release QA, although webhook validation and mocked multipart upload behavior passed;
- additional interactive clean-machine tray/window QA remains useful follow-up coverage even though the release package itself was built and executed on a fresh Windows CI runner.

See `docs/V1.1.0_MULTI_WATCH_DESIGN.md` for the full feature design, migration and safety contract.
