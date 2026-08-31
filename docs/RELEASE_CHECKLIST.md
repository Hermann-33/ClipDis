# ClipDis Release Checklist

Use this checklist before publishing a Windows release. For v1.1.0, every multi-watch/profile item below is mandatory.

## Automated Gates

- `python -m compileall -q main.py app tests` passes.
- `python -m unittest discover -s tests -v` passes.
- `python main.py --smoke-check` passes.
- `python main.py --qml-smoke-check` passes.
- `python main.py --diagnose` completes without exposing secrets.
- GitHub Actions v1.1 backend regression workflow is green.

## Build

- Debug onedir build succeeds.
- Release onedir build succeeds.
- Release EXE opens with no console.
- Release folder contains `ClipDis.exe` and `_internal`.
- `_internal` includes QML/assets, FFmpeg binaries, FFmpeg license files, and all new v1.1 modules.
- `app/watch_folders.py` is present in the packaged runtime/import graph.
- Do not delete `_internal`.

## Window and Tray

- Dashboard opens on launch.
- Tray icon appears.
- Taskbar, Alt+Tab, Explorer, and tray icons are correct.
- Second launch restores the existing instance instead of creating another tray app.
- Close hides to tray.
- Tray Exit quits.
- Normal window size remains usable.
- Minimum supported window size does not clip profile controls/dialogs.
- Keyboard focus is visible and destructive confirmation is safely cancellable.

## v1.0 -> v1.1 Migration

- A copy/fixture of a v1.0 config migrates to `config_version = 2`.
- Exactly one profile is created from the old watch folder.
- Migrated profile UUID remains stable after restart.
- Legacy Valorant enable flag becomes the migrated profile's stats toggle.
- Caption defaults off/empty.
- `config.v1.backup.json` is created once.
- Existing legacy uploaded-folder contents remain untouched.
- `%APPDATA%\ValorantClipUploader` remains the persistence namespace.
- Existing SQLite jobs remain readable after additive schema migration.

## Watch-Folder Profiles

- Fresh setup clearly explains that no watch folders are configured.
- Add first watch folder succeeds.
- Add second independent watch folder succeeds.
- Profile friendly names persist.
- Duplicate root is rejected.
- Parent/child overlapping roots are rejected in both ordering directions.
- One missing profile is shown as missing without breaking valid profiles.
- All-missing behavior is understandable and recoverable.
- User cannot manually configure an uploaded/archive path.
- Each profile visibly shows/derives `<watch root>\ClipDis Uploaded`.
- Removing a profile does not delete user files.
- Removing a profile with active or failed jobs is blocked with a clear explanation.

## Scanner Safety

- Two valid roots are scanned in one watcher cycle.
- A discovered job stores the correct `watch_folder_id` and `watch_folder_path`.
- `<watch root>\ClipDis Uploaded` is pruned before candidate discovery.
- A clip placed inside `ClipDis Uploaded` never becomes a new job.
- Nested content inside `ClipDis Uploaded` also never becomes a job.
- Multiple watch folders do not spawn multiple unbounded FFmpeg pipelines.

## Settings

- Settings persist after restart.
- Watch folders are managed through a visible profile list/card surface.
- Add/Edit/Remove actions have clear scopes.
- Global Discord webhook configuration remains separate from profile settings.
- Global Riot username/tagline/region/Henrik key remain separate from per-profile stats toggles.
- Profile Valorant Stats toggle persists independently for each profile.
- Profile Caption toggle/text persist independently for each profile.
- Caption character count/limit behavior is understandable.
- Webhook test works with a user-provided webhook.
- Valorant credentials can be tested independently of one particular profile.
- Start with Windows writes/removes the HKCU Run value.

## Dashboard

- Dashboard title/copy no longer implies only one watch folder.
- Each clip exposes its source profile name.
- `All Folders` shows clips from every profile.
- Selecting one profile filters to that profile only.
- `Select All Visible` never selects clips hidden by the current filter.
- Open Folders quick action targets the correct profile watch/archive path.
- Clear Uploaded quick action offers individual profiles and Clear All.
- Empty filtered state is understandable rather than blank/broken.

## Per-Profile Discord Behavior

- Caption OFF sends no profile caption.
- Caption ON sends the correct profile caption.
- Stats OFF performs no Henrik request for that clip.
- Stats ON uses the shared Riot/Henrik credentials.
- Henrik failure does not prevent ordinary clip upload.
- Caption + stats ordering/spacing is correct.
- Final Discord content over 2,000 characters is rejected locally rather than blindly sent.
- Caption text such as `@everyone` is sent with `allowed_mentions.parse = []` and does not create a broad mention.

## Archive Routing

- Profile A upload archives only into `A\ClipDis Uploaded`.
- Profile B upload archives only into `B\ClipDis Uploaded`.
- Filename collision handling still works.
- Original moves only after Discord upload succeeds.
- Failed upload leaves original in its watch folder.
- Archive failure after successful Discord upload preserves truthful uploaded state and leaves media safe.

## Clear Uploaded

- Per-profile preview shows correct profile, path, file count, and bytes.
- Clear profile A deletes A's safe archived files and leaves profile B untouched.
- Clear All clears safe archived files from all configured profile archives.
- Archive directory itself remains after clearing.
- Unexpected subdirectories are skipped, not recursively destroyed.
- Symlink/junction/reparse-point safety checks prevent redirection outside the expected archive.
- QML never passes an arbitrary deletion path to the backend; destructive API scope is profile ID/all-profiles only.
- Confirmation dialog states the exact profile/all-folders scope and consequence.
- Confirmation uses explicit labels such as `Cancel` / `Clear uploaded clips`, not generic Yes/No.

## Pipeline

- Thumbnails load without restart.
- One clip uploads successfully.
- Selected upload remains exact-job only.
- Auto Upload processes eligible clips until none remain.
- Failed clips are not automatically retried forever.
- Existing repeated-failure auto-pause behavior remains functional.

## Computer-Use UX Verification

Using isolated temporary watch roots, operate the packaged Windows build through the actual GUI and verify:

- zero-profile onboarding;
- two-profile setup;
- profile edit/persistence;
- open watch/archive actions;
- profile filter;
- selected-visible behavior;
- per-profile caption/stat controls;
- clear one;
- clear all;
- missing folder behavior;
- confirmation dialogs;
- restart persistence;
- no clipped/overlapping controls at normal/minimum window sizes.

Any defect found here must be fixed, rebuilt, and re-tested before release.

## Security

- No full Discord webhook in logs, diagnostics, screenshots, fixtures, or Git history.
- No Henrik API key in logs, diagnostics, screenshots, fixtures, or Git history.
- No secrets committed to Git.
- No user appdata/config/state bundled into the release.
- No real gaming clips or temporary test roots committed.
- No build artifacts/release ZIP accidentally committed as source.
