<h1 align="center">ClipDis</h1>

<p align="center">
  <img src="docs/images/clipdis-icon.png" alt="ClipDis app icon" width="160">
</p>

<p align="center">
  A Windows tray app that compresses gaming clips and uploads them to Discord.
</p>

<p align="center">
  <a href="https://github.com/Hermann-33/ClipDis/releases">Download ClipDis</a>
</p>

## What Is ClipDis?

ClipDis watches a clips folder, waits for new videos to finish writing, compresses them with bundled FFmpeg, uploads them to Discord through a webhook, and moves successfully uploaded originals to your uploaded/archive folder.

It is built for people who record Valorant or other gaming clips and want a simple way to send videos to Discord without manually compressing, checking file sizes, or dragging files into a channel.

## Who Is This For?

- Players who record Valorant or other gaming clips.
- People who want clip uploads to Discord without manual video compression.
- Small communities that want clips posted into one Discord channel.
- Users who prefer a small tray utility instead of a large dashboard app.

## Features

| Feature | What It Does |
| --- | --- |
| Watch folder | Monitors the folder where your recorder saves clips. |
| Uploaded/archive folder | Moves originals only after Discord confirms upload success. |
| FFmpeg compression | Uses bundled FFmpeg, so normal users do not need a separate FFmpeg install. |
| Discord webhook upload | Uploads clips directly to your chosen Discord channel. |
| Manual upload | Upload one clip or selected clips from the dashboard. |
| Auto Upload | Automatically processes eligible clips until none remain. |
| Thumbnail previews | Shows clip thumbnails in the dashboard grid. |
| Tray behavior | Runs quietly in the Windows system tray; closing the window hides it. |
| Persistent settings | Saves folders, options, and durable job state locally. |
| Optional Valorant stats | Can include Valorant rank and level using HenrikDev. |
| Start with Windows | Optional startup toggle for launching ClipDis when you sign in. |

## Requirements

For normal users:

- Windows 10 or Windows 11.
- A Discord server/channel where you can create or use a webhook.
- The downloaded ClipDis release ZIP.
- No Python installation required.
- No external FFmpeg installation required when using the bundled release.

For developers:

- Python 3.11+ recommended.
- Dependencies from `requirements.txt`.
- PyInstaller for packaging test builds.

## Download And Install

