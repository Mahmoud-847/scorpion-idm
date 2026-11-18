# -*- coding: utf-8 -*-
import ast
import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "native_app"))
sys.path.insert(0, str(ROOT / "tests"))

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QScrollArea
import requests

import scorpion_qt as sq
import auto_publish
import test_ui_runtime as rt

_REAL_SLEEP = time.sleep


def _make_engine(folder: Path):
    e = sq.ScorpionNativeEngine.__new__(sq.ScorpionNativeEngine)
    e.settings = {
        "downloadsRoot": str(folder / "downloads"),
        "defaultConnections": 1,
        "maxConcurrent": 4,
        "globalSpeedLimitKbps": 0,
        "lang": "en",
        "userAgent": "Scorpion-Test",
    }
    e.app_data = str(folder / "appdata")
    e.temp_root = str(folder / "temp")
    e.state_file = str(folder / "state.json")
    e.default_dl_root = str(folder / "downloads")
    e.downloads = {}
    e.controllers = {}
    e.lock = threading.RLock()
    e.signals = Mock()
    e.rpc_port = 0
    e.rpc_alive = False
    e.last_ext_seen = {}
    e.bridge_token = "test-bridge-token"
    e.save_state = Mock()
    return e


def _wait_download_done(it: dict, timeout: float = 6.0):
    deadline = time.monotonic() + timeout
    while it["status"] in ("downloading", "connecting", "queued") and time.monotonic() < deadline:
        _REAL_SLEEP(0.01)


