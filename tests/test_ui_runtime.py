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

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
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
    def test_review_milestone_counts_only_unique_completed_public_browser_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            win, _ = _build_test_window(Path(tmp))
            try:
                with patch.object(win.cards, 'show_for'), patch.object(win.engine, 'save_state') as save:
                    for dl_id, status, browser, private in (
                        ('manual', 'completed', False, False), ('queued', 'queued', True, False),
                        ('private', 'completed', True, True), ('first', 'completed', True, False),
                        ('first', 'completed', True, False), ('second', 'completed', True, False),
                        ('third', 'completed', True, False), ('fourth', 'completed', True, False),
                    ):
                        win.engine.downloads[dl_id] = {'status': status, 'fromBrowser': browser, 'incognito': private}
                        win.on_download_completed(dl_id)
                self.assertEqual(win.engine.settings['extensionCompletedIds'], ['first', 'second', 'third'])
                self.assertEqual(save.call_count, 3)
            finally:
                win.engine.downloads.clear()
                win.cards.clear()
                win._really_quit = True
                win.close()
                _QAPP.processEvents()

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

    def test_brand_icon_card_states_inline_torrent_selection_rtl_and_card_dismiss(self):
        import types

        ico = sq.scorpion_emblem_icon()
        self.assertFalse(ico.isNull())
        for px in (16, 32, 64, 128):
            self.assertFalse(ico.pixmap(px, px).isNull())

        with tempfile.TemporaryDirectory(prefix="scorpion_ui_states_") as tmp:
            win, offscreen_card_init = _build_test_window(Path(tmp))
            try:
                now_ms = int(time.time() * 1000)
                win.engine.apply_torrent_selection = types.MethodType(sq.ScorpionNativeEngine.apply_torrent_selection, win.engine)
                win.engine.save_state = lambda: None
                win.engine.start_download = lambda _id: None
                win.engine.downloads = {
                    "dl-active": {
                        "id": "dl-active",
                        "url": "https://example.test/video.mp4",
                        "filename": "Epic Cinematic Trailer (4K).mp4",
                        "category": "Video",
                        "totalSize": 1_200_000_000,
                        "downloadedBytes": 540_000_000,
                        "progress": 45.0,
                        "speed": 18_500_000,
                        "timeLeft": 42,
                        "connections": 16,
                        "status": "downloading",
                        "createdAt": now_ms,
                    },
                    "dl-tor": {
                        "id": "dl-tor",
                        "url": "magnet:?xt=urn:btih:0123456789abcdef",
                        "filename": "Ubuntu-24.04-desktop.iso",
                        "category": "Programs",
                        "isTorrent": True,
                        "torrentPeers": 3,
                        "totalSize": 4_100_000_000,
                        "downloadedBytes": 3_608_000_000,
                        "progress": 88.0,
                        "speed": 12_400_000,
                        "torrentFiles": [
                            {"index": 1, "path": "ubuntu/desktop.iso", "length": 4_000_000_000},
                            {"index": 2, "path": "ubuntu/SHA256SUMS", "length": 100_000_000},
                        ],
                        "torrentSelection": [1, 2],
                        "status": "downloading",
                        "createdAt": now_ms - 1000,
                    },
                    "dl-paused-ok": {
                        "id": "dl-paused-ok",
                        "url": "https://example.test/patch.zip",
                        "filename": "Game_Update_Patch.zip",
                        "category": "Compressed",
                        "supportsRange": True,
                        "totalSize": 8_400_000_000,
                        "downloadedBytes": 0,
                        "progress": 0.0,
                        "status": "paused",
                        "createdAt": now_ms - 2000,
                    },
                    "dl-paused-no": {
                        "id": "dl-paused-no",
                        "url": "https://example.test/stream.bin",
                        "filename": "stream.bin",
                        "category": "General",
                        "browserTransfer": True,
                        "supportsRange": False,
                        "totalSize": 100_000,
                        "downloadedBytes": 50_000,
                        "progress": 50.0,
                        "status": "paused",
                        "createdAt": now_ms - 2500,
                    },
                    "dl-queued": {
                        "id": "dl-queued",
                        "url": "https://example.test/queue.exe",
                        "filename": "installer.exe",
                        "category": "Programs",
                        "totalSize": 50_000_000,
                        "downloadedBytes": 0,
                        "progress": 0.0,
                        "status": "queued",
                        "createdAt": now_ms - 3000,
                    },
                    "dl-done": {
                        "id": "dl-done",
                        "url": "https://example.test/report.pdf",
                        "filename": "Report_Q3_Draft.pdf",
                        "category": "Documents",
                        "totalSize": 14_200_000,
                        "downloadedBytes": 14_200_000,
                        "progress": 100.0,
                        "status": "completed",
                        "createdAt": now_ms - 4000,
                    },
                    "dl-err": {
                        "id": "dl-err",
                        "url": "https://www.netflix.com/watch/123",
                        "filename": "protected.mp4",
                        "category": "Video",
                        "errorMsg": "DRM",
                        "status": "error",
                        "createdAt": now_ms - 5000,
                    },
                }

                # Check RTL default vs EN LTR toggle
                self.assertEqual(win.layoutDirection(), Qt.LayoutDirection.RightToLeft)
                win.lang = "en"
                win.apply_theme_and_lang()
                self.assertEqual(win.layoutDirection(), Qt.LayoutDirection.LeftToRight)
                self.assertEqual(win.table.rowCount(), 7)

                metas = {
                    win.table.item(r, 0).data(sq.ROLE_ID): win.table.item(r, 0).data(sq.ROLE_CARD_META)
                    for r in range(win.table.rowCount())
                }
                self.assertEqual(metas["dl-paused-ok"]["statsLine"], "Paused (Resume supported)")
                self.assertIn("Restart required", metas["dl-paused-no"]["statsLine"])
                self.assertEqual(metas["dl-queued"]["statsLine"], "Queued")
                self.assertEqual(metas["dl-done"]["statsLine"], "100%")
                self.assertIn("Restart in browser", metas["dl-err"]["statsLine"])

                # Expand inline torrent panel, uncheck file #2, apply selection
                win._on_card_action("dl-tor", "toggle_torrent")
                _QAPP.processEvents()
                self.assertIn("dl-tor", win._expanded_torrents)
                panel = win._expanded_panels.get("dl-tor")
                self.assertIsNotNone(panel)
                panel._preview_checks[2].setChecked(False)
                panel.btn_apply.click()
                _QAPP.processEvents()
                self.assertEqual(win.engine.downloads["dl-tor"]["torrentSelection"], [1])

                # Sidebar category filtering: Torrents & Queues
                win.on_tree_clicked(win.nav_items["Torrents"])
                self.assertEqual(win.table.rowCount(), 1)
                self.assertEqual(win.table.item(0, 0).data(sq.ROLE_ID), "dl-tor")

                win.on_tree_clicked(win.nav_items["Queues"])
                self.assertEqual(win.table.rowCount(), 1)
                self.assertEqual(win.table.item(0, 0).data(sq.ROLE_ID), "dl-queued")

                # Corner card dismiss ('close') hides card without deleting download
                with patch.object(sq.DownloadCard, "__init__", offscreen_card_init):
                    win.show_download_started("dl-active")
                    _QAPP.processEvents()
                    self.assertIn("dl-active", win.cards.cards)
                    win.cards._on_action("dl-active", "close")
                    _QAPP.processEvents()
                    self.assertNotIn("dl-active", win.cards.cards)
                    self.assertIn("dl-active", win.engine.downloads)
            finally:
                win.cards.clear()
                win._really_quit = True
                win.close()
                _QAPP.processEvents()

    def test_card_keyboard_shortcuts_and_unpainted_state_changes(self):
        with tempfile.TemporaryDirectory(prefix="scorpion_ui_keyboard_") as tmp:
            with patch.object(sq.ScorpionMainWindow, "_open_selected_shortcut") as global_enter:
                win, _ = _build_test_window(Path(tmp))
            try:
                win.lang = "en"
                win.engine.downloads = {"keyboard": {
                    "id": "keyboard", "url": "https://example.test/fixture",
                    "filename": "fixture.bin", "category": "General", "status": "downloading",
                    "totalSize": 1000, "downloadedBytes": 500, "progress": 50,
                    "createdAt": int(time.time() * 1000), "speed": 0,
                }}
                win.apply_theme_and_lang()
                win.table.setCurrentCell(0, 0)
                win.table.card_action.disconnect()
                actions = []
                win.table.card_action.connect(lambda did, action: actions.append(action))
                QApplication.setActiveWindow(win)
                win.table.setFocus()
                QTest.qWait(30)
                self.assertIs(QApplication.activeWindow(), win)
                QTest.keyClick(win.table, Qt.Key.Key_Right)
                QTest.keyClick(win.table, Qt.Key.Key_Return)
                self.assertEqual(actions, ["pause"])
                global_enter.assert_not_called()

                # A repaint has not yet replaced the cached active-row buttons.
                self.assertIn("pause", win.table._row_btn_map[0])
                win.engine.downloads["keyboard"]["status"] = "paused"
                win.refresh_all()
                QTest.keyClick(win.table, Qt.Key.Key_Space)
                self.assertEqual(actions, ["pause", "resume"])
                QTest.keyClick(win.table, Qt.Key.Key_Escape)
                self.assertIsNone(win.table._kbd_btn)
            finally:
                win.cards.clear()
                win._really_quit = True
                win.close()
                _QAPP.processEvents()

    def test_card_accessibility_peers_and_keyboard_actions(self):
        with tempfile.TemporaryDirectory(prefix="scorpion_ui_a11y_") as tmp:
            win, _ = _build_test_window(Path(tmp))
            try:
                now_ms = int(time.time() * 1000)
                win.engine.downloads = {
                    "dl-tor": {
                        "id": "dl-tor",
                        "url": "magnet:?xt=urn:btih:1234",
                        "filename": "Ubuntu-24.04-desktop.iso",
                        "category": "Torrent",
                        "isTorrent": True,
                        "peers": 3,
                        "totalSize": 4_100_000_000,
                        "downloadedBytes": 2_050_000_000,
                        "progress": 50.0,
                        "speed": 1_000_000,
                        "status": "downloading",
                        "createdAt": now_ms,
                    },
                }
                win.lang = "en"
                win.apply_theme_and_lang()
                win.table.setCurrentCell(0, 0)
                cell0 = win.table.item(0, 0)
                self.assertIn("Ubuntu-24.04-desktop.iso", cell0.text())
                self.assertIn("Peer:", cell0.text())
                self.assertIn("3", cell0.text())
                self.assertEqual(cell0.data(Qt.ItemDataRole.AccessibleTextRole), cell0.text())
                self.assertIn("Peer:", cell0.data(Qt.ItemDataRole.AccessibleDescriptionRole))
                self.assertIn("3", cell0.data(Qt.ItemDataRole.AccessibleDescriptionRole))
                self.assertIn("keyPressEvent", type(win.table).__dict__)

                emitted = []
                win.table.card_action.connect(lambda dl_id, act: emitted.append((dl_id, act)))
                QApplication.sendEvent(win.table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
                QApplication.sendEvent(win.table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
                QApplication.sendEvent(win.table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
                _QAPP.processEvents()
                self.assertEqual(emitted, [("dl-tor", "pause")])

                QApplication.sendEvent(win.table, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
                self.assertIsNone(win.table._kbd_btn)
            finally:
                win.cards.clear()
                win._really_quit = True
                win.close()
                _QAPP.processEvents()


if __name__ == "__main__":
    unittest.main()
