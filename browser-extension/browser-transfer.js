/* Read browser-owned media through the page's service worker, with bounded memory. */
(function (root) {
  'use strict';
  const CHUNK_SIZE = 512 * 1024;
  async function readRange(url, offset, total, fetcher) {
    const end = total ? Math.min(total - 1, offset + CHUNK_SIZE - 1) : offset + CHUNK_SIZE - 1;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    try {
      const res = await fetcher(url, {
        credentials: 'same-origin', headers: { Range: `bytes=${offset}-${end}` }, signal: controller.signal,
      });
      if (res.status !== 206) {
        if (res.body) await res.body.cancel();
        throw new Error('المتصفح لم يرجع جزءًا موثوقًا من الفيديو. شغّل الفيديو وأعد المحاولة.');
      }
      const match = /^bytes (\d+)-(\d+)\/(\d+)$/i.exec(res.headers.get('Content-Range') || '');
      const mime = (res.headers.get('Content-Type') || '').toLowerCase();
      if (!match || Number(match[1]) !== offset || Number(match[2]) > end ||
          Number(match[2]) < offset || Number(match[3]) <= Number(match[2]) ||
          (total && Number(match[3]) !== total) || /text\/html|application\/json/.test(mime)) {
        if (res.body) await res.body.cancel();
        throw new Error('بيانات الفيديو أو حجمه اتغيّرت. أعد فتح الفيديو وحاول تاني.');
      }
      // Even a broken server must not turn a range request into an unbounded in-memory download.
      const expected = Number(match[2]) - offset + 1;
      const reader = res.body.getReader();
      const bytes = new Uint8Array(expected);
      let received = 0;
      try {
        while (true) {
          const part = await reader.read();
          if (part.done) break;
          if (received + part.value.length > expected) throw new Error('حجم جزء الفيديو غير صحيح.');
          bytes.set(part.value, received);
          received += part.value.length;
        }
      } finally { await reader.cancel().catch(() => {}); }
      if (received !== expected) throw new Error('الاتصال انقطع قبل اكتمال جزء الفيديو.');
      return { bytes, total: Number(match[3]), mime };
    } finally { clearTimeout(timer); }
  }
  function encode(bytes) {
    let binary = '';
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(binary);
  }
  async function transfer(url, metadata, request, fetcher = fetch, progress = () => {}, rangeReader = readRange) {
    let transferId;
    try {
      let part = await rangeReader(url, 0, 0, fetcher);
      const start = await request('start', { ...metadata, url, totalSize: part.total, mime: part.mime });
      if (!start.ok) throw new Error(start.error || 'تعذر بدء التنزيل. حدّث البرنامج والإضافة.');
      transferId = start.transferId;
      let offset = 0;
      const total = part.total;
      const readAt = async (from) => {
        for (let attempt = 0; ; attempt++) {
          try { return await rangeReader(url, from, total, fetcher); }
          catch (err) { if (attempt === 2) throw err; }
        }
      };
      while (offset < total) {
        const payload = { transferId, offset, data: encode(part.bytes) };
        // Read the next part while this one is being sent: the two waits overlap instead of adding up.
        const nextOffset = offset + part.bytes.length;
        const nextPart = nextOffset < total ? readAt(nextOffset) : null;
        if (nextPart) nextPart.catch(() => {}); // a failed send must not leave an unhandled rejection
        // An acknowledged chunk can be retried safely: the desktop checks the offset AND its bytes.
        let result;
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            result = await request('chunk', payload);
            if (!result.ok && result.retryable && attempt < 2) continue;
            break;
          }
          catch (err) { if (attempt === 2) throw err; }
        }
        if (!result.ok) throw new Error(result.error || 'التنزيل اتوقف. أعد المحاولة من الفيديو.');
        offset = nextOffset;
        progress(offset, total);
        if (nextPart) part = await nextPart;
      }
      const done = await request('finish', { transferId });
      if (!done.ok) throw new Error(done.error || 'فشل التحقق من الفيديو.');
      return done;
    } catch (err) {
      if (transferId) await request('abort', { transferId }).catch(() => {});
      throw err;
    }
  }
  root.ScorpionTransfer = { transfer, readRange, CHUNK_SIZE };
  if (typeof module !== 'undefined') module.exports = root.ScorpionTransfer;
})(globalThis);
