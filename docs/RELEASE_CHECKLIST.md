# ClipDis Release Checklist

Use this checklist before publishing a Windows release.

## Build

- Release EXE opens with no console.
- Release folder contains `ClipDis.exe` and `_internal`.
- `_internal` includes QML/assets, FFmpeg binaries, and FFmpeg license files.
- Do not delete `_internal`.

## Window and Tray

- Dashboard opens on launch.
- Tray icon appears.
- Taskbar, Alt+Tab, Explorer, and tray icons are correct.
- Second launch restores the existing instance instead of creating another tray app.
- Close hides to tray.
- Tray Exit quits.

## Settings

- Settings persist after restart.
- Watch folder and uploaded/archive folder validate.
- Webhook test works with a user-provided webhook.
- Valorant stats test works if configured.
- Start with Windows writes/removes the HKCU Run value.

## Dashboard and Pipeline

- Thumbnails load without restart.
- One clip uploads successfully.
- Original moves only after Discord upload succeeds.
- Failed upload leaves original in the watch folder.
- Auto Upload processes eligible clips until none remain.
- Failed clips are not automatically retried.

## Security

- No secrets in logs or diagnostics.
- No secrets committed to Git.
- No user appdata/config/state bundled into the release.