1. Go to the [ClipDis Releases page](https://github.com/Hermann-33/ClipDis/releases).
2. Download `ClipDis-v1.0.0-windows-x64.zip`.
3. Extract the ZIP somewhere convenient, such as your Desktop or Downloads folder.
4. Open the extracted folder.
5. Run `ClipDis.exe`.
6. Do not delete `_internal`.

> **Important:** `_internal` contains the packaged runtime, QML files, icons, and bundled FFmpeg. If you delete `_internal`, ClipDis will not run correctly.

## First-Time Setup

1. Open `ClipDis.exe`.
2. Click the settings button in the top-right corner.
3. Choose your **Watch Folder**.
4. Choose your **Uploaded Folder**.
5. Paste your Discord webhook URL.
6. Click **Test Webhook** if the button is available.
7. Click **Save Configuration**.
8. Upload one clip manually first.
9. Enable **Auto Upload** only after the manual test works.

### Folder Choices

| Setting | Meaning |
| --- | --- |
| Watch Folder | The folder where NVIDIA ShadowPlay, OBS, Medal, or another recorder saves new clips. |
| Uploaded Folder | The folder where ClipDis moves originals after a successful Discord upload. |

ClipDis only moves an original clip after Discord confirms that upload succeeded. Failed clips stay in the watch folder so you do not lose them.

## How To Create A Discord Webhook URL

A Discord webhook is a private URL that lets ClipDis post clips into one channel.

1. Open Discord.
2. Go to your server.
3. Choose the channel where clips should be posted.
4. Click the channel settings gear, also called **Edit Channel**.
5. Open **Integrations**.
6. Choose **Webhooks**.
7. Click **New Webhook**.
8. Name it `ClipDis`.
9. Optionally choose an avatar.
10. Click **Copy Webhook URL**.
11. Paste the URL into ClipDis Settings.
12. Save your settings.

> **Keep your webhook private.** Anyone with the webhook URL can post into that Discord channel. If it leaks, delete the webhook in Discord and create a new one.

## Auto Upload

When **Auto Upload** is on, ClipDis keeps working through eligible clips in the watch folder:

```text
new clip -> ready check -> compress -> upload to Discord -> move original to uploaded folder
```

A few safety rules matter:

- Originals move only after Discord confirms upload success.
- Failed clips are not blindly retried forever.
- You can still manually upload clips when Auto Upload is off.
- Test one manual upload before turning Auto Upload on.

## Optional Valorant Stats

ClipDis can optionally include Valorant rank and account level in the Discord message.

To use Valorant stats, enable **Use Valorant Stats** in Settings and provide:

- Riot username.
- Riot tagline.
- Valorant region.
- HenrikDev API key.

HenrikDev API keys are handled through HenrikDev's system and community. You can start from the HenrikDev Discord invite:

[https://discord.gg/U2V8p6g2r](https://discord.gg/U2V8p6g2r)

Stats are optional. If stats are disabled or HenrikDev is unavailable, ClipDis should still upload the clip. Do not share your HenrikDev API key publicly.

## Folder Behavior

- **Watch Folder** is where new clips appear.
- **Uploaded Folder** is where originals move after successful upload.
- **Temporary work files** are created outside the release folder.
- **Settings and state** persist locally in your Windows user data.
- **`_internal`** is part of the packaged app and must stay beside `ClipDis.exe`.

When updating ClipDis, replace the app files, not your watch/upload folders.

## Privacy And Security

- Discord webhook URLs are stored locally and redacted in the UI where possible.
- HenrikDev API keys are stored locally and redacted in the UI where possible.
- Treat a Discord webhook like a password because it can post into your channel.
- Do not commit or share webhook URLs or API keys.
- Logs and diagnostics are intended to redact secrets.
- If you accidentally share a webhook or API key, rotate it immediately.

## Updating ClipDis

1. Download the newer release ZIP from the [Releases page](https://github.com/Hermann-33/ClipDis/releases).
2. Extract it into a fresh folder.
3. Run the new `ClipDis.exe`.
4. Keep `_internal` with the EXE.
5. Your existing settings should remain because they are stored in your Windows user data.

Avoid mixing random files from old and new builds. Extract the new ZIP cleanly.

## Troubleshooting

| Problem | What To Try |
| --- | --- |
| App does not open | Make sure `ClipDis.exe` is still next to `_internal`. Try extracting the ZIP again. |
| Windows warns about unknown publisher | This can happen with unsigned apps. Only run builds downloaded from the official GitHub Releases page. |
| Discord upload fails | Re-test your webhook, check the channel still exists, and confirm the file is not too large. |
| Webhook test fails | Create a fresh Discord webhook and paste the new URL into Settings. |
| Clips do not appear | Confirm the Watch Folder points to the folder where your recorder saves `.mp4` clips. |
| Thumbnails do not load | Give ClipDis a few seconds. If needed, restart once and check that bundled FFmpeg is present. |
| Upload is too large | Lower the max upload size setting or use shorter clips. Discord limits depend on your server/account. |
| Auto Upload does nothing | First confirm manual upload works, then ensure Auto Upload is on and the clip is not already failed. |
| Valorant stats unavailable | Check Riot name, tagline, region, and HenrikDev API key. Clip upload can still work without stats. |
| `_internal` was deleted | Extract the release ZIP again. `_internal` is required. |

## For Developers

ClipDis is a Python, PySide6, and QML desktop app packaged with PyInstaller.

Basic source workflow:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

Useful checks:

```powershell
python main.py --smoke-check
python main.py --qml-smoke-check
python main.py --diagnose
```

Release packaging uses:

```powershell
cmd /c build.bat release
```

The source code is separate from the release ZIP. Do not commit `dist/`, `dist_release/`, release ZIP files, logs, databases, local config, or secrets.
