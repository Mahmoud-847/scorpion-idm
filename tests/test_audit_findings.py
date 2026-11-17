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
        self.assertTrue(check({"Origin": "chrome-extension://hgcdbjpjlfgnejhceobphikeebmhmgcj", "X-Scorpion-Client": "1"}))

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


if __name__ == "__main__":
    unittest.main()
