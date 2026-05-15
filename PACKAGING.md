# Packaging Notes

This app expects FFmpeg to be bundled for normal users. The Settings UI does
not expose a manual FFmpeg path.

## Required Bundled Files

Include these files with releases:

- `app/ffmpeg/bin/ffmpeg.exe`
- `app/ffmpeg/bin/ffprobe.exe`
- `app/ffmpeg/bin/LICENSE*`, `COPYING*`, or `NOTICE*` files that ship with the FFmpeg build
- `app/gui/**/*.qml`
- `app/gui/assets/*`
- `app/gui/components/*`

## PyInstaller Example

Preferred test builds use the checked-in spec file:

```powershell
.\build.bat
```

This creates an onedir console-enabled test build at:

- `dist\ClipDis\ClipDis.exe`

For a no-console release-style QA build, run:

```powershell
.\build.bat release
```

This creates:

- `dist_release\ClipDis\ClipDis.exe`

After onedir works, create a onefile test build:

```powershell
.\build.bat onefile
```

This creates:

- `dist\ClipDis.exe`

The build script intentionally cleans only local PyInstaller build outputs. It
builds into a temporary staging directory first and only replaces the target
output directory after PyInstaller succeeds, so an interrupted build is less
likely to leave the project without a usable previous `dist` or `dist_release`
folder. Its source smoke checks run with temporary `APPDATA` / `LOCALAPPDATA`
values so they do not write test config/state into the user's real appdata. It
does not delete user appdata, config, state, logs, thumbnails, or secrets.

Manual PyInstaller equivalent:

```powershell
pyinstaller --noconsole --name ClipDis `
  --icon "app\gui\assets\app_icon.ico" `
  --add-binary "app\ffmpeg\bin\ffmpeg.exe;app\ffmpeg\bin" `
  --add-binary "app\ffmpeg\bin\ffprobe.exe;app\ffmpeg\bin" `
  --add-data "app\gui;app\gui" `
  --collect-all PySide6 `
  main.py
```

If the command misses QML plugins on a target machine, use `ClipDis.spec` and
explicitly collect PySide6 Qt/QML plugins. The app uses QML, so packaging must
include both the QML source files and the Qt QML runtime plugins.

At runtime, packaged builds resolve FFmpeg under PyInstaller's extracted
bundle directory, typically:

- `_MEIPASS/app/ffmpeg/bin/ffmpeg.exe`
- `_MEIPASS/app/ffmpeg/bin/ffprobe.exe`

Source/dev builds resolve:

- `app/ffmpeg/bin/ffmpeg.exe`
- `app/ffmpeg/bin/ffprobe.exe`

## User Data

Config, secrets, state, logs, and thumbnails must stay in the user's app data
locations, not beside the packaged EXE. The current app data folder name remains
`ValorantClipUploader` intentionally so existing user data is not broken during
this rename cycle.

## Startup Entry

The Start with Windows setting writes the HKCU Run value named `ClipDis`. In a
frozen build it should point to `sys.executable`; in source/dev mode it points
to the Python executable plus `main.py`.

## App Icon / Taskbar Identity

Both debug and release builds use the multi-size Windows icon:

- `app/gui/assets/app_icon.ico`

The runtime also sets the QApplication/window/tray icon and the Windows
AppUserModelID `Hermann.ClipDis` so taskbar grouping and Alt+Tab use the
ClipDis icon.

## Single Instance

Normal no-argument launches enforce a single ClipDis instance with Qt local IPC.
If ClipDis is already running, the second launch sends a `show` message to the
first instance and exits. Diagnostic commands such as `--diagnose`,
`--smoke-check`, and `--qml-smoke-check` still run independently.

## License Notice

When distributing FFmpeg, include the applicable FFmpeg license files and
third-party notices from the FFmpeg build being shipped. The spec bundles
`LICENSE*`, `COPYING*`, and `NOTICE*` files from both `app/ffmpeg` and
`app/ffmpeg/bin` when present. The exact license obligations depend on the
FFmpeg build configuration.

## Test Commands

Run these against the built executable before public release:

```powershell
.\dist\ClipDis\ClipDis.exe --smoke-check
.\dist\ClipDis\ClipDis.exe --qml-smoke-check
.\dist\ClipDis\ClipDis.exe --diagnose
.\dist\ClipDis\ClipDis.exe --test-valorant-stats
```

For the no-console release build, CLI diagnostics still run but stdout is not
visible from a normal terminal. Keep the console-enabled onedir build for
diagnostic command output, and use `dist_release\ClipDis\ClipDis.exe` for manual
launch/UI/tray QA.

For onefile:

```powershell
.\dist\ClipDis.exe --smoke-check
.\dist\ClipDis.exe --qml-smoke-check
.\dist\ClipDis.exe --diagnose
```

## Clean-Machine QA Checklist

- Test on a Windows machine or VM without Python installed.
- Test without system FFmpeg installed.
- Start with no existing `%APPDATA%\ValorantClipUploader` folder.
- First run opens the tray app and dashboard.
- Settings can save watch and uploaded folders.
- Bundled FFmpeg test passes.
- Discord webhook test passes with a user-provided webhook.
- Henrik stats test passes with a user-provided API key.
- Upload one small test clip.
- Restart and verify config, secrets, state, and thumbnails persist.
- Start with Windows writes/removes the HKCU Run value named `ClipDis`.
- Tray tooltip is `ClipDis`; tray menu contains only `Open Dashboard` and `Exit`.
- Close hides to tray; tray Exit quits.

Installer packaging, signing, shortcuts, uninstall cleanup, and final QA on a
clean Windows VM are separate release tasks and are not covered here.
