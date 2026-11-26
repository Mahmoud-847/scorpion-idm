"""Exercise the shipped Windows runtime without installing or registering the package."""

import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
from zipfile import ZipFile


def smoke_extracted_runtime():
    import hashlib
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import runpy
    import threading
    import time
    from unittest.mock import patch
    from urllib.error import HTTPError
    from urllib.request import build_opener, ProxyHandler, Request

    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
    import scorpion_qt as sq

    profile = Path(os.environ['USERPROFILE']).resolve()
    local = profile / 'AppData' / 'Local'
    temp_root = Path(tempfile.gettempdir()).resolve()
    isolated = profile.name == 'profile' and profile.parent.parent == temp_root and profile.parent.name.startswith('scorpion_store_smoke_')
    if not isolated or Path(os.environ['LOCALAPPDATA']).resolve() != local or not sq.is_msix_packaged():
        raise RuntimeError('Expected an extracted Store build and an isolated profile')
    launcher = Path(sys.executable).parent / 'app' / 'sitecustomize.py'
    with patch.object(sys, 'orig_argv', [sys.executable, 'scorpion-idm://open']), \
         patch.object(sys, 'argv', list(sys.argv)), \
         patch.object(runpy, 'run_path') as launch, patch.object(os, '_exit') as leave:
        exec(compile(launcher.read_bytes(), str(launcher), 'exec'), {'__file__': str(launcher)})
        launch.assert_called_once_with(str(launcher.with_name('scorpion_qt.py')), run_name='__main__')
        leave.assert_called_once_with(0)
        if len(sys.argv) != 1:
            raise RuntimeError('The Store open link was forwarded as a download')
    retired_host = subprocess.run([sys.executable, '-m', 'sitecustomize', '--native-messaging'],
                                  capture_output=True, timeout=5)
    if retired_host.returncode != 1 or retired_host.stdout:
        raise RuntimeError('The Store runtime accepted a Native Messaging launch')
    appdata = local / 'ScorpionIDM'
    appdata.mkdir(parents=True)
    (appdata / 'scorpion_native_state.json').write_text(json.dumps({'settings': {
        'wizardShownOnce': True, 'lastSeenVersion': sq.APP_VERSION, 'clipboardMonitor': False,
        'autoCheckUpdates': False, 'startWithWindows': False, 'associateTorrents': False,
    }}), encoding='utf-8')

    payload = b'Scorpion Store package smoke test\n' * 4096

    class Origin(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_HEAD(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()

        def do_GET(self):
            body = payload
            requested = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers.get('Range') or '')
            if requested:
                start = int(requested[1]); end = int(requested[2] or len(payload) - 1)
                if not (0 <= start <= end < len(payload)):
                    self.send_error(416)
                    return
                self.send_response(206)
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(payload)}')
                body = payload[start:end + 1]
            else:
                self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('ETag', '"scorpion-store-test-v1"')
            self.end_headers()
            self.wfile.write(body)

    origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
    threading.Thread(target=origin.serve_forever, daemon=True).start()
    fixture = f'http://127.0.0.1:{origin.server_port}'
    bridge_ready = threading.Event()
    bridge_servers = []

    def test_bridge_server(address, handler):
        if address[0] != '127.0.0.1':
            raise RuntimeError('Expected a loopback bridge')
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        bridge_servers.append(server)
        bridge_ready.set()
        return server

    app = QApplication([])
    with patch.object(sq, 'ThreadingHTTPServer', test_bridge_server), \
         patch.object(sq, 'apply_shell_integration'), \
         patch.object(QSystemTrayIcon, 'isSystemTrayAvailable', return_value=False):
        win = sq.ScorpionMainWindow(app)
    try:
        if not bridge_ready.wait(timeout=5):
            raise RuntimeError('Local bridge did not start')
        bridge = f'http://127.0.0.1:{bridge_servers[0].server_port}'
        if (appdata / 'native_host.bat').exists() or (appdata / 'browser-extension' / 'bridge-auth.json').exists():
            raise RuntimeError('The Store runtime attempted to provision Native Messaging')
        opener = build_opener(ProxyHandler({}))
        headers = {
            'X-Scorpion-Client': '1', 'Content-Type': 'application/json',
            'Origin': 'chrome-extension://' + sq.OFFICIAL_EXTENSION_ID,
        }

        def call(path, data=None, request_headers=None):
            encoded = None if data is None else json.dumps(data).encode()
            with opener.open(Request(bridge + path, data=encoded, headers=request_headers or headers), timeout=5) as response:
                if response.headers.get('X-Scorpion-Bridge-Mode') != 'store':
                    raise RuntimeError('Store bridge mode is missing')
                return json.load(response)

        def reject(path, data=None, request_headers=None):
            try:
                call(path, data, request_headers)
            except HTTPError as error:
                if error.code == 403:
                    return
                raise
            raise RuntimeError(f'Expected rejected request: {path}')

        reject('/ping?ext=1&browser=msedge')
        reject('/capture?url=' + fixture + '/must-not-queue.bin')
        expired = win.engine.create_store_pairing_code().replace('-', '')
        with win.engine.lock:
            win.engine._store_pairing = (expired, time.monotonic() - 1, 6)
        reject('/pair', {'code': expired})
        limited = win.engine.create_store_pairing_code().replace('-', '')
        for _ in range(6):
            reject('/pair', {'code': '000000000001' if limited == '000000000000' else '000000000000'})
        reject('/pair', {'code': limited})
        code = win.engine.create_store_pairing_code().replace('-', '')
        reject('/pair', {'code': code}, {**headers, 'Origin': 'https://example.com'})
        reject('/pair', {'code': '000000000001' if code == '000000000000' else '000000000000'})
        token = call('/pair', {'code': code})['token']
        reject('/pair', {'code': code})
        headers['X-Scorpion-Token'] = token
        if not call('/ping?ext=1&browser=msedge')['authenticated']:
            raise RuntimeError('Packaged bridge did not authenticate the paired browser')
        win.engine.add_download({'url': fixture + '/manual.bin', 'filename': 'manual.bin',
                                 'connections': 1, 'startImmediately': True})
        if not call('/capture', {'url': fixture + '/browser.bin', 'filename': 'browser.bin', 'type': 'file'})['ok']:
            raise RuntimeError('Browser capture was not accepted')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            app.processEvents()
            with win.engine.lock:
                items = list(win.engine.downloads.values())
                browser_completion_recorded = bool(win.engine.settings.get('extensionCompletedIds'))
            if len(items) == 2 and all(item['status'] == 'completed' for item in items) and browser_completion_recorded:
                break
            time.sleep(.02)
        else:
            raise RuntimeError(f'Downloads did not finish: {[item.get("status") for item in items]}')
        expected_hash = hashlib.sha256(payload).digest()
        for item in items:
            if hashlib.sha256(Path(item['filePath']).read_bytes()).digest() != expected_hash:
                raise RuntimeError(f'Download integrity check failed: {item["filename"]}')
        if call('/ping')['extensionCompletedCount'] != 1:
            raise RuntimeError('Expected exactly one completed download through browser capture')
        print('Packaged UI, single-use Store pairing, authenticated capture and both byte-exact downloads passed.')
    finally:
        win.timer.stop()
        win.cards.clear()
        win._really_quit = True
        win.close()
        app.processEvents()
        for server in bridge_servers + [origin]:
            server.shutdown()
            server.server_close()


