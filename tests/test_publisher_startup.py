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


if __name__ == "__main__":
    unittest.main()
