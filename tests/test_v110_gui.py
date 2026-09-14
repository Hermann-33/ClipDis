from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QMetaObject, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from app.config import AppConfig, load_config, save_config
from app.gui_bridge import GuiBridge


class GuiProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"APPDATA": str(self.root / "data"), "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"})
        self.env.start()
        save_config(AppConfig(generate_thumbnails_enabled=False))
        self.bridge = GuiBridge()
        self.profiles = []
        for name in ("Valorant", "Rocket League"):
            folder = self.root / name
            folder.mkdir()
            result = self.bridge.addWatchFolder(str(folder))
            self.assertTrue(result["ok"], result)
            self.profiles.append(result["data"])

    def tearDown(self):
        self.bridge._thumbnail_executor.shutdown(wait=True)
        self.env.stop()
        self.temp.cleanup()

    def job(self, index):
        p = self.profiles[index]
        clip = Path(p["path"]) / "clip.mp4"
        clip.write_bytes(b"synthetic fixture")
        return self.bridge._state.create_or_get_job(clip, p["id"], p["path"])

    def test_global_save_preserves_profiles_and_rejects_legacy_path_changes(self):
        self.bridge.saveConfig({"riot_username": "Player", "watch_folders": [], "watch_folder": "wrong"})
        cfg = load_config()
        self.assertEqual([p.id for p in cfg.watch_folders], [p["id"] for p in self.profiles])
        self.assertEqual(cfg.riot_username, "Player")

    def test_dashboard_and_delete_use_second_profile_id(self):
        a, b = self.job(0), self.job(1)
        clips = self.bridge.getDashboardClips()
        self.assertEqual({c["profileName"] for c in clips}, {"Valorant", "Rocket League"})
        self.assertTrue(self.bridge.deleteSelectedClips([b["id"]])["ok"])
        self.assertTrue(Path(a["source_path"]).exists())
        self.assertFalse(Path(b["source_path"]).exists())

    def test_missing_first_profile_does_not_break_second(self):
        Path(self.profiles[0]["path"]).rmdir()
        self.assertTrue(self.bridge.getSetupStatus()["watchFolderOk"])
        self.assertTrue(self.bridge.updateWatchFolder(self.profiles[0]["id"], {"name": "Missing Valorant"})["ok"])

    def test_global_stats_test_forces_enabled_without_mutating_profile(self):
        unavailable = SimpleNamespace(
            available=False, rank=None, account_level=None, message="Credentials incomplete.",
            category="config_missing", rank_category="", level_category="",
        )
        with patch("app.gui_bridge.fetch_valorant_stats", return_value=unavailable) as fetch:
            self.bridge.testValorantStats()
        self.assertTrue(fetch.call_args.args[0].use_henrik_stats)
        self.assertFalse(load_config().watch_folders[0].show_valorant_stats)

    def test_clear_all_reports_safety_failure(self):
        archive = Path(self.profiles[0]["uploadedPath"])
        archive.write_bytes(b"unexpected file instead of folder")
        result = self.bridge.clearAllUploaded()
        self.assertFalse(result["ok"])
        self.assertEqual(result["data"]["failed"], 1)
        self.assertTrue(archive.exists())

    def test_remove_last_profile_persists_empty_configuration(self):
        for p in self.profiles:
            self.assertTrue(self.bridge.removeWatchFolder(p["id"])["ok"])
        self.assertEqual(load_config().watch_folders, [])

    def test_uploaded_job_blocks_removal_until_archived(self):
        job = self.job(0)
        for status in ("queued", "processing", "processed", "uploading", "uploaded"):
            self.bridge._state.transition_job(job["id"], status)
        self.assertFalse(self.bridge.removeWatchFolder(self.profiles[0]["id"])["ok"])

    def test_profile_options_persist_independently(self):
        for p, stats in zip(self.profiles, (True, False)):
            self.assertTrue(self.bridge.updateWatchFolder(p["id"], {
                "show_valorant_stats": stats, "caption_enabled": True, "caption_text": p["name"],
            })["ok"])
        profiles = load_config().watch_folders
        self.assertEqual([p.show_valorant_stats for p in profiles], [True, False])
        self.assertEqual([p.caption_text for p in profiles], ["Valorant", "Rocket League"])

    def test_qml_filter_and_select_all_visible_are_exact(self):
        a, b = self.job(0), self.job(1)
        engine = QQmlApplicationEngine()
        engine.rootContext().setContextProperty("bridge", self.bridge)
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "app/gui/main.qml")))
        self.assertTrue(engine.rootObjects())
        window = engine.rootObjects()[0]
        page = window.findChild(type(self.bridge).__bases__[0], "DashboardPage")
        self.assertIsNotNone(page)
        page.setProperty("filterProfileId", self.profiles[1]["id"])
        self.app.processEvents()
        QMetaObject.invokeMethod(page, "selectAllVisible", Qt.DirectConnection)
        selected = page.property("selectedIds").toVariant()
        self.assertEqual(selected, [b["id"]])
        page.setProperty("filterProfileId", self.profiles[0]["id"])
        self.assertEqual(page.property("selectedIds").toVariant(), [])
        QMetaObject.invokeMethod(page, "selectAllVisible", Qt.DirectConnection)
        self.assertEqual(page.property("selectedIds").toVariant(), [a["id"]])
        window.hide()
        engine.deleteLater()
        self.app.processEvents()
