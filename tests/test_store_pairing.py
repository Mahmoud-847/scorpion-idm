"""Automatic pairing of the official store extension with the Store edition, through the real local bridge."""
import json
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "native_app"))
import scorpion_qt as sq  # noqa: E402

TOKEN = "c" * 64
OFFICIAL = f"chrome-extension://{sq.OFFICIAL_EXTENSION_ID}"
OTHER = "chrome-extension://" + "a" * 32


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_bridge(store: bool):
    engine = sq.ScorpionNativeEngine.__new__(sq.ScorpionNativeEngine)
    engine.rpc_port = free_port()
    engine.bridge_token = TOKEN
    engine.lock = threading.RLock()
    engine.settings = {"lang": "en"}
    engine.downloads = {}
    engine.controllers = {}
    with patch.object(sq, "is_msix_packaged", return_value=store):
        threading.Thread(target=engine._start_browser_rpc_bridge, daemon=True).start()
        for _ in range(100):
            if getattr(engine, "rpc_alive", False):
                break
            time.sleep(0.02)
    return engine


def pair(port, origin, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/pair", data=data, method="POST", headers={
        "Origin": origin, "X-Scorpion-Client": "1", "Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=3) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        return err.code, None


class StorePairingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = start_bridge(store=True)
        cls.exe = start_bridge(store=False)

    def test_official_extension_pairs_without_a_code(self):
        status, body = pair(self.store.rpc_port, OFFICIAL, {"auto": True})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True, "token": TOKEN})

    def test_edge_style_extension_origin_is_accepted_too(self):
        status, body = pair(self.store.rpc_port, f"extension://{sq.OFFICIAL_EXTENSION_ID}", {"auto": True})
        self.assertEqual(status, 200)

    def test_other_extensions_and_web_pages_cannot_auto_pair(self):
        for origin in (OTHER, "https://evil.test", "", f"{OFFICIAL}.evil.test"):
            status, body = pair(self.store.rpc_port, origin, {"auto": True})
            self.assertEqual(status, 403, origin)
            self.assertIsNone(body)

    def test_auto_must_be_exactly_true(self):
        for value in ("true", 1, None):
            status, _ = pair(self.store.rpc_port, OFFICIAL, {"auto": value})
            self.assertEqual(status, 403, value)

    def test_regular_exe_build_has_no_pairing_endpoint(self):
        status, body = pair(self.exe.rpc_port, OFFICIAL, {"auto": True})
        self.assertNotEqual(status, 200)
        self.assertIsNone(body)


if __name__ == "__main__":
    unittest.main()
