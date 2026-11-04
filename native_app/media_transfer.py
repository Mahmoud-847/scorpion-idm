"""Integrity checks and bounded, authenticated uploads from browser-owned media."""
import base64
import json
import math
import os
import re
import subprocess
import threading
import time
import urllib.parse
import uuid


def browser_local_url(url):
    parsed = urllib.parse.urlparse(url or "")
    return parsed.scheme == "blob" or (
        parsed.hostname == "web.telegram.org" and
        re.search(r"/(progressive|stream|download)/", parsed.path, re.I) is not None
    )


def fragment_url(url):
    parsed = urllib.parse.urlparse(url or "")
    if re.search(r"\.(m3u8|mpd)$", parsed.path, re.I):
        return False
    query = urllib.parse.parse_qs(parsed.query)
    return bool(re.search(r"\.(m4s|cmfv|cmfa|ts)$", parsed.path, re.I) or
                re.search(r"(?:^|[/_.-])(?:seg(?:ment)?|frag(?:ment)?|chunk|init)[-_.]?\d*(?:[_.-]|$)", parsed.path, re.I) or
                any(key in query for key in ("bytestart", "byteend")) or
                re.fullmatch(r"\d+-\d+", (query.get("range") or [""])[0]))


def finite_duration(value):
    try:
        number = float(value or 0)
        return number if math.isfinite(number) and number > 0 else 0
    except (ValueError, TypeError):
        return 0


def validate_media(path, ffprobe, expected_duration=0, audio_only=False, expect_audio=False):
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        raise RuntimeError("لم ينتج التنزيل ملف فيديو. أعد تشغيل الفيديو وحاول تاني.")
    if not ffprobe:
        raise RuntimeError("أداة فحص الفيديو غير متاحة. حدّث أدوات البرنامج ثم أعد المحاولة.")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,duration", "-of", "json", path],
        capture_output=True, text=True, timeout=45,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError("الملف المستلم غير قابل للتشغيل أو غير مكتمل. أعد المحاولة من الفيديو نفسه.")
    info = json.loads(result.stdout)
    streams = info.get("streams") or []
    required = "audio" if audio_only else "video"
    if not any(stream.get("codec_type") == required for stream in streams):
        raise RuntimeError("الملف المستلم لا يحتوي على المسار المطلوب. أعد المحاولة من الفيديو نفسه.")
    if expect_audio and not any(stream.get("codec_type") == "audio" for stream in streams):
        raise RuntimeError("التنزيل وصل من غير الصوت الموجود في المصدر. أعد المحاولة.")
    # Check the required track, not just the container: a long audio track can hide truncated video.
    durations = [finite_duration(s.get("duration")) for s in streams if s.get("codec_type") == required]
    duration = max(durations, default=0) or finite_duration((info.get("format") or {}).get("duration"))
    expected = finite_duration(expected_duration)
    tolerance = max(0.5, min(2.0, expected * 0.02))
    if expected and (not duration or duration < expected - tolerance):
        raise RuntimeError("مدة الملف أقصر من الفيديو الأصلي. لم يتم اعتماد الملف كتحميل مكتمل؛ أعد المحاولة من المشغّل.")
    return duration


