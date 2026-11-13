import base64
import contextlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "native_app"))
import scorpion_qt as sq
from media_transfer import browser_local_url, fragment_url, validate_media


def engine_at(folder):
    engine = sq.ScorpionNativeEngine.__new__(sq.ScorpionNativeEngine)
    engine.settings = {"downloadsRoot": str(folder / "downloads"), "defaultConnections": 1, "maxConcurrent": 4, "lang": "en"}
    engine.temp_root = str(folder / "temp")
    engine.downloads = {}
    engine.controllers = {}
    engine.lock = threading.RLock()
    engine.signals = Mock()
    engine.save_state = Mock()
    return engine


@contextlib.contextmanager
def media_server(video, wrong_range=False, missing_fragment=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/video.mp4":
                if "session=allowed" not in self.headers.get("Cookie", ""):
                    self.send_error(403)
                    return
                match = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
                if match:
                    start, end = map(int, match.groups())
                    end = min(end, len(video) - 1)
                    body = video[start:end + 1]
                    self.send_response(206 if not wrong_range or start == end == 0 else 200)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(video)}")
                else:
                    body = video
                    self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
            elif self.path == "/index.m3u8":
                body = b"#EXTM3U\n#EXT-X-TARGETDURATION:3\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:3,\nmissing.ts\n#EXT-X-ENDLIST\n"
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            else:
                self.send_error(404)
                return
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class MediaRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix="scorpion_media_tests_")
        cls.folder = Path(cls.workspace.name)
        cls.video = cls.folder / "fixture.mp4"
        subprocess.run([
            sq.find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "3", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(cls.video),
        ], check=True, capture_output=True)
        cls.data = cls.video.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.folder)
        self.engine = engine_at(Path(self.temp.name))

    def tearDown(self):
        for token in list(self.engine.__dict__.get("_browser_transfers", {})):
            self.engine.fail_browser_transfer(token, "test cleanup")
        self.temp.cleanup()

    def start_transfer(self, **kwargs):
        payload = {"url": "https://web.telegram.org/a/progressive/document123", "filename": "lesson.mp4",
                   "totalSize": len(self.data), "expectedDuration": 3, **kwargs}
        result = self.engine.begin_browser_transfer(payload)
        token = result["transferId"]
        return token, self.engine._browser_transfers[token][0]

    def send(self, token, data=None, offset=0):
        return self.engine.receive_browser_transfer("chunk", {
            "transferId": token, "offset": offset, "data": base64.b64encode(self.data if data is None else data).decode(),
        })

    def test_telegram_page_never_extracts_site_animation(self):
        extractor = Mock()
        with self.assertRaises(RuntimeError):
            self.engine._extract_with_fallback(extractor, {"url": "https://web.telegram.org/a/#-123"})
        extractor.extract_info.assert_not_called()

    def test_fragment_candidates_are_skipped(self):
        extractor = Mock()
        extractor.extract_info.side_effect = [RuntimeError("unsupported URL"), {"url": "https://cdn.test/full.mp4"}]
        item = {"url": "https://site.test/watch/1", "candidates": ["https://cdn.test/segment-1.mp4", "https://cdn.test/full.mp4"]}
        info = self.engine._extract_with_fallback(extractor, item)
        self.assertEqual(info["url"], "https://cdn.test/full.mp4")
        self.assertEqual(extractor.extract_info.call_count, 2)

    def test_strict_target_never_falls_back_to_parent_tab_or_page_scrape(self):
        extractor = Mock()
        extractor.extract_info.side_effect = [RuntimeError("unsupported URL"), {"url": "https://cdn.test/other-video.mp4"}]
        item = {"url": "https://player.test/selected", "tabUrl": "https://site.test/feed", "strictTarget": True}
        with patch.object(self.engine, "_scrape_media_urls", return_value=["https://cdn.test/other-video.mp4"]) as scrape:
            with self.assertRaisesRegex(RuntimeError, "الفيديو المحدد"):
                self.engine._extract_with_fallback(extractor, item)
        extractor.extract_info.assert_called_once_with(item["url"], download=False)
        scrape.assert_not_called()

    def test_strict_target_uses_only_explicit_candidates_and_never_audio_search(self):
        extractor = Mock()
        extractor.extract_info.side_effect = [RuntimeError("unsupported URL"), {"url": "https://cdn.test/selected.mp4"}]
        item = {"url": "https://soundcloud.com/artist/selected", "videoQuality": "audio", "strictTarget": True,
                "tabUrl": "https://site.test/feed", "candidates": ["https://cdn.test/selected.mp4"]}
        with patch.object(self.engine, "_build_audio_search_query") as search:
            info = self.engine._extract_with_fallback(extractor, item)
        search.assert_not_called()
        self.assertEqual(info["url"], "https://cdn.test/selected.mp4")
        self.assertEqual([call.args[0] for call in extractor.extract_info.call_args_list],
                         ["https://soundcloud.com/artist/selected", "https://cdn.test/selected.mp4"])

    def test_strict_embedded_player_uses_its_frame_with_parent_referer(self):
        engine = engine_at(Path(tempfile.mkdtemp()))
        frame = "https://player.test/embed-abc.html"
        item = {"url": frame, "referer": frame, "tabUrl": "https://site.test/play.php?vid=1",
                "candidates": [frame], "strictTarget": True, "videoQuality": "best"}
        stream = "https://cdn.test/hls/master.m3u8"
        seen = []

        def scrape(page, referer=""):
            seen.append((page, referer))
            return [stream] if referer.startswith("https://site.test") else []

        ydl = Mock()
        ydl.extract_info.side_effect = lambda url, download=False: (
            {"url": url, "formats": [{"url": url}], "duration": 60} if url == stream else (_ for _ in ()).throw(Exception("Unsupported URL")))
        with patch.object(engine, "_scrape_media_urls", side_effect=scrape):
            engine._extract_with_fallback(ydl, item)
        self.assertEqual(item["url"], stream)
        self.assertEqual(seen[0], (frame, "https://site.test/play.php?vid=1"))

    def test_strict_page_that_is_not_a_frame_is_never_scraped(self):
        engine = engine_at(Path(tempfile.mkdtemp()))
        page = "https://site.test/feed"
        item = {"url": page, "referer": page, "tabUrl": page, "candidates": [], "strictTarget": True, "videoQuality": "best"}
        ydl = Mock()
        ydl.extract_info.side_effect = Exception("Unsupported URL")
        with patch.object(engine, "_scrape_media_urls", return_value=["https://cdn.test/other.m3u8"]) as scrape:
            with self.assertRaises(RuntimeError):
                engine._extract_with_fallback(ydl, item)
        scrape.assert_not_called()

    def test_strict_target_does_not_choose_first_video_of_a_playlist(self):
        extractor = Mock()
        extractor.extract_info.return_value = {"entries": [{"url": "https://cdn.test/first.mp4"},
                                                           {"url": "https://cdn.test/second.mp4"}]}
        with self.assertRaisesRegex(RuntimeError, "الفيديو المحدد"):
            self.engine._extract_with_fallback(extractor, {"url": "https://site.test/feed", "strictTarget": True})

    def test_strict_target_is_saved_in_download_and_defaults_to_legacy_behavior(self):
        strict = self.engine.add_download({"url": "https://cdn.test/selected.mp4", "isVideo": True,
                                           "startImmediately": False, "strictTarget": True})
        legacy = self.engine.add_download({"url": "https://cdn.test/manual.mp4", "isVideo": True,
                                           "startImmediately": False})
        self.assertIs(strict["strictTarget"], True)
        self.assertIs(legacy["strictTarget"], False)

    def test_strict_quality_request_does_not_reuse_general_fallback_cache(self):
        url = "https://player.test/selected"
        self.engine._quality_cache = {url: (sq.time.time(), {"ok": True, "title": "Another video", "qualities": []})}
        with patch.object(self.engine, "_extract_with_fallback", return_value={"title": "Selected video", "url": url}) as extract, \
             patch.object(self.engine, "_js_runtime_opts", return_value={}), patch.object(sq.yt_dlp, "YoutubeDL"):
            result = self.engine.list_video_qualities(url, tab_url="https://site.test/feed", strict_target=True)
        self.assertEqual(result["title"], "Selected video")
        self.assertIs(extract.call_args.args[1]["strictTarget"], True)

    def test_three_second_preview_cannot_complete_long_video(self):
        with self.assertRaises(RuntimeError):
            validate_media(str(self.video), sq.find_tool("ffprobe"), 120)
        self.assertGreater(validate_media(str(self.video), sq.find_tool("ffprobe"), 3), 2.9)

    def test_missing_and_nonmedia_outputs_fail(self):
        bad = Path(self.temp.name) / "bad.mp4"
        bad.write_text("<html>Sign in</html>")
        for path in (str(bad), str(bad) + ".missing"):
            with self.assertRaises(RuntimeError):
                validate_media(path, sq.find_tool("ffprobe"))

    def test_valid_transfer_preserves_original_and_retries_idempotently(self):
        token, item = self.start_transfer()
        self.send(token)
        self.send(token)
        self.assertEqual(item["downloadedBytes"], len(self.data))
        original = Path(item["filePath"])
        original.write_bytes(b"existing user file")
        self.engine.receive_browser_transfer("finish", {"transferId": token})
        self.assertEqual(item["status"], "completed")
        self.assertEqual(original.read_bytes(), b"existing user file")
        self.assertEqual(Path(item["filePath"]).read_bytes(), self.data)
        self.engine.signals.completed.emit.assert_called_once_with(item["id"])

    def test_out_of_order_oversized_and_changed_retry_rejected(self):
        token, item = self.start_transfer()
        with self.assertRaises(ValueError):
            self.send(token, self.data[:100], 10)
        self.send(token, self.data[:100])
        with self.assertRaises(ValueError):
            self.send(token, b"x" * 100)
        with self.assertRaises(ValueError):
            self.send(token, b"x" * (512 * 1024 + 1))
        self.assertEqual(item["downloadedBytes"], 100)

    def test_incomplete_transfer_never_publishes(self):
        token, item = self.start_transfer()
        self.send(token, self.data[:100])
        with self.assertRaises(ValueError):
            self.engine.receive_browser_transfer("finish", {"transferId": token})
        self.assertEqual(item["status"], "error")
        self.assertFalse(Path(item["filePath"]).exists())
        self.engine.signals.completed.emit.assert_not_called()

    def test_short_transfer_never_publishes(self):
        token, item = self.start_transfer(expectedDuration=3600)
        self.send(token)
        with self.assertRaises(RuntimeError):
            self.engine.receive_browser_transfer("finish", {"transferId": token})
        self.assertEqual(item["status"], "error")
        self.assertFalse(Path(item["filePath"]).exists())

    def test_pause_cancels_browser_transfer_and_removes_temp(self):
        token, item = self.start_transfer()
        self.send(token, self.data[:100])
        self.engine.pause_download(item["id"])
        self.assertEqual(item["status"], "error")
        self.assertFalse(Path(item["tempFilePath"]).exists())
        self.assertFalse(self.engine.controllers)
        with self.assertRaises(ValueError):
            self.send(token)
        # Resume from the app cannot revive a browser-owned transfer
        self.engine.start_download(item["id"])
        self.assertEqual(item["status"], "error")

    def test_failed_transfer_removes_temp_and_abort_after_pause_is_ok(self):
        token, item = self.start_transfer()
        self.send(token, self.data[:100])
        self.assertEqual(self.engine.receive_browser_transfer("abort", {"transferId": token}), {"ok": True})
        self.assertEqual(item["status"], "error")
        self.assertFalse(Path(item["tempFilePath"]).exists())

    def test_finish_moves_file_across_drives(self):
        token, item = self.start_transfer()
        self.send(token)
        with patch("os.rename", side_effect=OSError(17, "cross-device")):
            self.engine.receive_browser_transfer("finish", {"transferId": token})
        self.assertEqual(item["status"], "completed")
        self.assertEqual(Path(item["filePath"]).read_bytes(), self.data)

    def test_expired_tab_marks_transfer_failed(self):
        token, item = self.start_transfer()
        self.engine._browser_transfers[token][1]["last_activity"] = 0
        self.engine.expire_browser_transfers()
        self.assertEqual(item["status"], "error")
        self.assertFalse(self.engine.controllers)

    def test_http_range_preserves_cookies_and_rejects_ignored_range(self):
        import requests
        cookies = requests.cookies.RequestsCookieJar()
        cookies.set("session", "allowed", domain="127.0.0.1", path="/")
        with media_server(self.data) as origin:
            self.assertEqual(self.engine._probe_video_stream_range(origin + "/video.mp4", {}, cookies=cookies), (len(self.data), True))
            item = self.engine.add_download({"url": origin + "/video.mp4", "filename": "range.mp4", "isVideo": True, "startImmediately": False})
            ctrl = {"aborted": False}
            self.assertTrue(self.engine._download_video_streams_16ports(item, ctrl,
                [{"url": origin + "/video.mp4", "ext": "mp4", "protocol": "http"}],
                str(Path(self.engine.get_item_temp_dir(item["id"])) / "video_out"), "", False, "best", cookies))
            self.assertEqual(Path(item["_videoOutput"]).read_bytes(), self.data)
        with media_server(self.data, wrong_range=True) as origin, patch.object(sq.time, "sleep"):
            item.pop("videoLayout", None)
            self.assertFalse(self.engine._download_video_streams_16ports(item, ctrl,
                [{"url": origin + "/video.mp4", "ext": "mp4", "protocol": "http"}],
                str(Path(self.engine.get_item_temp_dir(item["id"])) / "video_out"), "", False, "best", cookies))

    def test_missing_hls_fragment_aborts_instead_of_skipping(self):
        with media_server(self.data) as origin:
            opts = {"quiet": True, "no_warnings": True, "skip_unavailable_fragments": False,
                    "fragment_retries": 0, "outtmpl": str(Path(self.temp.name) / "stream.%(ext)s"), "logger": Mock()}
            with sq.yt_dlp.YoutubeDL(opts) as ydl:
                with self.assertRaises(sq.yt_dlp.utils.DownloadError):
                    ydl.download([origin + "/index.m3u8"])

    def test_real_video_worker_downloads_and_validates_with_browser_cookies(self):
        with media_server(self.data) as origin:
            item = self.engine.add_download({"url": origin + "/video.mp4", "filename": "worker.mp4",
                "isVideo": True, "startImmediately": False, "expectedDuration": 3,
                "cookies": [{"domain": "127.0.0.1", "hostOnly": True, "path": "/", "name": "session", "value": "allowed"}]})
            item["status"] = "downloading"
            ctrl = {"aborted": False}
            self.engine.controllers[item["id"]] = ctrl
            self.engine._run_video_worker_with_cookies(item, ctrl)
            self.assertEqual(item["status"], "completed", item.get("errorMsg"))
            self.assertEqual(Path(item["filePath"]).read_bytes(), self.data)
            self.assertGreater(item["actualDuration"], 2.9)
            self.assertFalse(list(Path(self.engine.temp_root).glob("cookies_*")))

    def test_real_video_worker_rejects_short_preview(self):
        with media_server(self.data) as origin:
            item = self.engine.add_download({"url": origin + "/video.mp4", "filename": "preview.mp4",
                "isVideo": True, "startImmediately": False, "expectedDuration": 3600,
                "cookies": [{"domain": "127.0.0.1", "hostOnly": True, "path": "/", "name": "session", "value": "allowed"}]})
            item["status"] = "downloading"
            ctrl = {"aborted": False}
            self.engine.controllers[item["id"]] = ctrl
            self.engine._run_video_worker_with_cookies(item, ctrl)
            self.assertEqual(item["status"], "error")
            self.assertFalse(Path(item["filePath"]).exists())
            self.engine.signals.completed.emit.assert_not_called()

    def test_url_classification(self):
        self.assertTrue(browser_local_url("https://web.telegram.org/a/progressive/document123"))
        self.assertFalse(browser_local_url("https://web.telegram.org.evil.test/a/progressive/123"))
        for url in ("https://cdn.test/chunk-01.mp4", "https://cdn.test/a.m4s", "https://cdn.test/a.mp4?bytestart=20"):
            self.assertTrue(fragment_url(url))
        for url in ("https://cdn.test/master.m3u8?token=a", "https://cdn.test/full.mp4?token=a"):
            self.assertFalse(fragment_url(url))

    def test_direct_video_finalization_rejects_short_file(self):
        item = self.engine.add_download({"url": "https://cdn.test/video.mp4", "filename": "direct.mp4",
            "category": "Video", "totalSize": len(self.data), "startImmediately": False, "expectedDuration": 120})
        item["status"] = "downloading"
        fh = open(item["tempFilePath"], "wb")
        fh.write(self.data)
        ctrl = {"aborted": False, "file": fh}
        self.engine.controllers[item["id"]] = ctrl
        self.engine._finalize(item, ctrl)
        self.assertEqual(item["status"], "error")
        self.assertFalse(Path(item["filePath"]).exists())
        self.engine.signals.completed.emit.assert_not_called()

    def test_direct_missing_output_cannot_complete(self):
        item = self.engine.add_download({"url": "https://cdn.test/file.zip", "filename": "file.zip",
            "totalSize": 100, "startImmediately": False})
        self.engine._finalize(item, {"aborted": False, "file": Mock()})
        self.assertEqual(item["status"], "error")
        self.engine.signals.completed.emit.assert_not_called()

    def test_manifest_scripts_are_bundled(self):
        manifest = json.loads((ROOT / "browser-extension" / "manifest.json").read_text())
        required = set(self.engine.REQUIRED_EXT_FILES)
        for script in [s for entry in manifest["content_scripts"] for s in entry["js"]]:
            self.assertTrue((ROOT / "browser-extension" / script).is_file())
            self.assertIn(script, required)

    def test_audio_browser_transfer_marks_music_category_and_audio_quality(self):
        _token, item = self.start_transfer(isAudio=True, filename="voice.ogg", mime="audio/ogg")
        self.assertEqual(item["category"], "Music")
        self.assertEqual(item["videoQuality"], "audio")

    def test_validate_video_output_treats_music_and_audio_exts_as_audio_only(self):
        with patch.object(sq, "validate_media", return_value=12.5) as mock_val:
            self.engine._validate_video_output("song.mp3", {"category": "Music", "videoQuality": "direct"})
            self.assertTrue(mock_val.call_args.args[3])
            self.engine._validate_video_output("voice.ogg", {"category": "Video", "videoQuality": "best"})
            self.assertTrue(mock_val.call_args.args[3])

    def test_duplicate_capture_deduplication_and_delete_reset(self):
        url = "https://example.com/report?id=1"
        self.assertIsNone(self.engine.should_ignore_duplicate_capture(url, "best", "file"))
        self.engine.record_capture(url, "best", "file", "dl-1")
        self.engine.downloads["dl-1"] = {"id": "dl-1", "url": url, "status": "downloading"}
        self.assertEqual(self.engine.should_ignore_duplicate_capture(url, "best", "file"), "dl-1")
        # Distinct quality should not be suppressed
        self.assertIsNone(self.engine.should_ignore_duplicate_capture(url, "audio", "video"))
        # Deleting the download clears duplicate suppression so manual retry works
        self.engine.delete_download("dl-1")
        self.assertIsNone(self.engine.should_ignore_duplicate_capture(url, "best", "file"))

    def test_excel_extension_detection_from_headers_query_and_ooxml(self):
        self.assertEqual(
            sq.extract_filename(
                "https://portal.example.com/getAgentProductivityDownload?from=1",
                {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            ),
            "getAgentProductivityDownload.xlsx",
        )
        self.assertEqual(
            sq.extract_filename(
                "https://portal.example.com/getAgentActivityReportDownload?type=EXCEL",
                {"Content-Type": "application/octet-stream"},
            ),
            "getAgentActivityReportDownload.xlsx",
        )
        import zipfile
        with tempfile.TemporaryDirectory() as tmpdir:
            xlsx_tmp = Path(tmpdir) / "getAgentProductivityDownload"
            with zipfile.ZipFile(xlsx_tmp, "w") as zf:
                zf.writestr("xl/workbook.xml", "<workbook/>")
            self.assertEqual(sq._sniff_file_ext(str(xlsx_tmp)), ".xlsx")


if __name__ == "__main__":
    unittest.main()
