# -*- coding: utf-8 -*-
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "native_app"))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

import scorpion_qt as sq


_QAPP = QApplication.instance() or QApplication([])


def _build_test_window(tmp_dir: Path):
    dl_root = tmp_dir / "downloads"
    temp_root = tmp_dir / "temp"
    dl_root.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    sf = tmp_dir / "scorpion_native_state.json"

    def fake_engine_init(self):
        self.signals = sq.EngineSignals()
        self.project_root = sq.RESOURCE_ROOT
        self.ext_source_dir = str(ROOT / "browser-extension")
        self.app_data = str(tmp_dir)
        self.legacy_prog_ext_dir = str(tmp_dir / "leg_ext")
        self.appdata_ext_dir = str(tmp_dir / "app_ext")
        self.temp_root = str(temp_root)
        self.default_dl_root = str(dl_root)
        self.state_file = str(sf)
        self.rpc_port = 19615
        self.rpc_alive = True
        self.last_ext_seen = {}
        self.settings = {
            "defaultConnections": 32,
            "globalSpeedLimitKbps": 0,
            "clipboardMonitor": False,
            "autoStartFromBrowser": True,
            "downloadsRoot": str(dl_root),
            "userAgent": "ScorpionIDM/Test",
            "connectedBrowsers": ["chrome"],
            "wizardShownOnce": True,
            "maxConcurrent": 4,
            "schedEnabled": False,
            "schedTime": "02:00",
            "schedLastFired": "",
            "startWithWindows": False,
            "associateTorrents": False,
            "autoCheckUpdates": False,
            "updateUrl": "",
            "lastSeenVersion": sq.APP_VERSION,
            "lang": "ar",
            "theme": "dark",
            "onStartShow": "card",
            "progressDetailsOpen": False,
        }
        self.total_speed = 0
        self.downloads = {}
        self.controllers = {}
        self._recent_captures = {}
        self.lock = threading.RLock()

    orig_card_init = sq.DownloadCard.__init__

    def offscreen_card_init(card_self, dl_id: str, is_ar: bool):
        orig_card_init(card_self, dl_id, is_ar)
        card_self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

    with patch.object(sq.ScorpionNativeEngine, "__init__", fake_engine_init), \
         patch.object(sq.QSystemTrayIcon, "isSystemTrayAvailable", return_value=False), \
         patch.object(sq, "apply_shell_integration"):
        win = sq.ScorpionMainWindow(_QAPP)

    win.timer.stop()
    win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    win.show()
    _QAPP.processEvents()
    return win, offscreen_card_init


