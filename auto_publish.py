# -*- coding: utf-8 -*-
"""
Scorpion IDM — Automatic GitHub Builder & Publisher
Watches project files for any modification, automatically bumps the version,
rebuilds the app + update payload + installer, safely updates the local install,
and pushes to GitHub so all PCs receive the update.
"""
import os
import re
import sys
import json
import time
import socket
import shutil
import hashlib
import ctypes
import threading
import subprocess
import urllib.request

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QTextEdit,
    QProgressBar,
    QFrame,
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_URL = "https://github.com/Mahmoud-847/scorpion-idm.git"

WATCH_TARGETS = [
    os.path.join(PROJECT_ROOT, "native_app", "scorpion_qt.py"),
    os.path.join(PROJECT_ROOT, "native_app", "sitecustomize.py"),
    os.path.join(PROJECT_ROOT, "native_app", "media_transfer.py"),
    os.path.join(PROJECT_ROOT, "native_app", "installer", "scorpion_setup.iss"),
    os.path.join(PROJECT_ROOT, "browser-extension", "manifest.json"),
    os.path.join(PROJECT_ROOT, "browser-extension", "background.js"),
    os.path.join(PROJECT_ROOT, "browser-extension", "content.js"),
    os.path.join(PROJECT_ROOT, "browser-extension", "media.js"),
    os.path.join(PROJECT_ROOT, "browser-extension", "browser-transfer.js"),
    os.path.join(PROJECT_ROOT, "browser-extension", "telegram-reader.js"),
    os.path.join(PROJECT_ROOT, "browser-extension", "content.css"),
    os.path.join(PROJECT_ROOT, "browser-extension", "popup.html"),
    os.path.join(PROJECT_ROOT, "browser-extension", "popup.js"),
    os.path.join(PROJECT_ROOT, "build_installer.ps1"),
    os.path.join(PROJECT_ROOT, "requirements.txt"),
    os.path.join(PROJECT_ROOT, "tests", "test_media_transfer.py"),
    os.path.join(PROJECT_ROOT, "tests", "browser-transfer.test.cjs"),
    os.path.join(PROJECT_ROOT, "tests", "content-panel.test.cjs"),
    os.path.join(PROJECT_ROOT, "tests", "test_publisher_startup.py"),
    os.path.join(PROJECT_ROOT, "tests", "package.json"),
    os.path.join(PROJECT_ROOT, "tests", "package-lock.json"),
]