def run_package(package: Path):
    temp_root = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix='scorpion_store_smoke_') as directory:
        root = Path(directory).resolve()
        if root.parent != temp_root or not root.name.startswith('scorpion_store_smoke_'):
            raise RuntimeError('Unexpected temporary directory')
        with ZipFile(package) as bundle:
            for name in bundle.namelist():
                path = PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
                    raise RuntimeError(f'Invalid package path: {name}')
            bundle.extractall(root / 'package')
        profile = root / 'profile'
        local = profile / 'AppData' / 'Local'
        local.mkdir(parents=True)
        env = {**os.environ, 'USERPROFILE': str(profile), 'LOCALAPPDATA': str(local), 'APPDATA': str(local),
               'QT_QPA_PLATFORM': 'offscreen', 'PYTHONUTF8': '1', 'NO_PROXY': '127.0.0.1,localhost'}
        exe = root / 'package' / 'ScorpionIDM.exe'
        result = subprocess.run([str(exe), str(Path(__file__).resolve()), '--extracted'],
                                cwd=exe.parent, env=env, capture_output=True, timeout=45)
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        return result.returncode


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: py tests/smoke_store_package.py <package.msix>')
    if sys.argv[1] == '--extracted':
        smoke_extracted_runtime()
    else:
        raise SystemExit(run_package(Path(sys.argv[1]).resolve(strict=True)))
