# ClipDis Project Audit

## Summary

ClipDis is a Windows PySide6/QML tray application for safely uploading gaming clips to Discord. It watches a configured folder, waits for files to become stable, compresses clips with bundled FFmpeg, uploads via Discord webhook, optionally includes Valorant rank/level through Henrik API, archives originals after confirmed upload, and stores durable state in SQLite.

## Architecture

- `main.py` starts diagnostics, Qt runtime setup, single-instance handling, tray/window wiring, worker startup, and CLI checks.
- `app/worker.py` coordinates watcher, processing, upload, archive, auto pipeline, and selected-only jobs.
- `app/state.py` owns SQLite job state and state transitions.
- `app/config.py` stores appdata configuration under `%APPDATA%\ValorantClipUploader` for compatibility.
- `app/secrets.py` stores Discord/Henrik secrets through keyring/Windows Credential Manager or local fallback.
- `app/ffmpeg_runner.py` resolves bundled FFmpeg/FFprobe and runs compression.
- `app/discord_uploader.py` validates and uploads to Discord.
- `app/valorant_stats.py` fetches Henrik MMR rank and account level.
- `app/archive.py` moves originals only after confirmed upload and handles compressed cleanup.
- `app/thumbnailer.py` creates cached thumbnails using bundled FFmpeg.
- `app/tray.py`, `app/gui_bridge.py`, and QML files provide the tray/QML UI bridge.
- `app/single_instance.py` prevents multiple tray instances and restores the running app.
- `app/startup.py` manages HKCU Run startup behavior.

## GUI/QML Map

- `app/gui/main.qml`: main shell, top bar, settings panel wiring, custom chrome.
- `app/gui/Dashboard.qml`: action strip, clip grid, selected actions, details panel, live thumbnail refresh.
- `app/gui/Settings.qml`: configuration, Performance, and Logs sections.
- `app/gui/Performance.qml`: retained compatibility page/component if loaded by smoke checks.
- `app/gui/Logs.qml`: retained compatibility log page/component.
- `app/gui/components/`: reusable buttons, cards, combo box, confirm dialog, clip cards, title bar, and related UI components.
- `app/gui/assets/`: app/settings/social icon assets.

## Persistence Model

User data intentionally remains under `%APPDATA%\ValorantClipUploader` for compatibility with earlier builds. Runtime work files use the OS temp directory. Thumbnails are cached under appdata unless configured otherwise. Secrets are local and redacted.

## Packaging Model

PyInstaller uses `ClipDis.spec`. Debug onedir output is `dist/ClipDis/ClipDis.exe`; no-console release output is `dist_release/ClipDis/ClipDis.exe`. QML/assets, PySide6 runtime, FFmpeg binaries, and FFmpeg license files are bundled into `_internal`.

## Known Technical Debt

- Appdata folder name still uses `ValorantClipUploader` for compatibility.
- Installer/signing/uninstall cleanup are not implemented yet.
- Clean Windows VM QA is still required before public release.
- Some legacy QML pages remain for smoke-check compatibility.

## Final Release Status

The source is prepared for v1.0.0 packaging and GitHub publication once build, diagnostics, release zip creation, and clean-machine QA pass.
