/* MAIN world only: isolated extension fetches may bypass the page's service worker. */
(function () {
  'use strict';
  const readRange = ScorpionTransfer.readRange;
  const readers = new Map();
  const IDLE_TIMEOUT = 180000;
  window.addEventListener('message', async (event) => {
    const msg = event.data;
    if (event.source !== window || event.origin !== location.origin || !msg || location.hostname !== 'web.telegram.org') return;
    if (typeof msg.readerId !== 'string' || !/^[\w-]{1,64}$/.test(msg.readerId)) return;
    for (const [id, reader] of readers) if (Date.now() - reader.lastActivity > IDLE_TIMEOUT) readers.delete(id);
    if (msg.action === 'SCORPION_RELEASE_MEDIA_READER') {
      if (readers.get(msg.readerId)?.url === msg.url) readers.delete(msg.readerId);
      return;
    }
    if (msg.action !== 'SCORPION_READ_MEDIA_RANGE') return;
    if (location.hostname !== 'web.telegram.org' || typeof msg.requestId !== 'string' || msg.requestId.length > 64) return;
    const fail = () => window.postMessage({ action: 'SCORPION_MEDIA_RANGE_RESULT', requestId: msg.requestId,
      error: 'جلسة قراءة الفيديو غير صالحة. أعد المحاولة من الفيديو.' }, location.origin);
    if (!Number.isSafeInteger(msg.offset) || msg.offset < 0 || !Number.isSafeInteger(msg.total) || msg.total < 0) return fail();
    let url;
    try { url = new URL(msg.url); } catch (_) { return fail(); }
    if (url.origin !== location.origin || !/\/(progressive|stream|download)\//i.test(url.pathname)) return fail();
    let reader = readers.get(msg.readerId);
    if (!reader) {
      // Authorize only an exact DOM media source at the start. Telegram may remove that player
      // while scrolling; subsequent sequential reads stay bound to the originally chosen source.
      if (msg.offset !== 0 || msg.total !== 0 || readers.size >= 8 ||
          !Array.from(document.querySelectorAll('video, audio')).some((el) => {
            const child = el.querySelector && el.querySelector('source[src]');
            return (el.currentSrc || el.src || (child && child.src)) === msg.url;
          })) return fail();
      reader = { url: msg.url, total: 0, nextOffset: 0, lastOffset: -1, busy: false, lastActivity: Date.now() };
      readers.set(msg.readerId, reader);
    }
    if (reader.url !== msg.url || reader.busy || msg.total !== reader.total ||
        msg.offset !== reader.nextOffset && msg.offset !== reader.lastOffset) return fail();
    reader.busy = true;
    reader.lastActivity = Date.now();
    try {
      const part = await readRange(url.href, msg.offset, msg.total, fetch);
      reader.total = part.total;
      reader.lastOffset = msg.offset;
      reader.nextOffset = msg.offset + part.bytes.length;
      reader.lastActivity = Date.now();
      let binary = '';
      for (let i = 0; i < part.bytes.length; i += 8192) binary += String.fromCharCode(...part.bytes.subarray(i, i + 8192));
      window.postMessage({ action: 'SCORPION_MEDIA_RANGE_RESULT', requestId: msg.requestId,
        part: { data: btoa(binary), total: part.total, mime: part.mime } }, location.origin);
    } catch (err) {
      window.postMessage({ action: 'SCORPION_MEDIA_RANGE_RESULT', requestId: msg.requestId, error: err.message }, location.origin);
    } finally { reader.busy = false; }
  });
})();
