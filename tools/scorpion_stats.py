"""Scorpion Stats: live download and user counts for Scorpion Download Manager.

Admin tool for the publisher's PC (not shipped with the app). It refreshes by itself every few
minutes and on demand, and shows how much each number changed since it was last seen.

Sources (all public, no sign-in):
- GitHub releases: download count of every installer, extension and update package.
- Microsoft Edge Add-ons: active users, rating and number of ratings of the extension.
- Microsoft Store: rating of the app. Store download counts are not public: they need the
  Partner Center analytics API, so the window links to the analytics page instead.
"""
import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser

try:  # Windows certificate store (works behind HTTPS-inspecting antivirus)
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)

REPO = "Mahmoud-847/scorpion-idm"
EDGE_CRX_ID = "hgcdbjpjlfgnejhceobphikeebmhmgcj"
STORE_ID = "9N3ZB1H6C77W"
REFRESH_MINUTES = 5
DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ScorpionStats")
HISTORY = os.path.join(DATA_DIR, "history.json")
ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "icon.ico")

LINKS = {
    "github": f"https://github.com/{REPO}/releases",
    "edge": "https://partner.microsoft.com/dashboard/microsoftedge/overview",
    "store": f"https://partner.microsoft.com/dashboard/products/{STORE_ID}/analytics",
}


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "ScorpionStats", "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)


def fetch_github():
    releases, page = [], 1
    while True:
        batch = get_json(f"https://api.github.com/repos/{REPO}/releases?per_page=100&page={page}")
        releases += batch
        if len(batch) < 100:
            break
        page += 1
    setup = ext = update = 0
    latest_setup = None
    for rel in releases:
        for asset in rel.get("assets", []):
            name, n = asset.get("name", ""), int(asset.get("download_count") or 0)
            if name.startswith("Scorpion-Setup"):
                setup += n
                if latest_setup is None:  # releases come newest first
                    latest_setup = (rel.get("tag_name", ""), n)
            elif name.startswith("Scorpion-Browser-Extension"):
                ext += n
            elif name.startswith("Scorpion-Update-Payload"):
                update += n
    return {"setup": setup, "ext_zip": ext, "update_pkg": update,
            "latest_tag": latest_setup[0] if latest_setup else "", "latest_setup": latest_setup[1] if latest_setup else 0}


def fetch_edge():
    d = get_json(f"https://microsoftedge.microsoft.com/addons/getproductdetailsbycrxid/{EDGE_CRX_ID}")
    return {"users": int(d.get("activeInstallCount") or 0), "rating": float(d.get("averageRating") or 0),
            "ratings": int(d.get("ratingCount") or 0), "version": d.get("version") or ""}


def fetch_store():
    d = get_json(f"https://storeedgefd.dsx.mp.microsoft.com/v9.0/products/{STORE_ID}"
                 "?market=EG&locale=en-us&deviceFamily=Windows.Desktop")
    p = d.get("Payload") or d
    return {"rating": float(p.get("AverageRating") or 0), "ratings": int(p.get("RatingCount") or 0)}


