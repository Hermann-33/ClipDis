from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.archive import archive_uploaded_job
from app.config import (
    AppConfig,
    CONFIG_VERSION,
    UPLOADED_DIR_NAME,
    WatchFolderProfile,
    load_config,
    new_watch_folder_profile,
    profile_uploaded_folder,
    save_config,
    validate_watch_folders,
)
from app.discord_uploader import build_webhook_payload, upload_file_to_webhook, upload_processed_job
from app.secrets import DISCORD_WEBHOOK_KEY
from app.state import StateStore
from app.watch_folders import WatchFolderService
from app.worker import _iter_files


class DummyResponse:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self.headers = {}
        self.text = json.dumps(payload or {"id": "123"})
        self._payload = payload or {"id": "123"}

    def json(self):
        return self._payload


class DummyStats:
    available = True
    category = "success"

    def to_payload(self):
        return {
            "available": True,
            "rank": "Diamond 2",
            "account_level": 145,
            "level": 145,
            "category": "success",
        }


def _same_path(left: str | Path, right: str | Path) -> bool:
    left_value = os.path.normcase(os.path.abspath(str(Path(left).resolve(strict=False))))
    right_value = os.path.normcase(os.path.abspath(str(Path(right).resolve(strict=False))))
    if left_value == right_value:
        return True
    # Windows hosted runners can expose TEMP through an 8.3 alias in one
    # source and a long path in another. samefile resolves both when present.
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


class MultiWatchConfigTests(unittest.TestCase):
    def test_v1_config_migrates_once_and_keeps_stable_profile_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch = root / "Valorant"
            uploaded = root / "Old Uploaded"
            watch.mkdir()
            uploaded.mkdir()
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "watch_folder": str(watch),
                        "uploaded_folder": str(uploaded),
                        "use_henrik_stats": True,
                    }
                ),
                encoding="utf-8",
            )

            first = load_config(config_path)
            self.assertEqual(first.config_version, CONFIG_VERSION)
            self.assertEqual(len(first.watch_folders), 1)
            profile = first.watch_folders[0]
            self.assertTrue(profile.show_valorant_stats)
            self.assertFalse(profile.caption_enabled)
            self.assertEqual(profile.caption_text, "")
            self.assertTrue(_same_path(profile_uploaded_folder(profile), watch / UPLOADED_DIR_NAME))
            self.assertTrue((root / "config.v1.backup.json").is_file())
            self.assertTrue(uploaded.is_dir())

            second = load_config(config_path)
            self.assertEqual(len(second.watch_folders), 1)
            self.assertEqual(second.watch_folders[0].id, profile.id)
            self.assertTrue(uploaded.is_dir())

    def test_duplicate_and_nested_profiles_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "child"
            child.mkdir()
            duplicate_a = new_watch_folder_profile(root, name="A")
            duplicate_b = new_watch_folder_profile(root, name="B")
            issues = validate_watch_folders([duplicate_a, duplicate_b])
            self.assertTrue(any("same directory" in issue.message for issue in issues))

            parent = new_watch_folder_profile(root, name="Parent")
            nested = new_watch_folder_profile(child, name="Nested")
            issues = validate_watch_folders([parent, nested])
            self.assertTrue(any("overlap" in issue.message for issue in issues))


class MultiWatchStateAndWorkerTests(unittest.TestCase):
    def test_job_persists_watch_folder_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = root / "clip.mp4"
            clip.write_bytes(b"clip")
            store = StateStore(root / "state.db")
            job = store.create_or_get_job(clip, "profile-1", root)
            self.assertEqual(job["watch_folder_id"], "profile-1")
            self.assertTrue(_same_path(job["watch_folder_path"], root))

    def test_archive_subtree_is_pruned_before_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / UPLOADED_DIR_NAME
            nested = archive / "nested"
            nested.mkdir(parents=True)
            visible = root / "new.mp4"
            hidden = archive / "old.mp4"
            hidden_nested = nested / "older.mp4"
            visible.write_bytes(b"new")
            hidden.write_bytes(b"old")
            hidden_nested.write_bytes(b"older")

            files = {path.resolve() for path in _iter_files(root, archive)}
            self.assertIn(visible.resolve(), files)
            self.assertNotIn(hidden.resolve(), files)
            self.assertNotIn(hidden_nested.resolve(), files)


