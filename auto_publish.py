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
    os.path.join(PROJECT_ROOT, "native_app", "installer", "scorpion_setup.py"),
    os.path.join(PROJECT_ROOT, "browser-extension", "manifest.json"),
    os.path.join(PROJECT_ROOT, "browser-extension", "background.js"),
    os.path.join(PROJECT_ROOT, "browser-extension", "content.js"),
    os.path.join(PROJECT_ROOT, "browser-extension", "content.css"),
    os.path.join(PROJECT_ROOT, "browser-extension", "popup.html"),
    os.path.join(PROJECT_ROOT, "browser-extension", "popup.js"),
]


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


def update_version_in_source(new_ver: str, note_ar: str, note_en: str):
    qt_file = os.path.join(PROJECT_ROOT, "native_app", "scorpion_qt.py")
    with open(qt_file, "r", encoding="utf-8") as f:
        content = f.read().replace("\r\n", "\n")

    content = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', f'APP_VERSION = "{new_ver}"', content, count=1)

    today = time.strftime("%Y-%m-%d")
    content = re.sub(
        r'("version":\s*)"[^"]+"(\s*,\s*"date":\s*)"[^"]+"(\s*,\s*"title_ar":\s*)"[^"]+"(\s*,\s*"title_en":\s*)"[^"]+"',
        f'\\g<1>"{new_ver}"\\g<2>"{today}"\\g<3>"الإصدار {new_ver} — تحديث جديد"\\g<4>"Version {new_ver} — New Update"',
        content,
        count=1,
    )
    if note_ar.strip():
        escaped_ar = note_ar.strip().replace('"', '\\"')
        escaped_en = (note_en.strip() or note_ar.strip()).replace('"', '\\"')
        if f'"{escaped_ar}"' not in content:
            content = re.sub(
                r'("ar":\s*\[\s*)',
                f'\\g<1>"{escaped_ar}",\n            ',
                content,
                count=1,
            )
        if f'"{escaped_en}"' not in content:
            content = re.sub(
                r'("en":\s*\[\s*)',
                f'\\g<1>"{escaped_en}",\n            ',
                content,
                count=1,
            )

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
        self.txt_note.setPlaceholderText("مثال: تحسين سرعة التحميل وإصلاح بعض الأخطاء...")
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
                proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", build_script],
                    cwd=PROJECT_ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                setup_path = ""
                for line in proc.stdout:
                    line_s = line.strip()
                    if line_s.startswith("SETUP_PATH="):
                        setup_path = line_s.split("=", 1)[1]
                    if line_s:
                        self.signals.log.emit(line_s)
                proc.wait()
                if proc.returncode != 0:
                    raise RuntimeError("فشل بناء البرنامج عبر PyInstaller")
                if not setup_path or not os.path.isfile(setup_path):
                    raise RuntimeError("تم البناء لكن لم يتم حفظ ملف التسطيب الجديد في مجلد التنزيلات")
                self.signals.log.emit(f"==> New setup saved: {setup_path}")

                self.signals.progress.emit(65, "جاري تحديث النسخة المثبتة على هذا الجهاز بأمان...")
                stop_running_scorpion()
                src_dist = os.path.join(PROJECT_ROOT, "native_app", "_build", "dist", "ScorpionIDM")
                dst_app = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ScorpionIDM")
                copy_tree_safely(src_dist, dst_app)

                ext_src = os.path.join(PROJECT_ROOT, "browser-extension")
                for ext_dst in (
                    os.path.join(dst_app, "browser-extension"),
                    os.path.join(os.environ.get("LOCALAPPDATA", ""), "ScorpionIDM", "browser-extension"),
                ):
                    copy_tree_safely(ext_src, ext_dst)

                exe_p = os.path.join(dst_app, "ScorpionIDM.exe")
                if os.path.isfile(exe_p):
                    subprocess.Popen([exe_p], cwd=dst_app)

                # Clients refuse packages without a matching checksum, so never publish one that would fail
                with open(os.path.join(PROJECT_ROOT, "release", "update.json"), "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                with open(os.path.join(PROJECT_ROOT, "release", "Scorpion-Update-Payload.zip"), "rb") as f:
                    pkg_sha = hashlib.sha256(f.read()).hexdigest()
                if manifest.get("version") != new_ver or manifest.get("sha256") != pkg_sha:
                    raise RuntimeError("ملف update.json لا يطابق حزمة التحديث (الإصدار أو بصمة SHA-256) — تم إيقاف الرفع")

                self.signals.progress.emit(80, "جاري رفع التحديث إلى GitHub (Mahmoud-847/scorpion-idm)...")
                self.signals.log.emit(f"==> Pushing v{new_ver} to {REPO_URL} ...")

                for args in (
                    # Stage only tracked files + release artifacts (never stray/secret files); never rewrite remote history
                    ("add", "-u"),
                    ("add", "--", "release/update.json", "release/Scorpion-Update-Payload.zip"),
                    ("commit", "-m", f"Release Scorpion IDM v{new_ver}", "--allow-empty"),
                    ("push", "-u", "origin", "main"),
                ):
                    self.signals.log.emit("$ git " + " ".join(args))
                    p_git = run_git(*args)
                    if p_git.stdout.strip():
                        self.signals.log.emit(p_git.stdout.strip())
                    if p_git.stderr.strip():
                        self.signals.log.emit(p_git.stderr.strip())
                    if args[0] in ("commit", "push") and p_git.returncode != 0:
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
    ensure_publisher_shortcut()
    try:
        _LOCK_SOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _LOCK_SOCK.bind(("127.0.0.1", 19616))
        _LOCK_SOCK.listen(1)
    except OSError:
        sys.exit(0)
    app = QApplication(sys.argv)
    win = AutoPublisherWindow(auto_run_now="--now" in sys.argv)
    win.show()
    sys.exit(app.exec())
