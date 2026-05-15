# v1.0.0 - Initial Release

## Added

- Windows tray app for compressing gaming clips and uploading them to Discord.
- Watch-folder detection with safe file-ready checks.
- Bundled FFmpeg/FFprobe support.
- Discord webhook upload with safe archive behavior.
- Dashboard with thumbnail previews, manual upload, selected upload, and Auto Upload.
- Optional Valorant rank/level through HenrikDev.
- Persistent settings and SQLite job state.
- Single-instance behavior and optional Start with Windows.
- No-console PyInstaller release build.

## Setup

1. Download `ClipDis-v1.0.0-windows-x64.zip`.
2. Extract the full ZIP.
3. Run `ClipDis.exe`.
4. Do not delete `_internal`.
5. Configure Watch Folder, Uploaded Folder, and Discord Webhook in Settings.
6. See `README.md` for beginner Discord webhook setup instructions.

## Optional Valorant Stats

Valorant rank/level support requires a HenrikDev API key. See `README.md` for setup notes and the HenrikDev Discord invite: https://discord.gg/U2V8p6g2r

## Notes

- Windows x64 only.
- Bundled FFmpeg is included.
- Webhook and API keys are stored locally and should never be committed or shared.
- If Valorant stats are unavailable, ClipDis should still upload clips.

## Asset

- `ClipDis-v1.0.0-windows-x64.zip`