class ArchiveAndClearTests(unittest.TestCase):
    def test_profile_archive_destinations_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "A"
            b = root / "B"
            a.mkdir()
            b.mkdir()
            pa = new_watch_folder_profile(a, name="A")
            pb = new_watch_folder_profile(b, name="B")
            config = AppConfig(watch_folders=[pa, pb])

            clip_a = a / "a.mp4"
            clip_b = b / "b.mp4"
            clip_a.write_bytes(b"a")
            clip_b.write_bytes(b"b")
            result_a = archive_uploaded_job(
                {"status": "uploaded", "source_path": str(clip_a), "watch_folder_id": pa.id}, config
            )
            result_b = archive_uploaded_job(
                {"status": "uploaded", "source_path": str(clip_b), "watch_folder_id": pb.id}, config
            )
            self.assertTrue(result_a.ok)
            self.assertTrue(result_b.ok)
            self.assertTrue(_same_path(Path(result_a.archive_path).parent, profile_uploaded_folder(pa)))
            self.assertTrue(_same_path(Path(result_b.archive_path).parent, profile_uploaded_folder(pb)))

    def test_clear_one_does_not_touch_other_profile_and_skips_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "A"
            b = root / "B"
            a.mkdir()
            b.mkdir()
            pa = new_watch_folder_profile(a, name="A")
            pb = new_watch_folder_profile(b, name="B")
            config_path = root / "config.json"
            save_config(AppConfig(watch_folders=[pa, pb]), config_path)
            state = StateStore(root / "state.db")
            service = WatchFolderService(config_path, state)

            archive_a = profile_uploaded_folder(pa)
            archive_b = profile_uploaded_folder(pb)
            archive_a.mkdir()
            archive_b.mkdir()
            file_a = archive_a / "a.mp4"
            file_b = archive_b / "b.mp4"
            unexpected_dir = archive_a / "keep-me"
            unexpected_dir.mkdir()
            (unexpected_dir / "nested.mp4").write_bytes(b"nested")
            file_a.write_bytes(b"aaaa")
            file_b.write_bytes(b"bbbb")

            preview = service.preview_clear_uploaded(pa.id)
            self.assertTrue(preview["ok"])
            self.assertEqual(preview["data"]["fileCount"], 1)
            self.assertEqual(preview["data"]["unexpectedCount"], 1)

            result = service.clear_uploaded(pa.id)
            self.assertTrue(result["ok"])
            self.assertFalse(file_a.exists())
            self.assertTrue(file_b.exists())
            self.assertTrue(unexpected_dir.is_dir())
            self.assertEqual(result["data"]["skipped"], 1)

    def test_profile_removal_is_blocked_by_active_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch = root / "Watch"
            watch.mkdir()
            profile = new_watch_folder_profile(watch, name="Watch")
            config_path = root / "config.json"
            save_config(AppConfig(watch_folders=[profile]), config_path)
            store = StateStore(root / "state.db")
            clip = watch / "clip.mp4"
            clip.write_bytes(b"clip")
            store.create_or_get_job(clip, profile.id, profile.path)
            service = WatchFolderService(config_path, store)
            result = service.remove_profile(profile.id)
            self.assertFalse(result["ok"])
            self.assertIn("active or failed clip jobs", result["message"])

    def test_profile_removal_is_blocked_by_failed_jobs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch = root / "Watch"
            watch.mkdir()
            profile = new_watch_folder_profile(watch, name="Watch")
            config_path = root / "config.json"
            save_config(AppConfig(watch_folders=[profile]), config_path)
            store = StateStore(root / "state.db")
            clip = watch / "clip.mp4"
            clip.write_bytes(b"clip")
            job = store.create_or_get_job(clip, profile.id, profile.path)
            store.mark_failed(int(job["id"]), "test_failure", "intentional test failure")
            service = WatchFolderService(config_path, store)
            result = service.remove_profile(profile.id)
            self.assertFalse(result["ok"])
            self.assertIn("active or failed clip jobs", result["message"])