def load_history():
    try:
        with open(HISTORY, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_history(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = HISTORY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, HISTORY)


class Fetcher(QObject):
    done = pyqtSignal(dict)

    def run(self):
        result = {"at": time.time()}
        for key, fn in (("github", fetch_github), ("edge", fetch_edge), ("store", fetch_store)):
            try:
                result[key] = fn()
            except Exception as err:  # one source failing must not hide the others
                result[key] = {"error": str(err)[:120]}
        self.done.emit(result)


CSS = """
QWidget { background: #111116; color: #f0e7da; font-family: 'Segoe UI'; }
QFrame#card { background: #1b1813; border: 1px solid #4a3418; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QLabel#bigtext { font-size: 18pt; font-weight: 800; color: #ffffff; }
QLabel#title { color: #ffb347; font-size: 13pt; font-weight: 700; }
QLabel#big { font-size: 30pt; font-weight: 800; color: #ffffff; }
QLabel#delta { font-size: 11pt; font-weight: 700; color: #45d97d; }
QLabel#sub { color: #b9ad9c; font-size: 10pt; }
QLabel#err { color: #ff6b61; font-size: 10pt; }
QPushButton { background: #2a2016; border: 1px solid #62451e; border-radius: 8px; padding: 7px 14px; color: #ffd29b; font-weight: 600; }
QPushButton:hover { background: #3a2b1a; }
QPushButton#primary { background: #ffab47; color: #1b1005; border: none; }
QPushButton#primary:hover { background: #ffbf70; }
"""


class Card(QFrame):
    def __init__(self, title, link_key):
        super().__init__()
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        top = QHBoxLayout()
        t = QLabel(title)
        t.setObjectName("title")
        top.addWidget(t)
        top.addStretch()
        open_btn = QPushButton("فتح ↗")
        open_btn.clicked.connect(lambda: webbrowser.open(LINKS[link_key]))
        top.addWidget(open_btn)
        lay.addLayout(top)
        row = QHBoxLayout()
        self.big = QLabel("…")
        self.big.setObjectName("big")
        self.delta = QLabel("")
        self.delta.setObjectName("delta")
        row.addWidget(self.big)
        row.addWidget(self.delta, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch()
        lay.addLayout(row)
        self.caption = QLabel("")
        self.caption.setObjectName("sub")
        lay.addWidget(self.caption)
        self.sub = QLabel("")
        self.sub.setObjectName("sub")
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)
        lay.addStretch()

    def set_values(self, value, caption, sub, delta=0, error=""):
        if error:
            self.big.setText("—")
            self.delta.setText("")
            self.caption.setText("تعذّر التحديث")
            self.sub.setObjectName("err")
            self.sub.setText(error)
        else:
            self.big.setText(value)
            # Long text (like "no ratings yet") uses a smaller size than a number
            self.big.setObjectName("big" if len(value) <= 12 else "bigtext")
            self.big.style().unpolish(self.big)
            self.big.style().polish(self.big)
            self.delta.setText(f"+{delta:,}" if delta > 0 else "")
            self.caption.setText(caption)
            self.sub.setObjectName("sub")
            self.sub.setText(sub)
        self.sub.style().unpolish(self.sub)
        self.sub.style().polish(self.sub)


class StatsWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scorpion Stats")
        if os.path.isfile(ICON):
            self.setWindowIcon(QIcon(ICON))
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(CSS)
        self.resize(900, 520)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        head = QHBoxLayout()
        h = QLabel("إحصائيات Scorpion Download Manager")
        h.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        head.addWidget(h)
        head.addStretch()
        self.status = QLabel("")
        self.status.setObjectName("sub")
        head.addWidget(self.status)
        self.refresh_btn = QPushButton("تحديث الآن")
        self.refresh_btn.setObjectName("primary")
        self.refresh_btn.clicked.connect(self.refresh)
        head.addWidget(self.refresh_btn)
        root.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.c_setup = Card("تحميل البرنامج من GitHub", "github")
        self.c_edge = Card("مستخدمي الإضافة على Edge", "edge")
        self.c_store = Card("متجر Microsoft", "store")
        self.c_extzip = Card("ملفات أخرى على GitHub", "github")
        grid.addWidget(self.c_setup, 0, 0)
        grid.addWidget(self.c_edge, 0, 1)
        grid.addWidget(self.c_store, 1, 0)
        grid.addWidget(self.c_extzip, 1, 1)
        root.addLayout(grid, 1)

        self.history = load_history()
        self.fetcher = Fetcher()
        self.fetcher.done.connect(self.apply)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MINUTES * 60 * 1000)
        if self.history.get("last"):
            self.apply(self.history["last"], from_cache=True)
        QTimer.singleShot(200, self.refresh)

    def refresh(self):
        if not self.refresh_btn.isEnabled():
            return
        self.refresh_btn.setEnabled(False)
        self.status.setText("جاري التحديث…")
        threading.Thread(target=self.fetcher.run, daemon=True).start()

    def _delta(self, path, value):
        """Change since the value seen in the previous session."""
        base = self.history.get("baseline", {}).get(path)
        return value - base if isinstance(base, (int, float)) else 0

    def apply(self, data, from_cache=False):
        gh, edge, store = data.get("github", {}), data.get("edge", {}), data.get("store", {})
        if "error" in gh:
            self.c_setup.set_values("", "", "", error=gh["error"])
            self.c_extzip.set_values("", "", "", error=gh["error"])
        else:
            self.c_setup.set_values(f"{gh['setup']:,}", "مرة تحميل لملف التسطيب (exe)، كل الإصدارات",
                              f"آخر إصدار {gh['latest_tag']}: {gh['latest_setup']:,} تحميل", self._delta("setup", gh["setup"]))
            self.c_extzip.set_values(f"{gh['ext_zip']:,}", "تحميل لملف الإضافة اليدوي (zip)",
                               f"حزم التحديث داخل البرنامج: {gh['update_pkg']:,}", self._delta("ext_zip", gh["ext_zip"]))
        if "error" in edge:
            self.c_edge.set_values("", "", "", error=edge["error"])
        else:
            stars = f"{edge['rating']:.1f} ★ من {edge['ratings']} تقييم" if edge["ratings"] else "لا توجد تقييمات بعد"
            self.c_edge.set_values(f"{edge['users']:,}", "مستخدم نشط حاليًا",
                             f"{stars}  •  النسخة المنشورة {edge['version']}", self._delta("edge_users", edge["users"]))
        if "error" in store:
            self.c_store.set_values("", "", "", error=store["error"])
        else:
            stars = f"{store['rating']:.1f} ★ من {store['ratings']} تقييم" if store["ratings"] else "لا توجد تقييمات بعد"
            self.c_store.set_values(stars, "التقييم في المتجر",
                              "عدد التحميلات من المتجر غير متاح للعامة. اضغط «فتح» لرؤيته في Partner Center ← Analytics.")
        when = time.strftime("%H:%M", time.localtime(data.get("at", time.time())))
        self.status.setText(("آخر بيانات محفوظة " if from_cache else "آخر تحديث ") + when +
                            f"  •  تحديث تلقائي كل {REFRESH_MINUTES} دقائق")
        if from_cache:
            return
        self.refresh_btn.setEnabled(True)
        # The "+n" next to each number counts what changed since the window was opened
        baseline = self.history.setdefault("baseline", {})
        values = {}
        if "error" not in gh:
            values.update(setup=gh["setup"], ext_zip=gh["ext_zip"])
        if "error" not in edge:
            values["edge_users"] = edge["users"]
        for k, v in values.items():
            baseline.setdefault(k, v)
        self.history["last"] = data
        try:
            save_history(self.history)
        except OSError:
            pass

    def closeEvent(self, event):
        # Next session counts changes from what was last seen
        last = self.history.get("last", {})
        gh, edge = last.get("github", {}), last.get("edge", {})
        base = {}
        if "setup" in gh:
            base.update(setup=gh["setup"], ext_zip=gh["ext_zip"])
        if "users" in edge:
            base["edge_users"] = edge["users"]
        self.history["baseline"] = base
        try:
            save_history(self.history)
        except OSError:
            pass
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = StatsWindow()
    win.show()
    sys.exit(app.exec())