def validate_release_sources(log):
    """Never close the user's app or publish a release whose regression checks fail."""
    commands = [
        [sys.executable, "-m", "py_compile", "native_app/scorpion_qt.py", "native_app/media_transfer.py", "auto_publish.py"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"],
    ]
    node = shutil.which("node")
    if not node:
        # The Python checks still guard the app; only the extension's checks need Node.js
        log("⚠ Node.js غير مثبت على هذا الجهاز: تم تخطي اختبارات إضافة المتصفح (اختبارات البرنامج تعمل).")
    elif not os.path.isdir(os.path.join(PROJECT_ROOT, "tests", "node_modules", "jsdom")):
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            raise RuntimeError("npm is required to install the extension UI test dependencies")
        installed = subprocess.run([npm, "ci", "--prefix", "tests", "--ignore-scripts", "--no-audit", "--no-fund"],
                                   cwd=PROJECT_ROOT, capture_output=True, text=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if installed.returncode:
            raise RuntimeError("Could not install the extension UI test dependencies")
    if node:
        commands.extend([[node, "--check", f"browser-extension/{name}"] for name in
                         ("background.js", "content.js", "popup.js", "media.js", "browser-transfer.js", "telegram-reader.js")])
        commands.append([node, "--test", "tests/browser-transfer.test.cjs"])
        commands.append([node, "--test", "tests/content-panel.test.cjs"])
    for command in commands:
        log("==> Checking: " + " ".join(command[1:]))
        result = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.stdout.strip():
            log(result.stdout.strip())
        if result.stderr.strip():
            log(result.stderr.strip())
        if result.returncode:
            raise RuntimeError("Release validation failed; build and publication were stopped")


def compute_snapshot() -> dict:
    """Computes SHA-256 of watched source files, ignoring APP_VERSION & CHANGELOG_HISTORY so version bumps never loop."""
    snap = {}
    for p in WATCH_TARGETS:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                if p.endswith("scorpion_qt.py"):
                    txt = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', 'APP_VERSION = ""', txt, count=1)
                    txt = re.sub(r'CHANGELOG_HISTORY\s*=\s*\[.*?\n\]', 'CHANGELOG_HISTORY = []', txt, count=1, flags=re.S)
                snap[p] = hashlib.sha256(txt.encode("utf-8")).hexdigest()
            except Exception:
                pass
    return snap


def read_current_version() -> str:
    qt_file = os.path.join(PROJECT_ROOT, "native_app", "scorpion_qt.py")
    try:
        with open(qt_file, "r", encoding="utf-8") as f:
            txt = f.read(12000)
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', txt)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "2.1.1"


def bump_patch_version(ver: str) -> str:
    parts = [int(x) if x.isdigit() else 0 for x in ver.strip().lstrip("vV").split(".")]
    while len(parts) < 3:
        parts.append(0)
    parts[-1] += 1
    return ".".join(str(x) for x in parts)


def _py_str(s: str) -> str:
    # JSON string literals are valid Python string literals
    return json.dumps(s, ensure_ascii=False)


def update_version_in_source(new_ver: str, note_ar: str, note_en: str):
    """Sets APP_VERSION and adds a CHANGELOG_HISTORY entry for new_ver (each release keeps its own notes)."""
    qt_file = os.path.join(PROJECT_ROOT, "native_app", "scorpion_qt.py")
    with open(qt_file, "r", encoding="utf-8") as f:
        content = f.read().replace("\r\n", "\n")

    content = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', f'APP_VERSION = "{new_ver}"', content, count=1)

    # Several notes can be typed on one line, separated by "|"
    notes_ar = [n.strip() for n in re.split(r"[\n|]", note_ar) if n.strip()]
    notes_en = [n.strip() for n in re.split(r"[\n|]", note_en or note_ar) if n.strip()]
    top = re.search(r'CHANGELOG_HISTORY\s*=\s*\[\s*\{\s*"version":\s*"([^"]+)"', content)
    prewritten = bool(top and top.group(1) == new_ver)
    # A release whose notes were already written keeps them as they are; never pad them with a generic line
    if not notes_ar and not prewritten:
        notes_ar, notes_en = ["تحسينات وإصلاحات عامة."], ["General improvements and fixes."]

    if prewritten:
        # Same version published again (no bump): add the new notes to its existing entry
        for key, notes in (("ar", notes_ar), ("en", notes_en)):
            new_lines = "".join(f"            {_py_str(n)},\n" for n in notes if _py_str(n) not in content)
            content = re.sub(rf'("{key}":\s*\[\n)', lambda m: m.group(1) + new_lines, content, count=1)
    else:
        today = time.strftime("%Y-%m-%d")
        entry = (
            "    {\n"
            f'        "version": "{new_ver}",\n'
            f'        "date": "{today}",\n'
            f'        "title_ar": {_py_str(f"الإصدار {new_ver}")},\n'
            f'        "title_en": {_py_str(f"Version {new_ver}")},\n'
            '        "ar": [\n' + "".join(f"            {_py_str(n)},\n" for n in notes_ar) + "        ],\n"
            '        "en": [\n' + "".join(f"            {_py_str(n)},\n" for n in notes_en) + "        ],\n"
            "    },\n"
        )
        content = re.sub(r"(CHANGELOG_HISTORY\s*=\s*\[\n)", lambda m: m.group(1) + entry, content, count=1)

    with open(qt_file, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def run_git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def find_gh() -> str:
    for cand in (shutil.which("gh"), r"C:\Program Files\GitHub CLI\gh.exe"):
        if cand and os.path.isfile(cand):
            return cand
    return ""


def desktop_app_environment():
    """The publisher's headless Qt platform must never leak into the desktop app."""
    return {key: value for key, value in os.environ.items() if key.upper() != "QT_QPA_PLATFORM"}


def wait_for_desktop_app(version, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:19615/ping", timeout=1) as response:
                status = json.load(response)
            if status.get("version") == version and status.get("uiReady") and status.get("uiPlatform") == "windows" and status.get("uiVisible"):
                return
        except Exception:
            pass
        time.sleep(0.25)
    raise RuntimeError("لم تظهر واجهة البرنامج بعد التحديث. تم إيقاف النشر؛ راجع تشغيل النسخة المثبتة.")


def publish_tools_pack(version: str, pack_path: str, log) -> None:
    """Uploads the tools pack as release 'tools-<version>' unless that release already exists."""
    gh = find_gh()
    if not gh:
        raise RuntimeError("أداة GitHub CLI (gh) غير مثبتة — مطلوبة لرفع حزمة الأدوات (winget install GitHub.cli ثم gh auth login)")
    tag = f"tools-{version}"
    run = lambda *a: subprocess.run(
        [gh, *a], cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if run("release", "view", tag).returncode == 0:
        log(f"==> Tools pack {tag} already published")
        return
    log(f"==> Uploading tools pack {tag} ({os.path.getsize(pack_path) // (1024 * 1024)} MB)...")
    res = run("release", "create", tag, pack_path, "--title", f"Tools {version}",
              "--notes", "Bundled programs (ffmpeg, ffprobe, QuickJS) downloaded by the app.",
              # Pre-release: GitHub must never report it as the latest release (apps read that as an update)
              "--prerelease", "--latest=false")
    if res.returncode != 0:
        raise RuntimeError(f"تعذر رفع حزمة الأدوات: {(res.stderr or res.stdout).strip()[:160]}")


def ensure_on_up_to_date_main():
    """Releases are only built from main, synced with GitHub; otherwise the push silently sends nothing."""
    branch = run_git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != "main":
        raise RuntimeError(
            f"المشروع حالياً على الفرع «{branch}» وليس main — بدّل إلى main أولاً (git switch main) ثم أعد المحاولة"
        )
    fetch = run_git("fetch", "origin", "main")
    if fetch.returncode != 0:
        raise RuntimeError(f"تعذر الاتصال بـ GitHub: {fetch.stderr.strip()[:160]}")
    pull = run_git("merge", "--ff-only", "origin/main")
    if pull.returncode != 0:
        raise RuntimeError(f"فرع main المحلي مختلف عن GitHub ولا يمكن تحديثه تلقائياً: {pull.stderr.strip()[:160]}")


def stop_running_scorpion():
    """Requests ScorpionIDM.exe to quit cleanly via RPC and waits until its files are unlocked."""
    try:
        # The bridge only accepts /quit as a GET carrying the trusted-client header
        req = urllib.request.Request("http://127.0.0.1:19615/quit", headers={"X-Scorpion-Client": "1"})
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass
    for _ in range(16):
        time.sleep(0.35)
        try:
            urllib.request.urlopen("http://127.0.0.1:19615/ping", timeout=0.4).read()
        except Exception:
            break
    time.sleep(0.6)


def copy_tree_safely(src_dir: str, dst_dir: str):
    """
    Copies all files from src_dir to dst_dir safely on Windows.
    If any target .exe / .dll / .pyd is still locked by Windows, renames it to .old_<timestamp>
    in-place first so PermissionError never occurs.
    """
    if not os.path.isdir(src_dir):
        return
    ts = int(time.time() * 1000)
    idx = 0
    for root, dirs, files in os.walk(src_dir):
        rel = os.path.relpath(root, src_dir)
        target_root = dst_dir if rel == "." else os.path.join(dst_dir, rel)
        os.makedirs(target_root, exist_ok=True)
        for fn in files:
            idx += 1
            s_file = os.path.join(root, fn)
            d_file = os.path.join(target_root, fn)
            if os.path.exists(d_file):
                try:
                    os.remove(d_file)
                except PermissionError:
                    stale = f"{d_file}.old_{ts}_{idx}"
                    try:
                        if os.path.exists(stale):
                            os.remove(stale)
                    except Exception:
                        pass
                    try:
                        os.replace(d_file, stale)
                    except Exception:
                        continue
            try:
                shutil.copy2(s_file, d_file)
            except PermissionError:
                stale = f"{d_file}.old_{ts}_{idx}"
                try:
                    os.replace(d_file, stale)
                    shutil.copy2(s_file, d_file)
                except Exception:
                    pass


class PublisherSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)


class AutoPublisherWindow(QMainWindow):
    def __init__(self, auto_run_now: bool = False):
        super().__init__()
        self.signals = PublisherSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self._on_progress)
        self.signals.finished.connect(self._on_finished)

        self.is_building = False
        self.last_snapshot = compute_snapshot()
        self.pending_change_time = None

        self.setWindowTitle("Scorpion IDM — أداة البناء والرفع التلقائي على GitHub")
        icon_p = os.path.join(PROJECT_ROOT, "build", "icon.ico")
        if os.path.exists(icon_p):
            self.setWindowIcon(QIcon(icon_p))
        self.resize(680, 540)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

        self.setStyleSheet("""
            * { font-family: "Segoe UI", Tahoma; font-size: 13px; color: #1f2430; }
            QMainWindow { background: #f4f5f7; }
            QFrame#Card { background: #ffffff; border: 1px solid #e2e5ea; border-radius: 10px; }
            QPushButton { background: #ffffff; border: 1px solid #d1d5db; border-radius: 7px; padding: 8px 16px; font-weight: 600; }
            QPushButton:hover { background: #f1f3f6; }
            QPushButton#Primary { background: #2563eb; border-color: #2563eb; color: #ffffff; }
            QPushButton#Primary:hover { background: #1d4ed8; }
            QLineEdit, QTextEdit { background: #ffffff; border: 1px solid #d1d5db; border-radius: 7px; padding: 6px 10px; }
            QProgressBar { background: #e7eaef; border: none; border-radius: 5px; text-align: center; font-weight: 600; }
            QProgressBar::chunk { background: #2563eb; border-radius: 5px; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header Card
        hdr_card = QFrame()
        hdr_card.setObjectName("Card")
        hl = QVBoxLayout(hdr_card)
        hl.setContentsMargins(16, 12, 16, 12)
        title = QLabel("🚀 أداة المراقبة والرفع التلقائي لمشروع Scorpion IDM على GitHub")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #2563eb;")
        sub = QLabel(
            f"المستودع المربوط: {REPO_URL}\n"
            "تقوم هذه الأداة ببناء النسخة الجديدة وحزمة التحديث ورفعها إلى حسابك على GitHub ليصل التحديث فوراً لكل أجهزتك."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #6b7280;")
        hl.addWidget(title)
        hl.addWidget(sub)
        root.addWidget(hdr_card)

        # Controls Card
        ctrl_card = QFrame()
        ctrl_card.setObjectName("Card")
        cl = QVBoxLayout(ctrl_card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(8)

        row1 = QHBoxLayout()
        self.lbl_ver = QLabel(f"الإصدار الحالي: v{read_current_version()}")
        self.lbl_ver.setStyleSheet("font-weight: 700; font-size: 14px;")
        row1.addWidget(self.lbl_ver)
        row1.addStretch()

        self.chk_watch = QCheckBox("مراقبة التعديلات في الكود والرفع التلقائي فور الحفظ (Auto-Watch)")
        self.chk_watch.setChecked(True)
        row1.addWidget(self.chk_watch)
        cl.addLayout(row1)

        self.chk_bump = QCheckBox("زيادة رقم الإصدار تلقائياً مع كل رفعة (مثلاً 2.1.1 ← 2.1.2) ليظهر إشعار التحديث على الأجهزة الأخرى")
        self.chk_bump.setChecked(True)
        cl.addWidget(self.chk_bump)

        cl.addWidget(QLabel("وصف التعديل (يظهر للمستخدمين في نافذة «ما الجديد في التحديث»):"))
        self.txt_note = QLineEdit()
        self.txt_note.setPlaceholderText("ما الذي سيلاحظه المستخدم؟ افصل بين النقاط بعلامة |   مثال: تحميل أسرع | إصلاح مشكلة الفيديو")
        cl.addWidget(self.txt_note)
        root.addWidget(ctrl_card)

        # Progress & Log Card
        log_card = QFrame()
        log_card.setObjectName("Card")
        ll = QVBoxLayout(log_card)
        ll.setContentsMargins(16, 12, 16, 12)
        ll.setSpacing(8)

        self.lbl_status = QLabel("👀 جاهز — في وضع المراقبة النشطة أو اضغط زر البناء والرفع بالأسفل.")
        self.lbl_status.setStyleSheet("font-weight: 600;")
        self.lbl_status.setWordWrap(True)
        ll.addWidget(self.lbl_status)

        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        self.prog.setValue(0)
        self.prog.setFixedHeight(20)
        ll.addWidget(self.prog)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.txt_log.setFont(QFont("Consolas", 10))
        ll.addWidget(self.txt_log, 1)
        root.addWidget(log_card, 1)

        # Action Buttons
        btns = QHBoxLayout()
        self.btn_publish = QPushButton("🚀 بناء ورفع التحديث إلى GitHub الآن")
        self.btn_publish.setObjectName("Primary")
        self.btn_publish.clicked.connect(lambda: self.trigger_build_and_publish("يدوي"))
        btns.addWidget(self.btn_publish)
        btns.addStretch()
        btn_close = QPushButton("إغلاق")
        btn_close.clicked.connect(self.close)
        btns.addWidget(btn_close)
        root.addLayout(btns)

        # File watcher timer (checks every 2 seconds)
        self.watch_timer = QTimer(self)
        self.watch_timer.timeout.connect(self._check_file_changes)
        self.watch_timer.start(2000)

        if auto_run_now:
            QTimer.singleShot(500, lambda: self.trigger_build_and_publish("تلقائي"))

    def _append_log(self, line: str):
        self.txt_log.append(line)

    def _on_progress(self, pct: int, status: str):
        self.prog.setValue(pct)
        self.lbl_status.setText(status)

    def _on_finished(self, ok: bool, msg: str):
        self.is_building = False
        self.btn_publish.setEnabled(True)
        self.last_snapshot = compute_snapshot()
        self.pending_change_time = None
        self.lbl_ver.setText(f"الإصدار الحالي: v{read_current_version()}")
        if ok:
            self.prog.setValue(100)
            self.lbl_status.setText(f"✅ {msg}")
            self.txt_note.clear()
        else:
            self.lbl_status.setText(f"❌ {msg[:220]}")

    def _check_file_changes(self):
        if self.is_building or not self.chk_watch.isChecked():
            return
        cur = compute_snapshot()
        if cur != self.last_snapshot:
            changed = [
                os.path.basename(k)
                for k in cur
                if cur.get(k) != self.last_snapshot.get(k)
            ]
            self.last_snapshot = cur
            self.pending_change_time = time.time()
            self._append_log(f"[Watcher] Detected modification in: {', '.join(changed)}")
            self.lbl_status.setText(f"⏳ تم رصد تعديل في ({', '.join(changed)}) — سيبدأ البناء والرفع خلال 4 ثوانٍ...")

        if self.pending_change_time and (time.time() - self.pending_change_time >= 4.0):
            self.pending_change_time = None
            self.trigger_build_and_publish("تلقائي بعد تعديل الملفات")

    def trigger_build_and_publish(self, reason: str = ""):
        if self.is_building:
            return
        self.is_building = True
        self.pending_change_time = None
        self.btn_publish.setEnabled(False)
        self.prog.setValue(5)
        note_ar = self.txt_note.text().strip()
        do_bump = self.chk_bump.isChecked()

        def worker():
            try:
                self.signals.progress.emit(7, "جاري التأكد من أن المشروع على فرع main ومحدّث من GitHub...")
                ensure_on_up_to_date_main()
                self.signals.progress.emit(9, "جاري اختبار إصلاحات الفيديو والإضافة قبل البناء والنشر...")
                validate_release_sources(self.signals.log.emit)
                cur_ver = read_current_version()
                new_ver = bump_patch_version(cur_ver) if do_bump else cur_ver
                if do_bump or note_ar:
                    self.signals.progress.emit(10, f"جاري تحديث رقم الإصدار إلى v{new_ver}...")
                    update_version_in_source(
                        new_ver,
                        note_ar,
                        note_ar,
                    )
                    self.last_snapshot = compute_snapshot()
                    self.signals.log.emit(f"==> Version updated: v{cur_ver} -> v{new_ver}")

                self.signals.progress.emit(20, "جاري إغلاق النسخة المفتوحة وبناء البرنامج وحزمة التحديث...")
                self.signals.log.emit("==> Stopping running ScorpionIDM instance & running build_installer.ps1 ...")
                stop_running_scorpion()

                build_script = os.path.join(PROJECT_ROOT, "build_installer.ps1")
                # Python launched from PowerShell 7 can inherit its Core-only module paths. Let
                # Windows PowerShell discover its own modules, including Authenticode verification.
                build_env = {key: value for key, value in os.environ.items() if key.upper() != "PSMODULEPATH"}
                proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", build_script],
                    cwd=PROJECT_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=build_env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                setup_path = tools_version = tools_pack = ""
                for line in proc.stdout:
                    line_s = line.strip()
                    if line_s.startswith("SETUP_PATH="):
                        setup_path = line_s.split("=", 1)[1]
                    elif line_s.startswith("TOOLS_VERSION="):
                        tools_version = line_s.split("=", 1)[1]
                    elif line_s.startswith("TOOLS_PACK="):
                        tools_pack = line_s.split("=", 1)[1]
                    if line_s:
                        self.signals.log.emit(line_s)
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError("فشل بناء البرنامج وملف التسطيب (راجع السجل بالأعلى)")
                if not setup_path or not os.path.isfile(setup_path):
                    raise RuntimeError("تم البناء لكن لم يتم حفظ ملف التسطيب الجديد في مجلد التنزيلات")
                self.signals.log.emit(f"==> New setup saved: {setup_path}")

                self.signals.progress.emit(65, "جاري تحديث النسخة المثبتة على هذا الجهاز بأمان...")
                stop_running_scorpion()
                src_dist = os.path.join(PROJECT_ROOT, "native_app", "_build", "dist", "ScorpionIDM")
                dst_app = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ScorpionIDM")
                shutil.rmtree(os.path.join(dst_app, "_internal"), ignore_errors=True)
                copy_tree_safely(src_dist, dst_app)

                ext_src = os.path.join(PROJECT_ROOT, "browser-extension")
                for ext_dst in (
                    os.path.join(dst_app, "browser-extension"),
                    os.path.join(os.environ.get("LOCALAPPDATA", ""), "ScorpionIDM", "browser-extension"),
                ):
                    copy_tree_safely(ext_src, ext_dst)

                exe_p = os.path.join(dst_app, "ScorpionIDM.exe")
                if os.path.isfile(exe_p):
                    subprocess.Popen([exe_p], cwd=dst_app, env=desktop_app_environment(),
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    wait_for_desktop_app(new_ver)

                # Clients refuse packages without a matching checksum, so never publish one that would fail
                with open(os.path.join(PROJECT_ROOT, "release", "update.json"), "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                with open(os.path.join(PROJECT_ROOT, "release", "Scorpion-Update-Payload.zip"), "rb") as f:
                    pkg_sha = hashlib.sha256(f.read()).hexdigest()
                if manifest.get("version") != new_ver or manifest.get("sha256") != pkg_sha:
                    raise RuntimeError("ملف update.json لا يطابق حزمة التحديث (الإصدار أو بصمة SHA-256) — تم إيقاف الرفع")
                if not tools_version or not os.path.isfile(tools_pack) or (manifest.get("tools") or {}).get("version") != tools_version:
                    raise RuntimeError("حزمة الأدوات (ffmpeg / QuickJS) غير جاهزة أو لا تطابق update.json — تم إيقاف الرفع")
                self.signals.progress.emit(75, "جاري رفع حزمة الأدوات إن كانت جديدة...")
                publish_tools_pack(tools_version, tools_pack, self.signals.log.emit)

                self.signals.progress.emit(80, "جاري رفع التحديث إلى GitHub (Mahmoud-847/scorpion-idm)...")
                self.signals.log.emit(f"==> Pushing v{new_ver} to {REPO_URL} ...")

                for args in (
                    # Stage only tracked files + release artifacts (never stray/secret files); never rewrite remote history
                    ("add", "-u"),
                    # Only files that exist: a renamed or removed doc/test must not block a release
                    ("add", "--", *[p for p in (
                        "release/update.json", "release/Scorpion-Update-Payload.zip", "release/Scorpion-Browser-Extension.zip",
                        "native_app/media_transfer.py", "browser-extension/media.js", "browser-extension/browser-transfer.js",
                        "browser-extension/telegram-reader.js",
                        "VIDEO_DOWNLOADS.md",
                        "tests/test_media_transfer.py", "tests/browser-transfer.test.cjs", "tests/test_publisher_startup.py",
                        "tests/content-panel.test.cjs", "tests/package.json", "tests/package-lock.json",
                    ) if os.path.exists(os.path.join(PROJECT_ROOT, p))]),
                    ("commit", "-m", f"Release Scorpion IDM v{new_ver}", "--allow-empty"),
                    ("push", "-u", "origin", "main"),
                ):
                    self.signals.log.emit("$ git " + " ".join(args))
                    p_git = run_git(*args)
                    if p_git.stdout.strip():
                        self.signals.log.emit(p_git.stdout.strip())
                    if p_git.stderr.strip():
                        self.signals.log.emit(p_git.stderr.strip())
                    if p_git.returncode != 0:
                        raise RuntimeError(
                            f"تعذر تنفيذ git {args[0]}: {(p_git.stderr or p_git.stdout).strip()[:160]}"
                        )

                # Confirm GitHub's main really has this release commit
                run_git("fetch", "origin", "main")
                local_head = run_git("rev-parse", "HEAD").stdout.strip()
                remote_head = run_git("rev-parse", "origin/main").stdout.strip()
                if not local_head or local_head != remote_head:
                    raise RuntimeError("تم البناء لكن التحديث لم يصل إلى فرع main على GitHub — راجع السجل")

                self.last_snapshot = compute_snapshot()
                self.signals.finished.emit(
                    True,
                    f"تم بناء ورفع الإصدار v{new_ver} إلى GitHub بنجاح! سيظهر التحديث الآن على كل أجهزتك."
                    f"\nملف التسطيب الجديد: {setup_path}",
                )
            except Exception as e:
                self.signals.log.emit(f"[ERROR] {e}")
                self.signals.finished.emit(False, str(e))

        threading.Thread(target=worker, daemon=True).start()


def ensure_publisher_shortcut():
    """Creates a Desktop shortcut for Scorpion Auto-Publisher via pure-Python Win32 COM."""
    if os.name != "nt":
        return
    from ctypes import wintypes

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    try:
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8),
            ]

            def __init__(self, d1, d2, d3, d4):
                super().__init__(d1, d2, d3, (wintypes.BYTE * 8)(*d4))

        CLSID_ShellLink = GUID(0x00021401, 0, 0, [0xC0, 0, 0, 0, 0, 0, 0, 0x46])
        IID_IShellLinkW = GUID(0x000214F9, 0, 0, [0xC0, 0, 0, 0, 0, 0, 0, 0x46])
        IID_IPersistFile = GUID(0x0000010B, 0, 0, [0xC0, 0, 0, 0, 0, 0, 0, 0x46])
        psl = ctypes.c_void_p()
        if ole32.CoCreateInstance(
            ctypes.byref(CLSID_ShellLink), None, 1, ctypes.byref(IID_IShellLinkW), ctypes.byref(psl)
        ) != 0:
            return
        vtbl = ctypes.cast(ctypes.cast(psl, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        WSTRING_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        ICON_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int)
        QI_FN = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
        )
        REL_FN = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)

        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        target = pyw if os.path.exists(pyw) else sys.executable
        script = os.path.abspath(__file__)
        ico = os.path.join(PROJECT_ROOT, "build", "icon.ico")
        lnk = os.path.join(os.path.expanduser("~"), "Desktop", "Scorpion Auto-Publisher.lnk")

        WSTRING_FN(vtbl[20])(psl, target)
        WSTRING_FN(vtbl[11])(psl, f'"{script}"')
        WSTRING_FN(vtbl[9])(psl, PROJECT_ROOT)
        WSTRING_FN(vtbl[7])(psl, "Scorpion Auto-Publisher (GitHub)")
        ICON_FN(vtbl[17])(psl, ico if os.path.exists(ico) else target, 0)

        ppf = ctypes.c_void_p()
        if QI_FN(vtbl[0])(psl, ctypes.byref(IID_IPersistFile), ctypes.byref(ppf)) == 0 and ppf:
            ppf_vtbl = ctypes.cast(
                ctypes.cast(ppf, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p)
            )
            SAVE_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.BOOL)
            SAVE_FN(ppf_vtbl[6])(ppf, lnk, True)
            REL_FN(ppf_vtbl[2])(ppf)
        REL_FN(vtbl[2])(psl)
    except Exception:
        pass
    finally:
        ole32.CoUninitialize()


_LOCK_SOCK = None


if __name__ == "__main__":
    once = "--once" in sys.argv
    if once:
        # A single logged publication is also usable from a terminal or CI without an interactive window.
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    ensure_publisher_shortcut()
    try:
        _LOCK_SOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _LOCK_SOCK.bind(("127.0.0.1", 19616))
        _LOCK_SOCK.listen(1)
    except OSError:
        sys.exit(0)
    app = QApplication(sys.argv)
    win = AutoPublisherWindow(auto_run_now="--now" in sys.argv or once)
    if "--no-bump" in sys.argv:
        win.chk_bump.setChecked(False)
    if once:
        win.chk_watch.setChecked(False)
        win.signals.log.connect(lambda message: print(message, flush=True))
        win.signals.progress.connect(lambda percent, message: print(f"[{percent}%] {message}", flush=True))
        win.signals.finished.connect(lambda ok, message: (print(message, flush=True), app.exit(0 if ok else 1)))
    else:
        win.show()
    sys.exit(app.exec())