class AuditFindingsRegressionTests(unittest.TestCase):
    def test_01_cleanup_never_touches_downloads_root_or_save_dir(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            e = _make_engine(root)
            dl_root = Path(e.settings["downloadsRoot"])
            dl_root.mkdir(parents=True, exist_ok=True)
            keep_files = [
                dl_root / "Family-Fragments.mp4",
                dl_root / "other-manager.part",
                dl_root / "unfinished.aria2",
                dl_root / "notes.txt",
            ]
            for p in keep_files:
                p.write_bytes(b"user-data")

            owned_tmp_dir = Path(e.temp_root) / "owned-id"
            orphan_tmp_dir = Path(e.temp_root) / "orphan-id"
            owned_tmp_dir.mkdir(parents=True)
            orphan_tmp_dir.mkdir(parents=True)
            orphan_cookie = Path(e.temp_root) / "cookies_old.txt"
            orphan_cookie.write_text("# Netscape")
            e.downloads["owned-id"] = {
                "id": "owned-id",
                "filePath": str(dl_root / "Family.mp4"),
                "saveDir": str(dl_root),
                "tempFilePath": str(owned_tmp_dir / "Family.mp4.scorpion_part"),
            }
            (dl_root / "Family.mp4.part").write_bytes(b"stray-part-in-save-dir")

            e._sweep_stray_part_files()
            for p in keep_files:
                self.assertTrue(p.exists(), f"{p.name} in downloadsRoot must never be deleted")
            self.assertFalse(orphan_tmp_dir.exists())
            self.assertFalse(orphan_cookie.exists())
            self.assertTrue(owned_tmp_dir.exists())

            e._cleanup_item_temp(e.downloads["owned-id"])
            self.assertFalse(owned_tmp_dir.exists())
            self.assertTrue((dl_root / "Family.mp4.part").exists())

    def test_02_torrent_move_failure_rolls_back_and_marks_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            e = _make_engine(root)
            it = e.add_download({
                "url": "magnet:?xt=urn:btih:testmove",
                "filename": "tor",
                "isTorrent": True,
                "startImmediately": False,
            })
            bt = Path(e.get_item_temp_dir(it["id"])) / "bt"
            bt.mkdir(parents=True)
            f1 = bt / "a.bin"
            f2 = bt / "b.bin"
            f1.write_bytes(b"111")
            f2.write_bytes(b"222")

            real_move = shutil.move
            calls = 0

            def flaky_move(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise PermissionError("destination locked")
                return real_move(src, dst)

            with patch.object(sq.shutil, "move", side_effect=flaky_move):
                with self.assertRaises(RuntimeError):
                    e._move_torrent_output(str(bt), it["saveDir"], [])
            # Rolled back first file to bt dir
            self.assertTrue(f1.exists())
            self.assertTrue(f2.exists())
            self.assertFalse((Path(it["saveDir"]) / "a.bin").exists())

            ctrl = {"aborted": False}
            e.controllers[it["id"]] = ctrl

            class _Proc:
                dead = False
                def poll(self): return 0 if self.dead else None
                def terminate(self): self.dead = True
                def wait(self, **kw): return 0

            def _rpc(_u, json=None, **_kw):
                m = (json or {}).get("method")
                res = {
                    "aria2.getVersion": {"version": "1"},
                    "aria2.addUri": "gid-1",
                    "aria2.changeGlobalOption": "OK",
                    "aria2.tellStatus": {
                        "status": "complete",
                        "totalLength": "6",
                        "completedLength": "6",
                        "downloadSpeed": "0",
                        "bittorrent": {"info": {"name": "a.bin"}},
                        "files": [{"path": str(f1), "selected": "true"}],
                    },
                }.get(m)
                r = Mock()
                r.json.return_value = {"result": res}
                return r

            with patch.object(e, "_find_aria2c", return_value="fake-aria2"), \
                 patch.object(sq.subprocess, "Popen", return_value=_Proc()), \
                 patch.object(sq.requests, "post", side_effect=_rpc), \
                 patch.object(sq.shutil, "move", side_effect=PermissionError("denied")), \
                 patch.object(sq.time, "sleep", return_value=None):
                e._run_torrent_worker(it, ctrl)

            self.assertEqual(it["status"], "error")
            self.assertTrue(f1.exists())
            self.assertFalse(Path(it["filePath"]).exists())
            self.assertFalse(e.signals.completed.emit.called)

    def test_03_custom_save_dir_preserved_through_probe_disposition_and_finalize(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                body = b"hello world!"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Disposition", 'attachment; filename="renamed_no_ext"')
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                e = _make_engine(root)
                custom_dir = root / "my_custom_folder"
                it = e.add_download({
                    "url": f"http://127.0.0.1:{srv.server_port}/raw",
                    "filename": "raw",
                    "totalSize": 12,
                    "connections": 1,
                    "saveDir": str(custom_dir),
                    "customSaveDir": True,
                    "startImmediately": False,
                    "category": "General",
                })
                p = e.probe_url(it["url"])
                e._apply_probe_result_to_item(it, p)
                self.assertEqual(Path(it["saveDir"]).resolve(), custom_dir.resolve())
                e.start_download(it["id"])
                _wait_download_done(it)
                self.assertEqual(it["status"], "completed")
                self.assertEqual(Path(it["filePath"]).parent.resolve(), custom_dir.resolve())
                self.assertFalse(Path(it["filePath"]).is_relative_to(Path(e.settings["downloadsRoot"])))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_04_add_download_does_not_block_qt_thread_during_slow_probe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            e = _make_engine(root)
            fired = []
            QTimer.singleShot(20, lambda: fired.append(True))

            def slow_probe(url, **_kw):
                time.sleep(0.25)
                return {
                    "url": url,
                    "filename": "probed.bin",
                    "totalSize": 4096,
                    "supportsRange": True,
                    "category": "General",
                    "saveDir": str(root / "downloads" / "General"),
                }

            started = time.perf_counter()
            with patch.object(e, "probe_url", side_effect=slow_probe):
                it = e.add_download({"url": "https://example.test/raw", "startImmediately": False})
                elapsed_ms = (time.perf_counter() - started) * 1000
                before_events = bool(fired)
                rt._QAPP.processEvents()
            time.sleep(0.32)
            self.assertLess(elapsed_ms, 80.0)
            self.assertFalse(before_events)
            self.assertEqual(it["totalSize"], 4096)
            self.assertEqual(it["filename"], "probed.bin")

    def test_05_atomic_state_save_concurrent_writers_and_bak_recovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            e = _make_engine(root)
            e.save_state = types.MethodType(sq.ScorpionNativeEngine.save_state, e)
            e._load_state = types.MethodType(sq.ScorpionNativeEngine._load_state, e)
            e.record_diagnostic = types.MethodType(sq.ScorpionNativeEngine.record_diagnostic, e)
            e.get_item_temp_dir = types.MethodType(sq.ScorpionNativeEngine.get_item_temp_dir, e)
            e._sweep_stray_part_files = Mock()

            ready, resume = threading.Event(), threading.Event()
            real_dump = json.dump

            def staggered_dump(obj, fp, **kw):
                if threading.current_thread().name == "first-writer":
                    ready.set()
                    resume.wait(3)
                return real_dump(obj, fp, **kw)

            e.downloads["k1"] = {"id": "k1", "filename": "a.zip", "status": "completed"}
            with patch.object(sq.json, "dump", side_effect=staggered_dump):
                t1 = threading.Thread(name="first-writer", target=e.save_state)
                t1.start()
                self.assertTrue(ready.wait(3))
                e.downloads["k2"] = {"id": "k2", "filename": "b.zip", "status": "completed"}
                e.save_state()
                resume.set()
                t1.join(timeout=3)

            loaded = json.loads(Path(e.state_file).read_text(encoding="utf-8"))
            self.assertEqual({d["id"] for d in loaded["downloads"]}, {"k1", "k2"})
            e.save_state()
            self.assertTrue(Path(e.state_file + ".bak").is_file())

            # Corrupt primary state.json and ensure _load_state recovers from .bak
            Path(e.state_file).write_text("{corrupt", encoding="utf-8")
            e2 = _make_engine(root)
            e2._load_state = types.MethodType(sq.ScorpionNativeEngine._load_state, e2)
            e2.record_diagnostic = types.MethodType(sq.ScorpionNativeEngine.record_diagnostic, e2)
            e2.get_item_temp_dir = types.MethodType(sq.ScorpionNativeEngine.get_item_temp_dir, e2)
            e2._sweep_stray_part_files = Mock()
            e2._load_state()
            self.assertIn("k2", e2.downloads)

    def test_06_tls_certificate_validation_enforced_and_no_verify_false(self):
        for py_path in (ROOT / "native_app" / "scorpion_qt.py", ROOT / "native_app" / "media_transfer.py"):
            src = py_path.read_text(encoding="utf-8")
            self.assertNotIn("verify=False", src)
            self.assertNotIn("nocheckcertificate", src)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "1")
                self.end_headers()
                self.wfile.write(b"X")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            cert = (
                x509.CertificateBuilder()
                .subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now_dt - datetime.timedelta(minutes=1))
                .not_valid_after(now_dt + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                .sign(key, hashes.SHA256())
            )
            cert_p = root / "cert.pem"
            key_p = root / "key.pem"
            cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_p.write_bytes(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))
            srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(cert_p), str(key_p))
            srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                e = _make_engine(root)
                with self.assertRaises(requests.exceptions.SSLError):
                    e.probe_url(f"https://localhost:{srv.server_port}/f.bin")
            finally:
                srv.shutdown()
                srv.server_close()

    def test_07_cookies_enforce_expiry_host_only_and_secure(self):
        with tempfile.TemporaryDirectory() as td:
            e = _make_engine(Path(td))
            now = int(time.time())
            cookies = [
                {"name": "host_sec", "value": "1", "domain": "media.example.test", "path": "/", "secure": True, "hostOnly": True, "httpOnly": True, "expirationDate": now + 3600},
                {"name": "expired", "value": "0", "domain": "media.example.test", "path": "/", "secure": False, "hostOnly": True, "expirationDate": now - 10},
            ]
            jar = e._cookies_to_jar(cookies)
            names = [c.name for c in jar]
            self.assertEqual(names, ["host_sec"])
            self.assertEqual(requests.Request("GET", "http://media.example.test/a", cookies=jar).prepare().headers.get("Cookie"), None)
            self.assertEqual(requests.Request("GET", "https://child.media.example.test/a", cookies=jar).prepare().headers.get("Cookie"), None)
            self.assertIn("host_sec=1", requests.Request("GET", "https://media.example.test/a", cookies=jar).prepare().headers.get("Cookie"))

            cf = Path(e._write_cookiefile(cookies, "unit"))
            txt = cf.read_text(encoding="utf-8")
            self.assertIn("media.example.test\tFALSE\t/\tTRUE", txt)
            self.assertNotIn(".media.example.test", txt)
            self.assertNotIn("expired", txt)

    def test_08_install_update_package_rolls_back_on_partial_failure(self):
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "local"
            target = local / "Programs" / "ScorpionIDM" / "app"
            target.mkdir(parents=True)
            first, second = target / "first.py", target / "scorpion_qt.py"
            first.write_bytes(b"old first")
            second.write_bytes(b"old functioning app")
            pkg = Path(td) / "payload.zip"
            with zipfile.ZipFile(pkg, "w") as zf:
                zf.writestr("app/first.py", b"new first")
                zf.writestr("app/scorpion_qt.py", b"new app")
            pkg_sha = hashlib.sha256(pkg.read_bytes()).hexdigest()

            calls = 0
            real_copy = shutil.copyfileobj

            def fail_second(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("disk full")
                return real_copy(src, dst)

            e = _make_engine(Path(td))
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}), \
                 patch.object(sq.shutil, "copyfileobj", side_effect=fail_second):
                ok, _ = e.install_update_package(str(pkg), pkg_sha)
            self.assertFalse(ok)
            self.assertEqual(first.read_bytes(), b"old first")
            self.assertEqual(second.read_bytes(), b"old functioning app")

    def test_10_incognito_download_not_persisted_and_no_cookies_stored(self):
        with tempfile.TemporaryDirectory() as td:
            e = _make_engine(Path(td))
            e.save_state = types.MethodType(sq.ScorpionNativeEngine.save_state, e)
            it = e.add_download({
                "url": "https://example.test/secret.zip",
                "filename": "secret.zip",
                "totalSize": 100,
                "incognito": True,
                "cookies": [{"name": "SID", "value": "secret", "domain": "example.test"}],
                "startImmediately": False,
            })
            self.assertNotIn(it["id"], e.__dict__.get("_site_cookies", {}))
            e.save_state()
            saved = json.loads(Path(e.state_file).read_text(encoding="utf-8"))
            self.assertEqual(saved["downloads"], [])

    def test_12_quality_cache_separates_anonymous_from_authenticated(self):
        with tempfile.TemporaryDirectory() as td:
            e = _make_engine(Path(td))

            class FakeYDL:
                calls = []
                def __init__(self, opts): self.opts = opts
                def __enter__(self): return self
                def __exit__(self, *a): return False
                def extract_info(self, url, download=False):
                    has_ck = bool(self.opts.get("cookiefile"))
                    FakeYDL.calls.append(has_ck)
                    if not has_ck:
                        return {"formats": []}
                    return {"formats": [{"vcodec": "avc1", "acodec": "mp4a", "height": 720, "format_id": "18"}]}

            fake_ytdlp = types.SimpleNamespace(YoutubeDL=FakeYDL)
            with patch.object(sq, "HAS_YTDLP", True), patch.object(sq, "yt_dlp", fake_ytdlp, create=True):
                r1 = e.list_video_qualities("https://video.example.test/watch?v=1", cookies=None)
                r2 = e.list_video_qualities("https://video.example.test/watch?v=1", cookies=[{"name": "S", "value": "1", "domain": "video.example.test"}])
            self.assertEqual(FakeYDL.calls, [False, True])
            self.assertEqual(r1["qualities"], [])
            self.assertTrue(len(r2["qualities"]) > 0)

    def test_14_15_strict_range_validator_and_truncated_206_rejected(self):
        payload_new = b"B" * 262144
        payload_old = b"A" * 262144
        mode = {"wrong_range": True, "etag": '"v2"', "truncate": False}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                rng = (self.headers.get("Range") or "bytes=0-0")[6:]
                start, end = map(int, rng.split("-"))
                actual_start = 0 if mode["wrong_range"] else start
                body = payload_new[actual_start:actual_start + end - start + 1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {actual_start}-{actual_start + len(body) - 1}/{len(payload_new)}")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("ETag", mode["etag"])
                self.end_headers()
                self.wfile.write(body[:50] if mode["truncate"] else body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                url = f"http://127.0.0.1:{srv.server_port}/f.bin"

                # Case A: Wrong Content-Range offset fails instead of corrupting output
                e = _make_engine(root / "a")
                it = e.add_download({"url": url, "filename": "f.bin", "totalSize": len(payload_new), "connections": 2, "supportsRange": True, "startImmediately": False})
                e.start_download(it["id"])
                _wait_download_done(it)
                self.assertEqual(it["status"], "error")
                self.assertFalse(Path(it["filePath"]).exists())

                # Case B: Changed resource on resume restarts cleanly so output matches payload_new byte-for-byte
                mode["wrong_range"] = False
                e2 = _make_engine(root / "b")
                it2 = e2.add_download({"url": url, "filename": "f.bin", "totalSize": len(payload_new), "connections": 1, "supportsRange": True, "etag": '"v1"', "startImmediately": False})
                Path(it2["tempFilePath"]).parent.mkdir(parents=True, exist_ok=True)
                Path(it2["tempFilePath"]).write_bytes(payload_old[:131072])
                it2["downloadedBytes"] = 131072
                it2["segments"][0].update(currentByte=131072, downloaded=131072)
                e2.start_download(it2["id"])
                _wait_download_done(it2)
                self.assertEqual(it2["status"], "completed")
                self.assertEqual(Path(it2["filePath"]).read_bytes(), payload_new)

                # Case C: Weak ETag disables range support in probe_url
                mode["etag"] = 'W/"weak-tag"'
                self.assertFalse(e2.probe_url(url)["supportsRange"])

                # Case D: Truncated 206 body fails instead of finishing short
                mode["etag"] = '"v2"'
                mode["truncate"] = True
                e3 = _make_engine(root / "c")
                it3 = e3.add_download({"url": url, "filename": "t.bin", "totalSize": len(payload_new), "connections": 1, "supportsRange": True, "startImmediately": False})
                with patch.object(sq.time, "sleep", side_effect=lambda _s: _REAL_SLEEP(0.002)):
                    e3.start_download(it3["id"])
                    _wait_download_done(it3)
                if it3["status"] == "downloading":
                    e3.pause_download(it3["id"])
                    _REAL_SLEEP(0.05)
                self.assertEqual(it3["status"], "error")
        finally:
            srv.shutdown()
            srv.server_close()

    def test_16_18_19_20_ui_accessibility_honest_status_scroll_and_perf(self):
        with tempfile.TemporaryDirectory() as td:
            win, _ = rt._build_test_window(Path(td))
            try:
                self.assertEqual(win.tree.focusPolicy(), Qt.FocusPolicy.StrongFocus)
                self.assertEqual(win.table.focusPolicy(), Qt.FocusPolicy.StrongFocus)
                self.assertIn("QPushButton:focus", sq.LIGHT_QSS)
                self.assertIn("QTableWidget:focus", sq.LIGHT_QSS)

                win.resize(640, 720)
                rt._QAPP.processEvents()
                win._apply_layout_mode(force=True)
                for btn in win._toolbar_buttons:
                    self.assertTrue(btn.text() or btn.accessibleName())

                win.lang = "en"
                win.apply_theme_and_lang()
                win.engine.rpc_alive = True
                win.engine.last_ext_seen = {}
                win.engine.active_connected_browsers = types.MethodType(sq.ScorpionNativeEngine.active_connected_browsers, win.engine)
                win.refresh_all()
                self.assertIn("Waiting for browser extension", win.lbl_status_bar.text())
                win.engine.last_ext_seen = {"msedge": time.time()}
                win.refresh_all()
                self.assertIn("Browser connected (msedge)", win.lbl_status_bar.text())

                # 2,000-row steady-state refresh_all stays responsive
                now_ms = int(time.time() * 1000)
                win.engine.downloads = {
                    str(i): {
                        "id": str(i),
                        "url": "https://example.test/sample.bin",
                        "filename": f"sample-{i}.bin",
                        "category": "General",
                        "filePath": str(Path(td) / f"{i}.bin"),
                        "totalSize": 1048576,
                        "downloadedBytes": 1048576,
                        "progress": 100,
                        "speed": 0,
                        "timeLeft": 0,
                        "status": "completed",
                        "createdAt": now_ms - i,
                        "segments": [],
                        "speedHistory": [],
                    }
                    for i in range(2000)
                }
                win.refresh_all()
                samples = []
                for _ in range(5):
                    s0 = time.perf_counter()
                    win.refresh_all()
                    samples.append((time.perf_counter() - s0) * 1000)
                samples.sort()
                self.assertLess(samples[2], 30.0)

                dlg = sq.SettingsDialog(win.engine, "en")
                dlg.ensurePolished()
                dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
                dlg.show()
                dlg.resize(640, 450)
                rt._QAPP.processEvents()
                self.assertGreaterEqual(len(dlg.findChildren(QScrollArea)), 1)
                self.assertLessEqual(dlg.minimumSizeHint().height(), 450)
                dlg.close()
                dlg.deleteLater()
            finally:
                win.cards.clear()
                win._really_quit = True
                win.close()
                rt._QAPP.processEvents()

    def test_21_bridge_token_auth_rejects_untrusted_clients(self):
        src = (ROOT / "native_app" / "scorpion_qt.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ScorpionNativeEngine")
        bridge = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_start_browser_rpc_bridge")
        handler = next(n for n in bridge.body if isinstance(n, ast.ClassDef) and n.name == "BridgeHandler")
        methods = [n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name in ("_origin_allowed", "_is_trusted_client")]
        ns = {
            "BRIDGE_ALLOWED_ORIGIN_PREFIXES": sq.BRIDGE_ALLOWED_ORIGIN_PREFIXES,
            "BRIDGE_CLIENT_HEADER": sq.BRIDGE_CLIENT_HEADER,
            "engine_ref": types.SimpleNamespace(bridge_token="secret-xyz"),
        }
        exec(compile(ast.Module(body=methods, type_ignores=[]), "scorpion_qt.py", "exec"), ns)

        def check(headers):
            h = types.SimpleNamespace(headers=headers)
            h._origin_allowed = lambda: ns["_origin_allowed"](h)
            return ns["_is_trusted_client"](h)

        self.assertFalse(check({"Origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "X-Scorpion-Client": "1"}))
        self.assertFalse(check({"X-Scorpion-Client": "1"}))
        self.assertFalse(check({"Origin": "https://evil.test", "X-Scorpion-Client": "1", "X-Scorpion-Token": "secret-xyz"}))
        self.assertTrue(check({"X-Scorpion-Client": "1", "X-Scorpion-Token": "secret-xyz"}))
        self.assertFalse(check({"Origin": "chrome-extension://hgcdbjpjlfgnejhceobphikeebmhmgcj", "X-Scorpion-Client": "1"}))
        self.assertTrue(check({"Origin": "chrome-extension://hgcdbjpjlfgnejhceobphikeebmhmgcj", "X-Scorpion-Client": "1", "X-Scorpion-Token": "secret-xyz"}))

    def test_22_check_for_updates_filters_extension_zips_and_requires_sha256(self):
        with tempfile.TemporaryDirectory() as td:
            e = _make_engine(Path(td))
            e.settings["updateUrl"] = "https://github.com/Mahmoud-847/scorpion-idm"
            manifest_resp = Mock(status_code=200)
            manifest_resp.json.return_value = {"version": "2.1.25"}
            rel_resp = Mock(status_code=200)
            rel_resp.json.return_value = {
                "tag_name": "v9.9.9",
                "assets": [
                    {"name": "Scorpion-Browser-Extension.zip", "browser_download_url": "https://example.test/ext.zip", "digest": "sha256:" + "a" * 64},
                ],
            }
            with patch.object(sq.requests, "get", side_effect=[manifest_resp, rel_resp]):
                res = e.check_for_updates()
            self.assertFalse(res.get("hasUpdate"))

            # Valid payload WITH valid 64-hex SHA256 IS accepted
            rel_ok = Mock(status_code=200)
            rel_ok.json.return_value = {
                "tag_name": "v9.9.9",
                "assets": [
                    {"name": "Scorpion-Browser-Extension.zip", "browser_download_url": "https://example.test/ext.zip", "digest": "sha256:" + "a" * 64},
                    {"name": "Scorpion-Update-Payload.zip", "browser_download_url": "https://example.test/payload.zip", "digest": "sha256:" + "b" * 64},
                ],
            }
            manifest_resp2 = Mock(status_code=200)
            manifest_resp2.json.return_value = {"version": "2.1.25"}
            with patch.object(sq.requests, "get", side_effect=[manifest_resp2, rel_ok]):
                res2 = e.check_for_updates()
            self.assertTrue(res2.get("hasUpdate"))
            self.assertEqual(res2.get("sha256"), "b" * 64)
            self.assertIn("payload.zip", res2.get("downloadUrl", ""))

    def test_23_24_docs_and_publisher_active_download_guard(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("بدون توقيع رقمي", readme)
        self.assertIn("SHA-256", readme)
        build_ps1 = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")
        self.assertIn("bridge-auth.json", build_ps1)
        self.assertIn("sourceSha256", build_ps1)

        with patch.object(auto_publish, "active_downloads_count", return_value=2):
            with self.assertRaises(RuntimeError):
                auto_publish.stop_running_scorpion(force=False)

        with patch.object(auto_publish, "active_downloads_count", return_value=-1):
            with self.assertRaises(RuntimeError):
                auto_publish.stop_running_scorpion(force=False)

    def test_25_gzip_200_fallback_saves_full_decompressed_bytes(self):
        import gzip

        source = b"A" * 300000
        compressed = gzip.compress(source)

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(compressed)))
                self.end_headers()
                self.wfile.write(compressed)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                e = _make_engine(Path(td))
                it = e.add_download({
                    "url": f"http://127.0.0.1:{srv.server_port}/file.bin",
                    "filename": "file.bin",
                    "totalSize": len(compressed),
                    "connections": 1,
                    "supportsRange": True,
                    "startImmediately": False,
                })
                e.start_download(it["id"])
                _wait_download_done(it)
                self.assertEqual(it["status"], "completed")
                self.assertEqual(Path(it["filePath"]).read_bytes(), source)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_26_resume_requires_comparable_validator_for_no_validator_and_type_change(self):
        old, new = b"A" * 262144, b"B" * 262144
        served = {"etag": None, "lm": None}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                rng = (self.headers.get("Range") or "bytes=0-0")[6:]
                start, end = map(int, rng.split("-"))
                body = new[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(new)}")
                self.send_header("Content-Length", str(len(body)))
                if served["etag"]:
                    self.send_header("ETag", served["etag"])
                if served["lm"]:
                    self.send_header("Last-Modified", served["lm"])
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                url = f"http://127.0.0.1:{srv.server_port}/f.bin"
                for name, init_kw, etag_s, lm_s in (
                    ("none", {}, None, None),
                    ("type_swap", {"etag": '"v1"'}, None, "Tue, 17 Nov 2026 10:00:00 GMT"),
                ):
                    served["etag"], served["lm"] = etag_s, lm_s
                    e = _make_engine(root / name)
                    it = e.add_download({
                        "url": url, "filename": "f.bin", "totalSize": len(new),
                        "connections": 1, "supportsRange": True, "startImmediately": False, **init_kw
                    })
                    Path(it["tempFilePath"]).parent.mkdir(parents=True, exist_ok=True)
                    Path(it["tempFilePath"]).write_bytes(old[:131072])
                    it["downloadedBytes"] = 131072
                    it["segments"][0].update(currentByte=131072, downloaded=131072)
                    e.start_download(it["id"])
                    _wait_download_done(it)
                    self.assertEqual(it["status"], "completed")
                    self.assertEqual(Path(it["filePath"]).read_bytes(), new)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_27_strict_http_session_preserves_host_only_through_prepare_and_redirect(self):
        with tempfile.TemporaryDirectory() as td:
            e = _make_engine(Path(td))
            cookies = [{"name": "sid", "value": "secret", "domain": "media.example.test", "path": "/", "secure": True, "hostOnly": True}]
            with e._http_session(cookies) as sess:
                p_http = sess.prepare_request(requests.Request("GET", "http://media.example.test/file"))
                p_host = sess.prepare_request(requests.Request("GET", "https://media.example.test/file"))
                p_sub = sess.prepare_request(requests.Request("GET", "https://child.media.example.test/file"))
                self.assertIsNone(p_http.headers.get("Cookie"))
                self.assertIn("sid=secret", p_host.headers.get("Cookie") or "")
                self.assertIsNone(p_sub.headers.get("Cookie"))
                # Simulate redirect copy
                p_redir = p_host.copy()
                p_redir.url = "https://child.media.example.test/next"
                p_redir.headers.pop("Cookie", None)
                p_redir.prepare_cookies(p_redir._cookies)
                self.assertIsNone(p_redir.headers.get("Cookie"))

    def test_28_update_post_commit_callback_failure_keeps_live_app(self):
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / "local"
            app_py = local / "Programs" / "ScorpionIDM" / "app" / "scorpion_qt.py"
            app_py.parent.mkdir(parents=True)
            app_py.write_bytes(b"old app")
            pkg = Path(td) / "payload.zip"
            with zipfile.ZipFile(pkg, "w") as zf:
                zf.writestr("app/scorpion_qt.py", b"new app")
            pkg_sha = hashlib.sha256(pkg.read_bytes()).hexdigest()

            def bad_cb(pct):
                if pct == 100:
                    raise RuntimeError("UI callback failed")

            e = _make_engine(Path(td))
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
                ok, _ = e.install_update_package(str(pkg), pkg_sha, bad_cb)
            self.assertTrue(ok)
            self.assertTrue(app_py.exists())
            self.assertEqual(app_py.read_bytes(), b"new app")

    def test_29_quality_cache_isolates_accounts_and_anonymous(self):
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as td:
            e = _make_engine(Path(td))
            e._js_runtime_opts = Mock(return_value={})
            e._build_media_headers = Mock(return_value={})
            e._write_cookiefile = Mock(return_value="")
            e._extract_with_fallback = Mock(side_effect=[
                {"title": "Account A Title", "formats": [{"height": 720, "vcodec": "h264", "acodec": "aac", "filesize": 1000}]},
                {"title": "Account B Title", "formats": [{"height": 1080, "vcodec": "h264", "acodec": "aac", "filesize": 2000}]},
                {"title": "Public Anon Title", "formats": [{"height": 360, "vcodec": "h264", "acodec": "aac", "filesize": 500}]},
            ])
            fake_ydl = types.SimpleNamespace(YoutubeDL=lambda _o: MagicMock())
            url = "https://video.example.test/private"
            with patch.object(sq, "HAS_YTDLP", True), patch.object(sq, "yt_dlp", fake_ydl, create=True):
                r_a = e.list_video_qualities(url, cookies=[{"name": "S", "value": "A", "domain": "video.example.test"}])
                r_b = e.list_video_qualities(url, cookies=[{"name": "S", "value": "B", "domain": "video.example.test"}])
                r_anon = e.list_video_qualities(url, cookies=None)
            self.assertEqual(e._extract_with_fallback.call_count, 3)
            self.assertEqual(r_a["title"], "Account A Title")
            self.assertEqual(r_b["title"], "Account B Title")
            self.assertEqual(r_anon["title"], "Public Anon Title")

    def test_30_browser_transfer_pacing_abort_and_unified_torrent_budget(self):
        import base64

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            e = _make_engine(root)
            e.settings["globalSpeedLimitKbps"] = 1
            chunk_b = base64.b64encode(b"x" * 524288).decode("ascii")
            start_res = e.begin_browser_transfer({"url": "https://web.telegram.org/a/progressive/1", "filename": "v.mp4", "totalSize": 1048576})
            tok = start_res["transferId"]
            item, ctrl = e._browser_transfers[tok]
            worker_errs = []

            def _run_chunk():
                try:
                    e.receive_browser_transfer("chunk", {"transferId": tok, "offset": 0, "data": chunk_b})
                except ValueError as exc:
                    worker_errs.append(str(exc))

            t_worker = threading.Thread(target=_run_chunk, daemon=True)
            t_worker.start()
            _REAL_SLEEP(0.12)
            cancelled = threading.Event()

            def _cancel():
                e.pause_download(item["id"])
                cancelled.set()

            threading.Thread(target=_cancel, daemon=True).start()
            self.assertTrue(cancelled.wait(0.25), "pause_download must not block on bandwidth limiter sleep")
            t_worker.join(2)
            self.assertTrue(worker_errs)

            # Unified torrent + native global budget must sum to <= globalSpeedLimitKbps
            e2 = _make_engine(root / "budget")
            e2.settings["globalSpeedLimitKbps"] = 100
            e2.downloads = {
                "nat": {"id": "nat", "speedLimitKbps": 0, "status": "downloading"},
                "tor": {"id": "tor", "speedLimitKbps": 0, "status": "downloading", "isTorrent": True},
            }
            e2.controllers = {"nat": {}, "tor": {"isTorrent": True}}
            tor_cap, nat_budget = e2._global_budget_split()
            self.assertLessEqual(tor_cap + nat_budget, 100)

    def test_31_primary_ext_receives_bridge_auth_and_publisher_locks_tested_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            primary = root / "Programs" / "ScorpionIDM" / "browser-extension"
            secondary = root / "ScorpionIDM" / "browser-extension"
            primary.mkdir(parents=True)
            (primary / "manifest.json").write_text("{}", encoding="utf-8")
            e = _make_engine(root)
            e.ext_source_dir = str(primary)
            e.legacy_prog_ext_dir = str(primary)
            e.appdata_ext_dir = str(secondary)
            e.bridge_token = "t" * 64
            selected = e.get_permanent_ext_dir()
            self.assertEqual(selected, str(primary))
            self.assertTrue((primary / "bridge-auth.json").is_file())
            self.assertTrue((secondary / "bridge-auth.json").is_file())

        # Publisher rejects mutation happening during validate_release_sources
        pub_src = (ROOT / "auto_publish.py").read_text(encoding="utf-8")
        tree = ast.parse(pub_src)
        pub_cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AutoPublisherWindow")
        trig = next(n for n in pub_cls.body if isinstance(n, ast.FunctionDef) and n.name == "trigger_build_and_publish")
        worker_fn = next(n for n in trig.body if isinstance(n, ast.FunctionDef) and n.name == "worker")
        state = {"s": "A"}
        reached_build = [False]
        finished_err = []

        def mutating_validate(_log):
            state["s"] = "B"

        sig = types.SimpleNamespace(
            progress=types.SimpleNamespace(emit=lambda *a: None),
            log=types.SimpleNamespace(emit=lambda *a: None),
            finished=types.SimpleNamespace(emit=lambda ok, msg: finished_err.append((ok, msg))),
        )
        ns = {
            "self": types.SimpleNamespace(signals=sig),
            "do_bump": False,
            "note_ar": "",
            "ensure_on_up_to_date_main": lambda: None,
            "validate_release_sources": mutating_validate,
            "compute_snapshot": lambda: dict(state),
            "read_current_version": lambda: "2.1.27",
            "stop_running_scorpion": lambda **kw: reached_build.__setitem__(0, True),
        }
        exec(compile(ast.Module(body=[worker_fn], type_ignores=[]), "auto_publish.py", "exec"), ns)
        ns["worker"]()
        self.assertFalse(reached_build[0])
        self.assertEqual(finished_err[0][0], False)

    def test_32_video_range_resume_enforces_strong_entity_validators(self):
        old = b"A" * 262144
        new = b"B" * 262144
        cut = 131072
        served = {"etag": '"version-2"', "lm": None, "first_byte_reads": 0}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                rng = (self.headers.get("Range") or "bytes=0-0")[6:]
                start, end = map(int, rng.split("-"))
                if start == 0 and end > 0:
                    served["first_byte_reads"] += 1
                body = new[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(new)}")
                self.send_header("Content-Length", str(len(body)))
                if served["etag"]:
                    self.send_header("ETag", served["etag"])
                if served["lm"]:
                    self.send_header("Last-Modified", served["lm"])
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                url = f"http://127.0.0.1:{srv.server_port}/video.mp4"
                cases = [
                    ("changed_etag", {"etag": '"version-1"'}, '"version-2"', None, False),
                    ("weak_etag", {"etag": '"version-1"'}, 'W/"version-1"', None, False),
                    ("missing_validator", {}, None, None, False),
                    ("matching_etag", {"etag": '"version-1"'}, '"version-1"', None, True),
                ]
                for label, init_kw, etag_s, lm_s, should_resume in cases:
                    served["etag"] = etag_s
                    served["lm"] = lm_s
                    served["first_byte_reads"] = 0
                    e = _make_engine(root / label)
                    it = e.add_download({
                        "url": url, "filename": "video.mp4", "isVideo": True,
                        "totalSize": len(new), "connections": 8, "startImmediately": False, **init_kw
                    })
                    part = Path(e.get_item_temp_dir(it["id"])) / "stream0.mp4.part"
                    part.parent.mkdir(parents=True, exist_ok=True)
                    part.write_bytes(old[:cut] + b"\0" * (len(old) - cut))
                    it["videoLayout"] = [[0, len(new), 8]]
                    it["downloadedBytes"] = cut
                    it["segments"] = [{
                        "id": 1, "streamIdx": 0, "localStart": 0, "localCur": cut,
                        "localEnd": len(new) - 1, "downloaded": cut, "currentByte": cut,
                        "startByte": 0, "endByte": len(new) - 1, "status": "paused",
                    }]
                    ctrl = {"aborted": False}
                    e.controllers[it["id"]] = ctrl
                    handled = e._download_video_streams_16ports(
                        it, ctrl,
                        [{"url": url, "protocol": "http", "ext": "mp4", "vcodec": "h264", "acodec": "none", "filesize": len(new)}],
                        str(root / label / "out"), "", False, "best",
                    )
                    if label in ("weak_etag", "missing_validator"):
                        self.assertFalse(handled, label)
                        self.assertNotIn("_videoOutput", it, label)
                        continue
                    self.assertTrue(handled, label)
                    got = Path(it["_videoOutput"]).read_bytes()
                    if should_resume:
                        self.assertEqual(got, old[:cut] + new[cut:], label)
                        self.assertEqual(served["first_byte_reads"], 0, label)
                    else:
                        self.assertEqual(got, new, label)
                        self.assertGreaterEqual(served["first_byte_reads"], 1, label)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_33_low_speed_browser_transfer_returns_unclamped_throttle_and_tracks_debt(self):
        import base64

        now = [0.0]

        class _Clock:
            def monotonic(self):
                return now[0]

            def sleep(self, sec):
                now[0] += float(sec)

        clk = _Clock()
        with tempfile.TemporaryDirectory() as td:
            e = _make_engine(Path(td))
            e.settings["globalSpeedLimitKbps"] = 1
            start = e.begin_browser_transfer({"url": "https://web.telegram.org/a/progressive/v", "filename": "v.mp4", "totalSize": 1048576})
            self.assertEqual(start["chunkSize"], 4096)
            tok = start["transferId"]
            chunk_b64 = base64.b64encode(b"a" * 524288).decode("ascii")
            with patch.object(sq.time, "monotonic", side_effect=clk.monotonic), \
                 patch.object(sq.time, "sleep", side_effect=clk.sleep):
                r1 = e.receive_browser_transfer("chunk", {"transferId": tok, "offset": 0, "data": chunk_b64})
                self.assertGreater(r1.get("throttleMs", 0), 400000)
                eff_kbps = 512.0 / (clk.now + r1["throttleMs"] / 1000.0) if hasattr(clk, "now") else 512.0 / (now[0] + r1["throttleMs"] / 1000.0)
                self.assertLessEqual(eff_kbps, 1.05)
                # Sending next chunk early (after only 60s instead of full throttleMs) must retain unpaid debt!
                clk.sleep(60.0)
                r2 = e.receive_browser_transfer("chunk", {"transferId": tok, "offset": 524288, "data": chunk_b64})
                self.assertGreater(r2.get("throttleMs", 0), 900000)
            e.fail_browser_transfer(tok, "done")

    def test_34_global_budget_split_stays_within_1_kbps_limit(self):
        with tempfile.TemporaryDirectory() as td:
            e = _make_engine(Path(td))
            e.settings["globalSpeedLimitKbps"] = 1
            e.downloads = {
                "nat": {"id": "nat", "speedLimitKbps": 0, "status": "downloading"},
                "tor": {"id": "tor", "speedLimitKbps": 0, "status": "downloading", "isTorrent": True},
            }
            e.controllers = {"nat": {}, "tor": {"isTorrent": True}}
            tor_cap, nat_budget = e._global_budget_split()
            self.assertGreater(tor_cap, 0.0)
            self.assertGreater(nat_budget, 0.0)
            self.assertLessEqual(tor_cap + nat_budget, 1.0 + 1e-9)

    def test_35_update_install_separates_relaunch_failure_without_quitting(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "local"
            install_dir = local / "Programs" / "ScorpionIDM"
            install_dir.mkdir(parents=True)
            (install_dir / "ScorpionIDM.exe").write_bytes(b"old-exe")
            pkg = root / "payload.zip"
            with zipfile.ZipFile(pkg, "w") as zf:
                zf.writestr("ScorpionIDM.exe", b"new-exe")
            pkg_sha = hashlib.sha256(pkg.read_bytes()).hexdigest()
            quits = []
            e = _make_engine(root)
            e.signals = types.SimpleNamespace(quit_requested=types.SimpleNamespace(emit=lambda: quits.append(True)))
            with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}), \
                 patch.object(sq.subprocess, "Popen", side_effect=OSError("launch blocked")):
                ok, status = e.install_update_package(str(pkg), pkg_sha)
            self.assertTrue(ok)
            self.assertTrue(status.startswith("installed_restart_failed:"))
            self.assertEqual(quits, [])
            self.assertEqual((install_dir / "ScorpionIDM.exe").read_bytes(), b"new-exe")

            dlg = sq.UpdateDialog(e, lang="en", update_info={"version": "2.1.27", "hasUpdate": False})
            try:
                with patch.object(dlg, "accept") as acc:
                    dlg._on_finished(True, status)
                    rt._QAPP.processEvents()
                acc.assert_not_called()
                self.assertIn("restart", dlg.lbl_prog.text().lower())
            finally:
                dlg.close()

    def test_36_publisher_aborts_if_snapshot_mutates_in_final_window(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "release").mkdir()
            (root / "native_app").mkdir()
            pkg = root / "release" / "Scorpion-Update-Payload.zip"
            pkg.write_bytes(b"pkg")
            setup = root / "setup.exe"
            setup.write_bytes(b"setup")
            tools = root / "tools.zip"
            tools.write_bytes(b"tools")
            src_hash = hashlib.sha256()
            for name in ("scorpion_qt.py", "sitecustomize.py", "media_transfer.py", "scorpion_brand.py", "scorpion_cards.py"):
                rel = f"native_app/{name}"
                content = (ROOT / rel).read_bytes()
                (root / rel).write_bytes(content)
                src_hash.update((rel + "\0").encode("utf-8"))
                src_hash.update(content)
            (root / "release" / "update.json").write_text(json.dumps({
                "version": "2.1.27",
                "sha256": hashlib.sha256(pkg.read_bytes()).hexdigest(),
                "sourceSha256": src_hash.hexdigest(),
                "tools": {"version": "v1"},
            }))
            pub_src = (ROOT / "auto_publish.py").read_text(encoding="utf-8")
            tree = ast.parse(pub_src)
            pub_cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AutoPublisherWindow")
            trig = next(n for n in pub_cls.body if isinstance(n, ast.FunctionDef) and n.name == "trigger_build_and_publish")
            worker_fn = next(n for n in trig.body if isinstance(n, ast.FunctionDef) and n.name == "worker")
            state = {"ext": "A"}
            stops, git_cmds, finished = [], [], []
            sig = types.SimpleNamespace(
                progress=types.SimpleNamespace(emit=lambda *a: None),
                log=types.SimpleNamespace(emit=lambda *a: None),
                finished=types.SimpleNamespace(emit=lambda *a: finished.append(a)),
            )

            def _stop(**_kw):
                stops.append(True)
                if len(stops) == 2:
                    state["ext"] = "B"

            class _Build:
                stdout = [f"SETUP_PATH={setup}", "TOOLS_VERSION=v1", f"TOOLS_PACK={tools}"]
                returncode = 0
                def wait(self):
                    return 0

            ns = {
                "self": types.SimpleNamespace(signals=sig),
                "do_bump": False,
                "note_ar": "",
                "PROJECT_ROOT": str(root),
                "REPO_URL": "synthetic",
                "ensure_on_up_to_date_main": lambda: None,
                "validate_release_sources": lambda _l: None,
                "compute_snapshot": lambda: dict(state),
                "read_current_version": lambda: "2.1.27",
                "stop_running_scorpion": _stop,
                "copy_tree_safely": lambda *a: None,
                "read_local_bridge_token": lambda: "",
                "subprocess": types.SimpleNamespace(Popen=lambda *a, **k: _Build(), PIPE=-1, STDOUT=-2),
                "publish_tools_pack": lambda *a: None,
                "run_git": lambda *a: (git_cmds.append(a), types.SimpleNamespace(returncode=0, stdout="h", stderr=""))[1],
            }
            exec(compile(ast.Module(body=[worker_fn], type_ignores=[]), "auto_publish.py", "exec"), ns)
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local")}):
                ns["worker"]()
            self.assertFalse(any(a[0] == "commit" for a in git_cmds))
            self.assertFalse(any(a[0] == "push" for a in git_cmds))
            self.assertEqual(finished[-1][0], False)

    def test_37_unpacked_extension_discovery_rejects_arbitrary_scorpion_substring(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            local = root / "local"
            trusted_ext = local / "ScorpionIDM" / "browser-extension"
            evil_ext = root / "evil-scorpion-helper"
            trusted_ext.mkdir(parents=True)
            evil_ext.mkdir(parents=True)
            (trusted_ext / "manifest.json").write_text('{"name":"Scorpion"}', encoding="utf-8")
            (evil_ext / "manifest.json").write_text('{"name":"Scorpion Coupon Helper"}', encoding="utf-8")

            pref = local / "Microsoft" / "Edge" / "User Data" / "Default" / "Preferences"
            pref.parent.mkdir(parents=True)
            trusted_id = "a" * 32
            evil_name_id = "b" * 32
            evil_path_id = "c" * 32
            pref.write_text(json.dumps({
                "extensions": {
                    "settings": {
                        trusted_id: {"path": str(trusted_ext), "manifest": {"name": "Scorpion"}},
                        evil_name_id: {"path": str(root / "benign-folder"), "manifest": {"name": "Scorpion Coupon Helper"}},
                        evil_path_id: {"path": str(evil_ext), "manifest": {"name": "Helper"}},
                    }
                }
            }), encoding="utf-8")
            (root / "benign-folder").mkdir()

            with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}):
                origins = sq._discover_unpacked_extension_origins()
                self.assertIn(f"chrome-extension://{trusted_id}/", origins)
                self.assertNotIn(f"chrome-extension://{evil_name_id}/", origins)
                self.assertNotIn(f"chrome-extension://{evil_path_id}/", origins)

                e = _make_engine(root)
                e.ext_source_dir = str(ROOT / "browser-extension")
                e.legacy_prog_ext_dir = str(local / "Programs" / "ScorpionIDM" / "browser-extension")
                e.appdata_ext_dir = str(trusted_ext)
                e.bridge_token = "t" * 64
                e.sync_and_repair_browser_extensions()
                self.assertFalse((evil_ext / "bridge-auth.json").exists())
                self.assertTrue((trusted_ext / "bridge-auth.json").is_file())


class FinalReleaseReviewTests(unittest.TestCase):
    def test_release_validation_requires_extension_test_runtime(self):
        with patch.object(auto_publish.shutil, "which", return_value=None), \
             patch.object(auto_publish.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Node.js is required"):
                auto_publish.validate_release_sources(lambda *_: None)
        run.assert_not_called()

    def test_extension_release_fingerprint_covers_packaged_assets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "icons").mkdir()
            (root / "manifest.json").write_bytes(b"{}")
            (root / "icons" / "icon.png").write_bytes(b"\xff\x80")
            original = auto_publish.extension_tree_digest(str(root))
            (root / "bridge-auth.json").write_bytes(b"local data")
            self.assertEqual(original, auto_publish.extension_tree_digest(str(root)))
            (root / "icons" / "icon.png").write_bytes(b"\xfe\x80")
            self.assertNotEqual(original, auto_publish.extension_tree_digest(str(root)))

    def test_downloads_extension_requires_complete_tree_match_before_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            (source / "manifest.json").write_text('{}', encoding="utf-8")
            (source / "popup.html").write_text('<p>original</p>', encoding="utf-8")
            copy = root / "home" / "Downloads" / "Scorpion-Browser-Extension"
            shutil.copytree(source, copy)
            self.assertTrue(sq._ext_dir_matches_reference(str(copy), str(source)))
            (copy / "popup.html").write_text('<p>different</p>', encoding="utf-8")
            self.assertFalse(sq._ext_dir_matches_reference(str(copy), str(source)))
            e = _make_engine(root)
            e.ext_source_dir = str(source)
            e.legacy_prog_ext_dir = str(root / "installed" / "primary")
            e.appdata_ext_dir = str(root / "installed" / "secondary")
            with patch.object(sq.os.path, "expanduser", return_value=str(root / "home")), \
                 patch.dict(os.environ, {"TEMP": str(root / "other-temp")}), \
                 patch.object(sq, "register_native_messaging_hosts"):
                e.sync_and_repair_browser_extensions()
            self.assertFalse((copy / "bridge-auth.json").exists())
            self.assertEqual((copy / "popup.html").read_text(), '<p>different</p>')
            shutil.copy2(source / "popup.html", copy / "popup.html")
            (copy / "extra.js").write_text('additional fixture', encoding="utf-8")
            self.assertFalse(sq._ext_dir_matches_reference(str(copy), str(source)))

    def test_publisher_snapshot_covers_binary_assets_and_staged_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            asset = root / "browser-extension" / "icons" / "icon.png"
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"\xff\x80")
            with patch.object(auto_publish, "PROJECT_ROOT", str(root)), \
                 patch.object(auto_publish, "WATCH_TARGETS", []):
                first = auto_publish.compute_snapshot()
                asset.write_bytes(b"\xfe\x80")
                second = auto_publish.compute_snapshot()
                self.assertNotEqual(first, second)
                # Ordinary fixture: index differs even if worktree has returned to the tested state.
                with patch.object(auto_publish.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout=b"\xff\x80")):
                    self.assertFalse(auto_publish.staged_sources_match_snapshot(second))
                with patch.object(auto_publish.subprocess, "run", return_value=types.SimpleNamespace(returncode=0, stdout=b"\xfe\x80")):
                    self.assertTrue(auto_publish.staged_sources_match_snapshot(second))
                (asset.parent / "extra.png").write_bytes(b"new")
                self.assertNotEqual(second, auto_publish.compute_snapshot())
        self.assertEqual(auto_publish._snapshot_digest("source.js", b"a\r\n"), auto_publish._snapshot_digest("source.js", b"a\n"))


if __name__ == "__main__":
    unittest.main()