class DesktopUIRuntimeTests(unittest.TestCase):
    def test_browser_capture_immediately_reveals_download_despite_active_filters(self):
        with tempfile.TemporaryDirectory(prefix="scorpion_ui_rt_") as tmp:
            win, _ = _build_test_window(Path(tmp))
            try:
                now_ms = int(time.time() * 1000)
                win.engine.downloads["old-vid"] = {
                    "id": "old-vid",
                    "url": "https://example.com/movie.mp4",
                    "filename": "movie.mp4",
                    "category": "Video",
                    "saveDir": str(Path(tmp) / "downloads" / "Video"),
                    "filePath": str(Path(tmp) / "downloads" / "Video" / "movie.mp4"),
                    "tempFilePath": str(Path(tmp) / "temp" / "old-vid.part"),
                    "totalSize": 10_000_000,
                    "downloadedBytes": 10_000_000,
                    "progress": 100.0,
                    "speed": 0,
                    "timeLeft": 0,
                    "status": "completed",
                    "createdAt": now_ms - 5000,
                }
                win.filter_state = "completed"
                win.filter_cat = "Video"
                win.txt_search.setText("nonexistent_filter_text")
                win.refresh_all()
                self.assertEqual(win.stack.currentIndex(), 1)
                self.assertEqual(win.table.rowCount(), 0)

                def fake_start(dl_id):
                    win.engine.downloads[dl_id].update(status="downloading", phase="connecting")

                with patch.object(win.engine, "start_download", side_effect=fake_start):
                    win.on_browser_captured({
                        "url": "https://portal.example.com/api/export?type=EXCEL",
                        "filename": "تقرير_المبيعات_2026.xlsx",
                        "totalSize": 420_000,
                        "type": "file",
                    })
                _QAPP.processEvents()

                self.assertEqual(win.filter_state, "all")
                self.assertEqual(win.filter_cat, "ALL")
                self.assertEqual(win.txt_search.text(), "")
                self.assertEqual(win.stack.currentIndex(), 0)
                self.assertEqual(win.table.rowCount(), 2)
                row0_cell = win.table.item(0, 0)
                self.assertEqual(row0_cell.data(sq.ROLE_RAW_NAME), "تقرير_المبيعات_2026.xlsx")
                self.assertEqual(win.table.currentRow(), 0)
            finally:
                win.cards.clear()
                win._really_quit = True
                win.close()
                _QAPP.processEvents()

    def test_cancel_confirmation_hides_card_before_topmost_modal_and_handles_both_choices(self):
        with tempfile.TemporaryDirectory(prefix="scorpion_ui_card_") as tmp:
            win, offscreen_card_init = _build_test_window(Path(tmp))
            try:
                with patch.object(sq.DownloadCard, "__init__", offscreen_card_init):
                    dl_id = "dl-cancel-test"
                    win.engine.downloads[dl_id] = {
                        "id": dl_id,
                        "url": "https://example.com/archive.zip",
                        "filename": "archive.zip",
                        "category": "Compressed",
                        "saveDir": str(Path(tmp) / "downloads" / "Compressed"),
                        "filePath": str(Path(tmp) / "downloads" / "Compressed" / "archive.zip"),
                        "tempFilePath": str(Path(tmp) / "temp" / "archive.part"),
                        "totalSize": 5_000_000,
                        "downloadedBytes": 512_000,
                        "progress": 10.2,
                        "speed": 100_000,
                        "timeLeft": 45,
                        "status": "downloading",
                        "createdAt": int(time.time() * 1000),
                    }
                    win.refresh_all()
                    win.show_download_started(dl_id)
                    _QAPP.processEvents()

                    card = win.cards.cards[dl_id]
                    self.assertTrue(card.isVisible())

                    observed = []

                    def mock_exec_factory(choose_yes: bool):
                        def _mock_exec(box_self):
                            observed.append({
                                "card_visible": card.isVisible(),
                                "topmost": bool(box_self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint),
                                "parent": box_self.parent(),
                            })
                            target_role = QMessageBox.ButtonRole.YesRole if choose_yes else QMessageBox.ButtonRole.NoRole
                            for b in box_self.buttons():
                                if box_self.buttonRole(b) == target_role:
                                    b.click()
                                    break
                            return 1

                        return _mock_exec

                    # 1) User keeps download: card hides while modal is open, then restores cleanly
                    with patch.object(QMessageBox, "exec", mock_exec_factory(False)):
                        win.cards._on_action(dl_id, "cancel")
                    _QAPP.processEvents()
                    self.assertEqual(len(observed), 1)
                    self.assertFalse(observed[0]["card_visible"])
                    self.assertTrue(observed[0]["topmost"])
                    self.assertIsNone(observed[0]["parent"])
                    self.assertTrue(card.isVisible())
                    self.assertIn(dl_id, win.engine.downloads)

                    # 2) User confirms cancel: card and download are removed and table updates immediately
                    with patch.object(QMessageBox, "exec", mock_exec_factory(True)):
                        win.cards._on_action(dl_id, "cancel")
                    _QAPP.processEvents()
                    self.assertEqual(len(observed), 2)
                    self.assertFalse(observed[1]["card_visible"])
                    self.assertNotIn(dl_id, win.engine.downloads)
                    self.assertEqual(win.table.rowCount(), 0)
            finally:
                win.cards.clear()
                win._really_quit = True
                win.close()
                _QAPP.processEvents()

    def test_refresh_all_handles_null_fields_safely(self):
        with tempfile.TemporaryDirectory(prefix="scorpion_ui_null_") as tmp:
            win, _ = _build_test_window(Path(tmp))
            try:
                win.engine.downloads["dl-null"] = {
                    "id": "dl-null",
                    "url": "https://example.com/file.bin",
                    "filename": "file.bin",
                    "category": None,
                    "saveDir": str(Path(tmp) / "downloads" / "General"),
                    "filePath": str(Path(tmp) / "downloads" / "General" / "file.bin"),
                    "tempFilePath": str(Path(tmp) / "temp" / "dl-null.part"),
                    "totalSize": None,
                    "downloadedBytes": None,
                    "progress": None,
                    "speed": None,
                    "timeLeft": None,
                    "status": "downloading",
                    "createdAt": None,
                }
                win.refresh_all()
                self.assertEqual(win.stack.currentIndex(), 0)
                self.assertEqual(win.table.rowCount(), 1)
            finally:
                win.cards.clear()
                win._really_quit = True
                win.close()
                _QAPP.processEvents()


if __name__ == "__main__":
    unittest.main()