class DiscordProfileTests(unittest.TestCase):
    def test_caption_and_stats_are_combined_in_order(self):
        profile = WatchFolderProfile(
            id="p1",
            name="Rocket League",
            path="C:/Clips/RocketLeague",
            show_valorant_stats=True,
            caption_enabled=True,
            caption_text="Rocket League",
        )
        config = AppConfig(watch_folders=[profile])
        job = {"watch_folder_id": "p1", "source_path": "C:/Clips/RocketLeague/clip.mp4"}
        content = build_webhook_payload(
            job,
            config,
            {"available": True, "rank": "Diamond 2", "account_level": 145},
            profile,
        )
        self.assertEqual(content, "Rocket League\n\nRank: **Diamond 2**\nLevel: **145**")

    def test_stats_disabled_profile_performs_no_henrik_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = root / "clip.mp4"
            clip.write_bytes(b"clip")
            profile = new_watch_folder_profile(root, name="Rocket League", show_valorant_stats=False)
            config = AppConfig(watch_folders=[profile], max_upload_size_mb=8)
            job = {
                "id": 1,
                "watch_folder_id": profile.id,
                "source_path": str(root / "source.mp4"),
                "compressed_path": str(clip),
            }

            def fake_upload(*args, **kwargs):
                return DummyResponse(200)

            with patch("app.discord_uploader.fetch_valorant_stats") as fetch_stats:
                result = upload_processed_job(
                    job,
                    config,
                    secrets={DISCORD_WEBHOOK_KEY: "https://discord.com/api/webhooks/123456/test_token"},
                    upload_func=fake_upload,
                    sleep_func=lambda _: None,
                )
            self.assertTrue(result.ok)
            fetch_stats.assert_not_called()

    def test_stats_enabled_profile_requests_henrik(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = root / "clip.mp4"
            clip.write_bytes(b"clip")
            profile = new_watch_folder_profile(root, name="Valorant", show_valorant_stats=True)
            config = AppConfig(watch_folders=[profile], max_upload_size_mb=8)
            job = {
                "id": 1,
                "watch_folder_id": profile.id,
                "source_path": str(root / "source.mp4"),
                "compressed_path": str(clip),
            }

            def fake_upload(*args, **kwargs):
                return DummyResponse(200)

            with patch("app.discord_uploader.fetch_valorant_stats", return_value=DummyStats()) as fetch_stats:
                result = upload_processed_job(
                    job,
                    config,
                    secrets={DISCORD_WEBHOOK_KEY: "https://discord.com/api/webhooks/123456/test_token"},
                    upload_func=fake_upload,
                    sleep_func=lambda _: None,
                )
            self.assertTrue(result.ok)
            fetch_stats.assert_called_once()

    def test_multipart_payload_disables_mentions(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "clip.mp4"
            clip.write_bytes(b"clip")
            captured = {}

            def fake_post(url, **kwargs):
                captured.update(kwargs)
                return DummyResponse(200)

            with patch("app.discord_uploader.requests.post", side_effect=fake_post):
                response = upload_file_to_webhook(
                    "https://discord.com/api/webhooks/123456/test_token",
                    clip,
                    "@everyone Rocket League",
                    5,
                    True,
                )
            self.assertEqual(response.status_code, 200)
            payload = json.loads(captured["data"]["payload_json"])
            self.assertEqual(payload["allowed_mentions"], {"parse": []})
            self.assertEqual(payload["content"], "@everyone Rocket League")


if __name__ == "__main__":
    unittest.main()