class BrowserTransferMixin:
    def begin_browser_transfer(self, payload):
        url = str(payload.get("url") or "")
        if not browser_local_url(url) or urllib.parse.urlparse(url).hostname != "web.telegram.org":
            raise ValueError("مصدر التنزيل غير صالح.")
        total = int(payload.get("totalSize") or 0)
        if total <= 0:
            raise ValueError("تعذر معرفة الحجم الكامل للفيديو.")
        with self.lock:
            if self.active_count() >= max(1, int(self.settings.get("maxConcurrent") or 4)):
                raise ValueError("انتظر اكتمال تحميل جارٍ ثم أعد المحاولة من المتصفح.")
            item = self.add_download({
                "url": url, "filename": payload.get("filename") or "Telegram_Video.mp4",
                "referer": payload.get("pageUrl") or "https://web.telegram.org/",
                "totalSize": total, "isVideo": True, "browserTransfer": True,
                "expectedDuration": payload.get("expectedDuration"), "startImmediately": False,
                "connections": 1,
            })
        ctrl = {"aborted": False, "file_lock": threading.RLock(), "last_bytes": 0,
                "last_time": time.time(), "last_activity": time.time()}
        try:
            ctrl["file"] = open(item["tempFilePath"], "w+b")
        except OSError:
            item.update(status="error", speed=0, errorMsg="تعذر إنشاء ملف التنزيل. راجع المساحة المتاحة وصلاحية المجلد.")
            self.save_state()
            raise
        token = uuid.uuid4().hex
        self.__dict__.setdefault("_browser_transfers", {})[token] = (item, ctrl)
        self.controllers[item["id"]] = ctrl
        self.save_state()
        self.signals.browser_captured.emit({"browserTransferId": item["id"]})
        return {"ok": True, "transferId": token}

    def receive_browser_transfer(self, operation, payload):
        token = str(payload.get("transferId") or "")
        record = self.__dict__.get("_browser_transfers", {}).get(token)
        if not record:
            raise ValueError("جلسة التنزيل انتهت. أعد المحاولة من المتصفح.")
        item, ctrl = record
        with ctrl["file_lock"]:
            ctrl["last_activity"] = time.time()
            if ctrl["aborted"] or item.get("status") != "downloading":
                raise ValueError("التنزيل اتوقف. أعد المحاولة من المتصفح.")
            if operation == "chunk":
                offset = int(payload.get("offset", -1))
                encoded = payload.get("data") or ""
                if not isinstance(encoded, str) or len(encoded) > 710000:
                    raise ValueError("حجم جزء الفيديو غير صالح.")
                chunk = base64.b64decode(encoded, validate=True)
                current = item["downloadedBytes"]
                if offset < 0 or not chunk or len(chunk) > 512 * 1024 or offset + len(chunk) > item["totalSize"]:
                    raise ValueError("حدود جزء الفيديو غير صالحة.")
                fh = ctrl["file"]
                if offset < current and offset + len(chunk) <= current:
                    fh.seek(offset)
                    if fh.read(len(chunk)) != chunk:
                        raise ValueError("الجزء المكرر مختلف عن البيانات المحفوظة.")
                    return {"ok": True, "offset": current}
                if offset != current:
                    raise ValueError("وصل جزء فيديو خارج الترتيب.")
                fh.seek(offset)
                fh.write(chunk)
                item["downloadedBytes"] += len(chunk)
                seg = item["segments"][0]
                seg["downloaded"] = item["downloadedBytes"]
                seg["currentByte"] = item["downloadedBytes"]
                item["progress"] = min(99.9, item["downloadedBytes"] / item["totalSize"] * 100)
                return {"ok": True, "offset": item["downloadedBytes"]}
            if operation == "abort":
                self.fail_browser_transfer(token, "التنزيل من المتصفح انقطع. افتح الفيديو وأعد المحاولة.")
                return {"ok": True}
            if operation != "finish":
                raise ValueError("عملية تنزيل غير صالحة.")
            try:
                if item["downloadedBytes"] != item["totalSize"]:
                    raise ValueError("الفيديو لم يصل بالكامل. أعد المحاولة من المتصفح.")
                ctrl["file"].flush()
                os.fsync(ctrl["file"].fileno())
                ctrl["file"].close()
                item["phase"] = "merging"
                item["actualDuration"] = self._validate_video_output(item["tempFilePath"], item)
                if ctrl["aborted"]:
                    raise ValueError("التنزيل اتوقف أثناء فحص الفيديو. أعد المحاولة من المتصفح.")
                destination = self._available_media_path(item["filePath"], item["id"])
                os.rename(item["tempFilePath"], destination)
                item["filePath"] = destination
                item["filename"] = os.path.basename(destination)
                item.update(status="completed", progress=100.0, speed=0, timeLeft=0, phase="done", finishedAt=time.time())
                item["segments"][0]["status"] = "completed"
                self.controllers.pop(item["id"], None)
                self._browser_transfers.pop(token, None)
                self.save_state()
                self.signals.completed.emit(item["id"])
                self._cleanup_item_temp(item)
                return {"ok": True}
            except Exception as err:
                self.fail_browser_transfer(token, str(err))
                raise

    def fail_browser_transfer(self, token, message):
        record = self.__dict__.get("_browser_transfers", {}).pop(token, None)
        if not record:
            return
        item, ctrl = record
        with ctrl["file_lock"]:
            ctrl["aborted"] = True
            ctrl["file"].close()
            self.controllers.pop(item["id"], None)
            if item.get("status") == "downloading":
                item.update(status="error", speed=0, errorMsg=message)
                for seg in item["segments"]:
                    seg["status"] = "error"
                self.save_state()

    def expire_browser_transfers(self):
        for token, (_, ctrl) in list(self.__dict__.get("_browser_transfers", {}).items()):
            if ctrl["aborted"] or time.time() - ctrl["last_activity"] > 180:
                self.fail_browser_transfer(token, "انقطع الاتصال بتبويب الفيديو. افتحه وأعد التنزيل.")
