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
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

try:  # Windows certificate store (works behind HTTPS-inspecting antivirus)
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (QApplication, QDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

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


STORE_CREDS = os.path.join(DATA_DIR, "store_api.json")
STORE_FIRST_DAY = "2026-11-20"  # before the app was in the Store


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows DPAPI: only this Windows user on this PC can decrypt what it encrypts."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    src, out = Blob(len(data), buf), Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out)):  # 0x1: no UI
        raise OSError("Windows could not encrypt or decrypt the Store key")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def save_store_creds(tenant_id, client_id, secret):
    import base64

    os.makedirs(DATA_DIR, exist_ok=True)
    data = {"tenant_id": tenant_id.strip(), "client_id": client_id.strip(),
            "secret": base64.b64encode(_dpapi(secret.strip().encode("utf-8"), True)).decode("ascii")}
    tmp = STORE_CREDS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, STORE_CREDS)


def load_store_creds():
    import base64

    try:
        with open(STORE_CREDS, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["secret"] = _dpapi(base64.b64decode(data["secret"]), False).decode("utf-8")
        return data if data.get("tenant_id") and data.get("client_id") and data.get("secret") else None
    except (OSError, ValueError, KeyError):
        return None


def store_token(creds):
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": creds["client_id"],
                                   "client_secret": creds["secret"],
                                   "resource": "https://manage.devcenter.microsoft.com"}).encode()
    req = urllib.request.Request(f"https://login.microsoftonline.com/{urllib.parse.quote(creds['tenant_id'])}/oauth2/token",
                                 data=body, headers={"User-Agent": "ScorpionStats"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)["access_token"]


def fetch_store_acquisitions(creds):
    """Daily acquisitions from the Microsoft Store analytics API (data can lag up to 72 hours)."""
    token = store_token(creds)
    end = time.strftime("%Y-%m-%d", time.gmtime())
    url = ("https://manage.devcenter.microsoft.com/v1.0/my/analytics/appacquisitions"
           f"?applicationId={STORE_ID}&startDate={STORE_FIRST_DAY}&endDate={end}&top=10000&aggregationLevel=day")
    days = {}
    while url:
        d = get_json(url, {"Authorization": f"Bearer {token}"})
        for row in d.get("Value") or []:
            day = (row.get("date") or "")[:10]
            days[day] = days.get(day, 0) + int(row.get("acquisitionQuantity") or 0)
        nxt = d.get("@nextLink")
        url = ("https://manage.devcenter.microsoft.com/v1.0/my/analytics/" + nxt) if nxt and not nxt.startswith("http") else nxt
    today = time.strftime("%Y-%m-%d", time.gmtime())
    week_ago = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 6 * 86400))
    return {"total": sum(days.values()), "today": days.get(today, 0),
            "week": sum(v for k, v in days.items() if k >= week_ago),
            "last_day": max((k for k, v in days.items() if v), default="")}


def fetch_store():
    d = get_json(f"https://storeedgefd.dsx.mp.microsoft.com/v9.0/products/{STORE_ID}"
                 "?market=EG&locale=en-us&deviceFamily=Windows.Desktop")
    p = d.get("Payload") or d
    out = {"rating": float(p.get("AverageRating") or 0), "ratings": int(p.get("RatingCount") or 0)}
    creds = load_store_creds()
    if creds:
        try:
            out["acq"] = fetch_store_acquisitions(creds)
        except urllib.error.HTTPError as err:
            out["acq_error"] = ("المفتاح مرفوض أو منتهي. أعد الربط." if err.code in (400, 401, 403)
                                else f"خطأ من Microsoft ({err.code})")
        except Exception as err:
            out["acq_error"] = str(err)[:120]
    return out


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
QLineEdit { background: #1b1813; border: 1px solid #62451e; border-radius: 6px; padding: 6px; color: #ffffff; }
"""


class StoreLinkDialog(QDialog):
    """Takes the Partner Center Azure AD app values. The secret is kept encrypted with Windows DPAPI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ربط متجر Microsoft")
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.setStyleSheet(CSS)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        info = QLabel("من Partner Center ← الترس ← Account settings ← User management ← Azure AD applications، "
                      "انسخ القيم دي والصقها هنا. المفتاح السري بيتحفظ مشفّر على الجهاز ده بس.")
        info.setWordWrap(True)
        info.setObjectName("sub")
        lay.addWidget(info)
        form = QFormLayout()
        old = load_store_creds() or {}
        self.tenant = QLineEdit(old.get("tenant_id", ""))
        self.client = QLineEdit(old.get("client_id", ""))
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret.setPlaceholderText("محفوظ — اتركه فاضي لو مش هتغيره" if old else "")
        for w in (self.tenant, self.client, self.secret):
            w.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        form.addRow("Tenant ID", self.tenant)
        form.addRow("Client ID", self.client)
        form.addRow("Key (Client secret)", self.secret)
        lay.addLayout(form)
        self.msg = QLabel("")
        self.msg.setObjectName("err")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        self.ok = QPushButton("حفظ واختبار")
        self.ok.setObjectName("primary")
        self.ok.clicked.connect(self.save)
        cancel = QPushButton("إلغاء")
        cancel.clicked.connect(self.reject)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self._old_secret = old.get("secret", "")

    def save(self):
        creds = {"tenant_id": self.tenant.text().strip(), "client_id": self.client.text().strip(),
                 "secret": self.secret.text().strip() or self._old_secret}
        if not all(creds.values()):
            self.msg.setText("لازم القيم التلاتة.")
            return
        self.ok.setEnabled(False)
        self.msg.setText("جاري الاختبار…")
        QApplication.processEvents()
        try:
            store_token(creds)
        except urllib.error.HTTPError as err:
            self.msg.setText(f"Microsoft رفضت القيم ({err.code}). راجع Tenant ID و Client ID والمفتاح.")
            self.ok.setEnabled(True)
            return
        except Exception as err:
            self.msg.setText(f"تعذر الاتصال: {str(err)[:100]}")
            self.ok.setEnabled(True)
            return
        save_store_creds(creds["tenant_id"], creds["client_id"], creds["secret"])
        self.accept()


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
        self.link_btn = QPushButton("ربط متجر Microsoft")
        self.link_btn.clicked.connect(self.link_store)
        head.addWidget(self.link_btn)
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

    def link_store(self):
        if StoreLinkDialog(self).exec():
            QMessageBox.information(self, "تم", "تم ربط المتجر. ممكن تتأخر أرقام Microsoft لحد 72 ساعة.")
            self.refresh()

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
            acq = store.get("acq")
            if acq:
                last = f"  •  آخر يوم فيه بيانات {acq['last_day']}" if acq.get("last_day") else ""
                self.c_store.set_values(f"{acq['total']:,}", "تحميل من المتجر (إجمالي)",
                                        f"النهارده {acq['today']:,}  •  آخر 7 أيام {acq['week']:,}  •  {stars}{last}",
                                        self._delta("store_total", acq["total"]))
            elif store.get("acq_error"):
                self.c_store.set_values(stars, "التقييم في المتجر", "", error="تعذر جلب التحميلات: " + store["acq_error"])
            else:
                self.c_store.set_values(stars, "التقييم في المتجر",
                                        "لعرض عدد التحميلات اضغط «ربط متجر Microsoft» فوق.")
        self.link_btn.setText("إعادة ربط المتجر" if load_store_creds() else "ربط متجر Microsoft")
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
        if store.get("acq"):
            values["store_total"] = store["acq"]["total"]
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
        acq = last.get("store", {}).get("acq")
        if acq:
            base["store_total"] = acq["total"]
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
