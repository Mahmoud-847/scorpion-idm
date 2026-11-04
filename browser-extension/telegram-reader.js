/* MAIN world only: isolated extension fetches may bypass the page's service worker. */
(function () {
  'use strict';
  const readRange = ScorpionTransfer.readRange;
  window.addEventListener('message', async (event) => {
    const msg = event.data;
    if (event.source !== window || event.origin !== location.origin || !msg || msg.action !== 'SCORPION_READ_MEDIA_RANGE') return;
    if (location.hostname !== 'web.telegram.org' || typeof msg.requestId !== 'string' || msg.requestId.length > 64) return;
    // No arbitrary URL proxy. Only read the exact source of a video already present in this page.
    if (!Array.from(document.querySelectorAll('video')).some((video) => (video.currentSrc || video.src) === msg.url) ||
        !Number.isSafeInteger(msg.offset) || msg.offset < 0 || !Number.isSafeInteger(msg.total) || msg.total < 0) return;
    const url = new URL(msg.url, location.href);
    if (url.origin !== location.origin || !/\/(progressive|stream|download)\//i.test(url.pathname)) return;
    try {
      const part = await readRange(url.href, msg.offset, msg.total, fetch);
      let binary = '';
      for (let i = 0; i < part.bytes.length; i += 8192) binary += String.fromCharCode(...part.bytes.subarray(i, i + 8192));
      window.postMessage({ action: 'SCORPION_MEDIA_RANGE_RESULT', requestId: msg.requestId,
        part: { data: btoa(binary), total: part.total, mime: part.mime } }, location.origin);
    } catch (err) {
      window.postMessage({ action: 'SCORPION_MEDIA_RANGE_RESULT', requestId: msg.requestId, error: err.message }, location.origin);
    }
  });
})();
