import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "native_app"))
import auto_publish
import scorpion_qt


class PublisherStartupTests(unittest.TestCase):
    def test_installer_links_follow_the_new_release_without_counting_as_a_source_change(self):
        folder = Path(tempfile.mkdtemp())
        page = folder / "browser-extension" / "popup.html"
        page.parent.mkdir(parents=True)
        old = '<a href="https://example.test/releases/download/v2.1.30/Scorpion-Setup-2.1.30.exe">Get</a>\r\n'
        page.write_bytes(old.encode("utf-8"))
        before = auto_publish._snapshot_digest(str(page), page.read_bytes())
        with patch.object(auto_publish, "PROJECT_ROOT", str(folder)):
            changed = auto_publish.update_installer_links("2.1.31")
        self.assertEqual(changed, ["browser-extension/popup.html"])
        text = page.read_bytes().decode("utf-8")
        self.assertIn("releases/download/v2.1.31/Scorpion-Setup-2.1.31.exe", text)
        self.assertTrue(text.endswith("\r\n"))  # line endings kept
        self.assertEqual(auto_publish._snapshot_digest(str(page), page.read_bytes()), before)

    def test_update_notes_users_read_have_no_developer_terms(self):
        import re

        banned = re.compile(r"github|\.json|\.py\b|docs/|git |thread|token|etag|last-modified|hostonly|native messaging|"
                            r"bridge|snapshot|sha-?256|refresh_all|dialog\b|cookie policy|\bapi\b", re.I)
        for entry in scorpion_qt.CHANGELOG_HISTORY:
            if tuple(int(p) for p in entry["version"].split(".")) < (2, 1, 16):
                continue
            for line in [entry["title_ar"], entry["title_en"], *entry["ar"], *entry["en"]]:
                self.assertIsNone(banned.search(line), f'{entry["version"]}: {line}')
            self.assertNotIn("تحسينات وإصلاحات عامة", " ".join(entry["ar"]), entry["version"])

    def test_release_notes_come_from_the_changelog(self):
        notes = auto_publish.read_release_notes(scorpion_qt.CHANGELOG_HISTORY[0]["version"])
        self.assertTrue(notes.startswith("- "))

    def test_headless_environment_does_not_leak_to_desktop_app(self):
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen", "SCORPION_TEST_VALUE": "kept"}):
            env = auto_publish.desktop_app_environment()
        self.assertFalse(any(key.upper() == "QT_QPA_PLATFORM" for key in env))
        self.assertEqual(env["SCORPION_TEST_VALUE"], "kept")

    def test_publisher_rejects_an_invisible_offscreen_app(self):
        status = {"version": "2.1.14", "uiReady": True, "uiVisible": True, "uiPlatform": "offscreen"}
        with patch.object(auto_publish.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(status).encode())), \
             patch.object(auto_publish.time, "sleep"):
            with self.assertRaises(RuntimeError):
                auto_publish.wait_for_desktop_app("2.1.14", timeout=0.01)

    def test_publisher_accepts_only_the_expected_visible_windows_app(self):
        status = {"version": "2.1.14", "uiReady": True, "uiVisible": True, "uiPlatform": "windows"}
        with patch.object(auto_publish.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(status).encode())):
            auto_publish.wait_for_desktop_app("2.1.14", timeout=0.1)

    def test_embedded_launcher_preserves_application_arguments(self):
        class ExitProbe(Exception):
            pass
        for arguments in ([], ["--tray"], ["magnet:?xt=urn:btih:example"], ["C:/Downloads/example.torrent"]):
            with self.subTest(arguments=arguments), \
                 patch.object(sys, "executable", "C:/ScorpionIDM/ScorpionIDM.exe"), \
                 patch.object(sys, "orig_argv", ["ScorpionIDM.exe", *arguments]), \
                 patch.object(sys, "argv", list(sys.argv)), \
                 patch.object(runpy, "run_path") as launch, \
                 patch.object(os, "_exit", side_effect=ExitProbe):
                with self.assertRaises(ExitProbe):
                    launcher = ROOT / "native_app/sitecustomize.py"
                    exec(compile(launcher.read_text(encoding="utf-8"), str(launcher), "exec"), {"__file__": str(launcher)})
                launch.assert_called_once()
                self.assertEqual(sys.argv[1:], arguments)

    def test_python_diagnostic_invocations_do_not_launch_the_app(self):
        launcher = ROOT / "native_app/sitecustomize.py"
        for arguments in (["-c", "print(1)"], ["diagnostic.py"]):
            with patch.object(sys, "executable", "C:/ScorpionIDM/ScorpionIDM.exe"), \
                 patch.object(sys, "orig_argv", ["ScorpionIDM.exe", *arguments]), \
                 patch.object(runpy, "run_path") as launch, patch.object(os, "_exit") as terminate:
                exec(compile(launcher.read_text(encoding="utf-8"), str(launcher), "exec"), {"__file__": str(launcher)})
                launch.assert_not_called()
                terminate.assert_not_called()

    def test_edge_browser_wizard_points_to_official_store(self):
        self.assertEqual(scorpion_qt.EDGE_STORE_CRX_ID, "hgcdbjpjlfgnejhceobphikeebmhmgcj")
        self.assertEqual(
            scorpion_qt.EDGE_STORE_URL,
            "https://microsoftedge.microsoft.com/addons/detail/hgcdbjpjlfgnejhceobphikeebmhmgcj",
        )
        by_key = {key: url for key, _name, url, _accent in scorpion_qt.BROWSER_SPECS}
        self.assertEqual(by_key["msedge"], scorpion_qt.EDGE_STORE_URL)
        self.assertEqual(by_key["chrome"], "chrome://extensions")
        self.assertEqual(by_key["brave"], "brave://extensions")

    def test_edge_store_extension_detection_across_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(scorpion_qt.is_edge_store_extension_installed(tmp))
            crx_root = Path(tmp) / "Profile 2" / "Extensions" / scorpion_qt.EDGE_STORE_CRX_ID
            crx_root.mkdir(parents=True)
            self.assertFalse(scorpion_qt.is_edge_store_extension_installed(tmp))
            (crx_root / "1.8.6_0").mkdir()
            self.assertTrue(scorpion_qt.is_edge_store_extension_installed(tmp))

    def test_current_desktop_name_returns_non_empty_string(self):
        name = auto_publish.current_desktop_name()
        self.assertIsInstance(name, str)
        self.assertTrue(len(name.strip()) > 0)


if __name__ == "__main__":
    unittest.main()
