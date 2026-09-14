<h1 align="center">ClipDis</h1>

<p align="center">
  <img src="docs/images/clipdis-icon.png" alt="ClipDis app icon" width="160">
</p>

<p align="center">
  A Windows tray app that compresses gaming clips and uploads them to Discord.
</p>

<p align="center">
  <a href="https://github.com/Hermann-33/ClipDis/releases/latest">Download ClipDis</a>
</p>

## Release Status

The latest public binary release is **v1.1.0 — Multi-Watch Folders**, published on September 14, 2026.

Download the verified Windows release from the [ClipDis Releases page](https://github.com/Hermann-33/ClipDis/releases/tag/v1.1.0).

See `CHANGELOG.md` and `docs/V1.1.0_MULTI_WATCH_DESIGN.md` for implementation and verification details.

## What Is ClipDis?

ClipDis watches gaming-clip folders, waits for new videos to finish writing, compresses them with bundled FFmpeg, uploads them to Discord through a webhook, and moves successfully uploaded originals into app-managed archive folders.

It is built for people who record Valorant or other games and want a simple way to send videos to Discord without manually compressing, checking file sizes, or dragging files into a channel.

## v1.1.0 Watch-Folder Model

v1.1.0 changes ClipDis from one global watch/archive pair to watch-folder profiles.

Each profile has:

- a friendly name;
- a watch-folder path;
- a stable internal profile ID;
- an automatically derived `ClipDis Uploaded` archive folder;
- an independent **Show Valorant Stats** toggle;
- an optional custom Discord caption.

Example:

```text
D:\Clips\Valorant
  clip-a.mp4
  ClipDis Uploaded\

D:\Clips\Rocket League
  clip-b.mp4
  ClipDis Uploaded\
```

Users do **not** choose a separate uploaded/archive path in v1.1.0. ClipDis derives it as:

```text
<watch folder>\ClipDis Uploaded
```

That directory is app-owned. The watcher excludes it before clip discovery so archived clips cannot be reprocessed or uploaded again.

ClipDis rejects duplicate or nested/overlapping watch roots because a physical clip must have one unambiguous owning profile.

## Features

| Feature | What It Does |
| --- | --- |
| Multiple watch folders | Supports independent watch-folder profiles for different games/recorders. |
| Automatic archive folders | Each profile archives successful originals into its own `ClipDis Uploaded` directory. |
| FFmpeg compression | Uses bundled FFmpeg, so normal users do not need a separate FFmpeg install. |
| Discord webhook upload | Uploads clips directly to your chosen Discord channel. |
| Per-profile captions | A watch folder can optionally prepend custom text such as `Rocket League` to its Discord clip post. |
| Per-profile Valorant metadata | Shared Riot/Henrik credentials can be enabled only for the watch folders that should show Valorant rank/level. |
| Manual upload | Upload one clip or selected clips from the dashboard. |
| Auto Upload | Automatically processes eligible clips until none remain. |
| Thumbnail previews | Shows clip thumbnails in the dashboard grid. |
| Tray behavior | Runs quietly in the Windows system tray; closing the window hides it. |
| Persistent settings | Saves watch profiles, options, and durable job state locally. |
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

1. Go to the [ClipDis v1.1.0 release](https://github.com/Hermann-33/ClipDis/releases/tag/v1.1.0).
2. Download `ClipDis-v1.1.0-windows-x64.zip`.
3. Extract the **entire** ZIP into a normal folder.
4. Open the extracted folder.
5. Run `ClipDis.exe`.
6. Keep `_internal` beside `ClipDis.exe`.

> **Important:** `_internal` contains the packaged runtime, QML files, icons, and bundled FFmpeg. If you delete or move `_internal`, ClipDis will not run correctly.

The release also includes `SHA256SUMS.txt` so the downloaded ZIP can be checksum-verified.

## First-Time Setup

1. Open ClipDis.
2. Open **Settings**.
3. Click **Add Watch Folder** and choose the folder where your recorder saves clips.
4. Add more watch folders when needed.
5. Give profiles useful names such as `Valorant`, `Rocket League`, or `Fortnite`.
6. Paste your Discord webhook URL once in the global configuration.
7. Configure Riot/Henrik credentials only if you want Valorant metadata.
8. On each watch profile, choose whether Valorant stats should be shown.
9. Optionally enable a profile caption and enter text such as `Rocket League`.
10. Test your configuration and perform one manual upload before relying on unattended Auto Upload.

There is no separate Uploaded Folder picker. Each profile automatically owns:

```text
<watch folder>\ClipDis Uploaded
```

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
12. Save your settings and use the webhook test before uploading clips.

> **Keep your webhook private.** Anyone with the webhook URL can post into that Discord channel. If it leaks, delete/regenerate the webhook in Discord and update ClipDis.

## Auto Upload

With multiple watch folders, discovery is conceptually:

```text
scan profile A + profile B + ...
        |
        v
one durable ClipDis job queue
        |
        v
ready check -> compress -> upload -> archive into owning profile
```

ClipDis deliberately retains one global processing/upload/archive pipeline rather than spawning one FFmpeg pipeline per watch folder.

Safety rules:

- originals move only after Discord confirms upload success;
- each job records the profile that discovered it;
- a successful clip archives only into its owning profile's `ClipDis Uploaded` directory;
- archive subtrees are excluded from scanning;
- failed clips are not blindly retried forever;
- one missing watch folder does not stop other valid profiles;
- manually selected upload operations remain limited to the selected jobs.

## Per-Profile Captions

A profile can optionally include a custom caption with every clip posted from that source.

Example profile:

```text
Name: Rocket League
Caption enabled: Yes
Caption: Rocket League
Valorant stats: No
```

The Discord post can contain:

```text
Rocket League
<video attachment>
```

If both a caption and Valorant stats are enabled, ClipDis formats them as separate sections.

User captions are sent with Discord mentions disabled, so text such as `@everyone` is displayed as text rather than generating a broad mention through ClipDis.

## Optional Valorant Stats

Riot/Henrik identity is global, while **whether to include rank/level is per watch-folder profile**.

Global values:

- Riot username;
- Riot tagline;
- Valorant region;
- HenrikDev API key.

A profile with **Show Valorant Stats** off performs no Henrik lookup for that upload.

A profile with the option on requests stats using the shared credentials. Stats remain optional: if HenrikDev is unavailable, the clip upload is allowed to continue.

HenrikDev API keys are obtained through HenrikDev's system/community. Start from the HenrikDev Discord server:

**https://discord.gg/U2V8p6g2r**

Do not share your HenrikDev API key publicly.

## Archive And Clear Behavior

Each watch profile uses its own archive:

```text
<watch root>\ClipDis Uploaded
```

ClipDis supports:

- opening a profile's watch directory;
- opening/creating its `ClipDis Uploaded` directory;
- previewing how many archived files and bytes would be cleared;
- clearing one selected profile archive;
- clearing all profile archives.

Destructive clear operations are profile-scoped. The UI does not pass arbitrary filesystem deletion paths to the backend.

ClipDis deletes only safe regular top-level files in the expected app-owned archive directory. Unexpected directories/links are skipped instead of being recursively erased.

## v1.0.0 -> v1.1.0 Migration

Configuration schema v2 is introduced automatically.

For an existing installation:

- the legacy watch folder is converted into one watch-folder profile;
- its old Valorant enable flag becomes that profile's `show_valorant_stats` value;
- caption defaults to off;
- a one-time `config.v1.backup.json` is created before migration;
- the old configured uploaded folder and its contents are left untouched;
- new successful uploads use `<watch root>\ClipDis Uploaded`;
- `%APPDATA%\ValorantClipUploader` remains the persistence namespace so existing settings/state are not reset by a cosmetic path rename.

## Privacy And Security

- Discord webhook URLs are stored locally and redacted in the UI where possible.
- HenrikDev API keys are stored locally and redacted in the UI where possible.
- Treat a Discord webhook like a password because it can post into your channel.
- Do not commit or share webhook URLs or API keys.
- Logs and diagnostics are intended to redact secrets.
- Profile captions are ordinary local configuration, not credentials.
- Destructive archive clearing derives paths from trusted profile configuration rather than accepting arbitrary paths from QML.
- If you accidentally share a webhook or API key, rotate it immediately.

## Updating ClipDis

1. Download the newer release ZIP from the [Releases page](https://github.com/Hermann-33/ClipDis/releases).
2. Extract it into a fresh folder.
3. Run the new `ClipDis.exe`.
4. Keep `_internal` with the EXE.
5. Existing settings should remain because they are stored in your Windows user data.

Avoid mixing random files from old and new builds. Extract the new ZIP cleanly.

## Troubleshooting

| Problem | What To Try |
| --- | --- |
| App does not open | Make sure `ClipDis.exe` is still next to `_internal`. Try extracting the ZIP again. |
| Windows warns about unknown publisher | This can happen with unsigned apps. Only run builds downloaded from the official GitHub Releases page. |
| Discord upload fails | Re-test your webhook, check the channel still exists, and confirm the file is not too large. |
| Webhook test fails | Create a fresh Discord webhook and paste the new URL into Settings. |
| Clips do not appear | Confirm the correct watch profile points to the folder where your recorder saves `.mp4` clips. |
| One game folder is missing | That profile should report missing; other valid watch folders should continue scanning. |
| An archived clip appears as new | `ClipDis Uploaded` should always be excluded from scanning. Stop Auto Upload and report the issue before processing more clips. |
| Thumbnails do not load | Give ClipDis a few seconds. If needed, restart once and check that bundled FFmpeg is present. |
| Upload is too large | Lower the max upload size setting or use shorter clips. Discord limits depend on your server/account. |
| Auto Upload does nothing | First confirm manual upload works, then ensure Auto Upload is on and the clip is not already failed. |
| Valorant stats unavailable | Check Riot name, tagline, region, HenrikDev API key, and that the source profile has stats enabled. Clip upload can still work without stats. |
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

Regression suite:

```powershell
python -m unittest discover -s tests -v
```

Useful checks:

```powershell
python -m compileall main.py app tests
python main.py --smoke-check
python main.py --qml-smoke-check
python main.py --diagnose
```

Release packaging uses:

```powershell
cmd /c build.bat release
```

The source code is separate from the release ZIP. Do not commit `dist/`, `dist_release/`, release ZIP files, logs, databases, local config, or secrets.

For v1.1.0 architecture, implementation decisions, migration details, safety requirements and verification results, read:

```text
docs/V1.1.0_MULTI_WATCH_DESIGN.md
```
