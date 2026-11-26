const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readRange, transfer, CHUNK_SIZE } = require('../browser-extension/browser-transfer.js');
const media = require('../browser-extension/media.js');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

test('signed full media survives, individual fragments do not', () => {
  assert.equal(media.isFragment('https://cdn.test/full.mp4?token=abc'), false);
  for (const url of ['https://cdn.test/chunk-1.mp4', 'https://cdn.test/a.m4s', 'https://cdn.test/a.mp4?range=0-100'])
    assert.equal(media.isFragment(url), true);
  assert.equal(media.isFragment('https://cdn.test/segment/index.m3u8'), false);
  assert.equal(media.isTelegram('https://web.telegram.org.evil.test/'), false);
});

test('user-started downloads are never skipped just because the name looks like a stream part', () => {
  const background = fs.readFileSync(path.join(__dirname, '../browser-extension/background.js'), 'utf8');
  const handler = background.slice(background.indexOf('chrome.downloads.onCreated'), background.indexOf('async function sendToScorpion'));
  assert.ok(handler.includes('isBrowserLocal'));
  assert.ok(!handler.includes('isFragment'));
});

test('rejects HTML, ignored ranges, wrong offsets, changed totals and truncated bodies', async () => {
  const cases = [
    new Response('<html>login</html>', { status: 200 }),
    new Response('abcd', { status: 206, headers: { 'Content-Range': 'bytes 1-4/10' } }),
    new Response('ab', { status: 206, headers: { 'Content-Range': 'bytes 0-3/10' } }),
    new Response('abcde', { status: 206, headers: { 'Content-Range': 'bytes 0-3/10' } }),
    new Response('abcd', { status: 206, headers: { 'Content-Range': 'bytes 0-3/10', 'Content-Type': 'text/html' } }),
    new Response('abcd', { status: 206, headers: { 'Content-Range': 'bytes 0-3/11' } }),
  ];
  for (const response of cases) await assert.rejects(readRange('https://web.telegram.org/a/progressive/123', 0, 10, async () => response));
});

test('transfers every byte even when the service worker returns smaller ranges', async () => {
  const source = Buffer.alloc(CHUNK_SIZE * 2 + 7);
  for (let i = 0; i < source.length; i++) source[i] = i % 251;
  const received = [];
  const operations = [];
  const fetcher = async (url, opts) => {
    const [, from, requestedEnd] = /bytes=(\d+)-(\d+)/.exec(opts.headers.Range);
    const start = Number(from), end = Math.min(Number(requestedEnd), start + 65535, source.length - 1);
    return new Response(source.subarray(start, end + 1), { status: 206,
      headers: { 'Content-Range': `bytes ${start}-${end}/${source.length}`, 'Content-Type': 'video/mp4' } });
  };
  const request = async (op, payload) => {
    operations.push(op);
    if (op === 'start') return { ok: true, transferId: 'test' };
    if (op === 'chunk') {
      assert.equal(payload.offset, Buffer.concat(received).length);
      received.push(Buffer.from(payload.data, 'base64'));
    }
    return { ok: true };
  };
  await transfer('https://web.telegram.org/a/progressive/123', {}, request, fetcher);
  assert.deepEqual(Buffer.concat(received), source);
  assert.equal(operations.at(-1), 'finish');
});

test('reads the next part while the current one is still being sent', async () => {
  const source = Buffer.alloc(CHUNK_SIZE * 3);
  const events = [];
  const fetcher = async (url, opts) => {
    const [, from, requestedEnd] = /bytes=(\d+)-(\d+)/.exec(opts.headers.Range);
    const start = Number(from), end = Math.min(Number(requestedEnd), source.length - 1);
    events.push(`read:${start}`);
    return new Response(source.subarray(start, end + 1), { status: 206,
      headers: { 'Content-Range': `bytes ${start}-${end}/${source.length}`, 'Content-Type': 'video/mp4' } });
  };
  const request = async (op, payload) => {
    if (op === 'start') return { ok: true, transferId: 'test' };
    if (op === 'chunk') {
      events.push(`send:${payload.offset}`);
      await new Promise((resolve) => setTimeout(resolve, 20));
      events.push(`sent:${payload.offset}`);
    }
    return { ok: true };
  };
  await transfer('https://web.telegram.org/a/progressive/123', {}, request, fetcher);
  // The second part is requested before the first send has finished
  assert.ok(events.indexOf(`read:${CHUNK_SIZE}`) < events.indexOf('sent:0'));
});

test('stops and aborts when the desktop rejects a chunk', async () => {
  const operations = [];
  const request = async (op) => {
    operations.push(op);
    return op === 'start' ? { ok: true, transferId: 'test' } : { ok: false };
  };
  await assert.rejects(transfer('https://web.telegram.org/a/progressive/123', {}, request, async () =>
    new Response('abcd', { status: 206, headers: { 'Content-Range': 'bytes 0-3/4' } })));
  assert.deepEqual(operations, ['start', 'chunk', 'abort']);
});

test('MAIN reader only reads an exact video source on Telegram, never arbitrary addresses', async () => {
  let listener;
  const posts = [];
  const src = 'https://web.telegram.org/a/progressive/document123';
  const window = { addEventListener: (name, callback) => { listener = callback; }, postMessage: (data) => posts.push(data) };
  let reads = 0;
  const context = { window, location: { origin: 'https://web.telegram.org', hostname: 'web.telegram.org', href: 'https://web.telegram.org/a/' },
    document: { querySelectorAll: () => [{ currentSrc: src }] }, URL, fetch: async () => {}, btoa,
    ScorpionTransfer: { readRange: async () => { reads++; return { bytes: new Uint8Array([1, 2, 3]), total: 3, mime: 'video/mp4' }; } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../browser-extension/telegram-reader.js'), 'utf8'), context);
  const event = (url, origin = context.location.origin) => ({ source: window, origin,
    data: { action: 'SCORPION_READ_MEDIA_RANGE', requestId: 'test', readerId: 'reader-1', url, offset: 0, total: 0 } });
  await listener(event('https://evil.test/a/progressive/document123'));
  await listener(event(src, 'https://evil.test'));
  assert.equal(reads, 0);
  await listener(event(src));
  assert.equal(reads, 1);
  assert.equal(posts.at(-1).part.data, 'AQID');
  assert.equal(posts.at(-1).requestId, 'test');
});

test('an authorized Telegram transfer survives DOM removal but cannot change source, skip bytes or outlive release/expiry', async () => {
  let listener;
  let now = 1000;
  let videos = [];
  const reads = [], posts = [];
  const src = 'https://web.telegram.org/a/progressive/original';
  const other = 'https://web.telegram.org/a/progressive/other';
  const window = { addEventListener: (_, cb) => { listener = cb; }, postMessage: (data) => posts.push(data) };
  const context = { window, location: { origin: 'https://web.telegram.org', hostname: 'web.telegram.org' },
    document: { querySelectorAll: () => videos }, Date: { now: () => now }, URL, fetch: async () => {}, btoa,
    ScorpionTransfer: { readRange: async (url, offset) => {
      reads.push({ url, offset });
      return { bytes: new Uint8Array([1, 2]), total: 10, mime: 'video/mp4' };
    } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../browser-extension/telegram-reader.js'), 'utf8'), context);
  const send = async (data) => listener({ source: window, origin: context.location.origin,
    data: { action: 'SCORPION_READ_MEDIA_RANGE', requestId: 'request', readerId: 'reader-1', url: src, offset: 0, total: 0, ...data } });
  await send();
  assert.equal(reads.length, 0, 'a source absent at the start is never authorized');
  videos = [{ currentSrc: src }];
  await send();
  videos = [{ currentSrc: other }]; // Scrolling virtualized the original player.
  await send({ offset: 2, total: 10 });
  assert.equal(reads.length, 2);
  assert.deepEqual(reads.at(-1), { url: src, offset: 2 });
  await send({ url: other, offset: 4, total: 10 });
  await send({ offset: 8, total: 10 });
  await send({ offset: 4, total: 11 });
  assert.equal(reads.length, 2);
  await send({ offset: 2, total: 10 }); // A lost reply can be retried at the last offset.
  assert.equal(reads.length, 3);
  await send({ action: 'SCORPION_RELEASE_MEDIA_READER' });
  await send({ offset: 4, total: 10 });
  assert.equal(reads.length, 3);
  videos = [{ currentSrc: src }];
  await send();
  now += 180001;
  videos = [];
  await send({ offset: 2, total: 10 });
  assert.equal(reads.length, 4);
  assert.ok(posts.at(-1).error);
});

function loadBackgroundHarness(fetchHandler, options = {}) {
  const captured = [], cookieQueries = [], cancelled = [], erased = [], sentToTabs = [], createdTabs = [];
  const listeners = { onCreated: null, onMessage: null, onRemoved: null, onReplaced: null, onUpdated: null, onMenuClicked: null };
  const event = (slot) => ({ addListener: (cb) => { if (slot) listeners[slot] = cb; } });
  const stored = options.storage || (options.fresh ? {} : { scorpionConfig: { interceptAllDownloads: true, lang: 'ar' } });
  const chrome = {
    storage: {
      local: { get: (_, cb) => cb ? cb(stored) : Promise.resolve(stored), set: async (values) => Object.assign(stored, values) },
      session: { set: async () => {}, get: async () => ({}), remove: async () => {} },
      onChanged: event(),
    },
    runtime: {
      lastError: null,
      getURL: (rel) => `chrome-extension://test-ext/${rel}`,
      onInstalled: event('onInstalled'),
      onStartup: event(),
      onMessage: event('onMessage'),
    },
    contextMenus: { removeAll: (cb) => cb(), create() {}, onClicked: event('onMenuClicked') },
    tabs: {
      create: async ({ url }) => createdTabs.push(url),
      onCreated: event(),
      onActivated: event(),
      onUpdated: event('onUpdated'),
      onRemoved: event('onRemoved'),
      onReplaced: event('onReplaced'),
      sendMessage: (tabId, msg, opts, cb) => {
        const callback = typeof opts === 'function' ? opts : cb;
        const frameId = typeof opts === 'object' && opts ? opts.frameId : 0;
        sentToTabs.push({ tabId, msg, frameId });
        if (callback) callback(options.tabReply ? options.tabReply(msg, frameId) : { ok: false });
      },
    },
    downloads: {
      onCreated: event('onCreated'),
      cancel: (id, cb) => { cancelled.push(id); if (cb) cb(); },
      erase: ({ id }) => erased.push(id),
    },
    cookies: {
      getAllCookieStores: async () => [],
      getAll: async (q) => {
        cookieQueries.push(q);
        return [{ domain: 'files.test', path: '/', name: 'SESSION', value: 'tok-regular' }];
      },
    },
    webRequest: { onHeadersReceived: event(), onSendHeaders: event() },
  };
  const context = {
    chrome,
    ScorpionMedia: require(path.join(__dirname, '../browser-extension/media.js')),
    importScripts() {},
    navigator: { userAgent: 'Unit test UA', language: options.language || 'en-US', languages: ['en-US'] },
    URL, AbortController, AbortSignal, setTimeout: () => 0, clearTimeout() {}, setInterval() {}, console,
    fetch: async (url, opts) => {
      if (url.endsWith('bridge-auth.json')) {
        if (options.noAuthFile) return { ok: false, status: 404 };
        return { ok: true, json: async () => ({ token: 'unit-bridge-secret' }) };
      }
      if (url.includes('/ping') && !options.customPing) return { ok: true, json: async () => ({ lang: 'ar' }) };
      return fetchHandler(url, opts, captured);
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../browser-extension/background.js'), 'utf8'), context);
  return { context, listeners, captured, cookieQueries, cancelled, erased, sentToTabs, createdTabs };
}

test('Store pairing survives worker restart and leaves the traditional credential intact', async () => {
  const token = 'a'.repeat(64);
  const storage = { scorpionBridgeToken: 'existing-exe-token' };
  const reply = (data, status = 200) => new Response(JSON.stringify(data), {
    status, headers: { 'X-Scorpion-Bridge-Mode': 'store' },
  });
  const fetchStore = async (url, options) => {
    if (url.endsWith('/pair')) {
      assert.equal(JSON.parse(options.body).code, 'ABCD1234ABCD');
      assert.equal(options.redirect, 'error');
      return reply({ ok: true, token });
    }
    return options.headers['X-Scorpion-Token'] === token ?
      reply({ authenticated: true, totalCount: 0, activeCount: 0 }) : reply({ ok: false }, 403);
  };
  const makeWorker = () => loadBackgroundHarness(fetchStore, {
    customPing: true, noAuthFile: true, storage,
  }).listeners.onMessage;
  const send = (worker, message, url) => new Promise((resolve) => worker(message, { url }, resolve));
  const worker = makeWorker();
  const status = { action: 'SCORPION_CHECK_STATUS' };
  const pair = { action: 'SCORPION_PAIR_STORE', code: 'ABCD-1234-ABCD' };
  assert.equal((await send(worker, status)).pairingRequired, true);
  assert.equal(worker(pair, { url: 'https://files.test/' }, () => assert.fail('Untrusted sender')), false);
  const paired = await send(worker, pair, 'chrome-extension://test-ext/popup.html');
  assert.equal(paired.ok, true);
  assert.equal(paired.token, undefined);
  assert.equal(storage.scorpionBridgeToken, 'existing-exe-token');
  assert.equal((await send(makeWorker(), status)).alive, true);
});

test('only a fresh installation opens welcome and the default follows browser language', async () => {
  const h = loadBackgroundHarness(async () => { throw new Error('unexpected external request'); }, { fresh: true });
  await h.listeners.onInstalled({ reason: 'update' });
  assert.deepEqual(h.createdTabs, []);
  await h.listeners.onInstalled({ reason: 'install' });
  assert.deepEqual(h.createdTabs, ['chrome-extension://test-ext/welcome.html']);
  const status = await new Promise((resolve) => h.listeners.onMessage({ action: 'SCORPION_CHECK_STATUS' }, {}, resolve));
  assert.equal(status.config.lang, 'en', 'the running desktop app does not replace the browser default');
});

test('a Scorpion installer download stays in the browser even after a CDN redirect', async () => {
  const h = loadBackgroundHarness(async () => { throw new Error('the installer must not be intercepted'); });
  await h.listeners.onCreated({ id: 99, state: 'in_progress',
    url: 'https://github.com/Mahmoud-847/scorpion-idm/releases/download/v2.1.28/Scorpion-Setup-2.1.28.exe',
    finalUrl: 'https://release-assets.githubusercontent.com/file.exe', filename: 'Scorpion-Setup-2.1.28.exe',
  });
  assert.deepEqual(h.cookieQueries, []);
  assert.deepEqual(h.cancelled, []);
});

test('duplicate captures wait for server acceptance and do not cancel downloads on rejection', async () => {
  let resolveCapture;
  const h = loadBackgroundHarness((url, opts, captured) => {
    captured.push({ url, headers: opts.headers, body: JSON.parse(opts.body) });
    return new Promise((r) => { resolveCapture = r; });
  });
  const base = { url: 'https://files.test/a.zip', filename: 'a.zip', state: 'in_progress', mime: 'application/zip', fileSize: 500000, incognito: false };
  const p1 = h.listeners.onCreated({ ...base, id: 101 });
  await new Promise(setImmediate);
  const p2 = h.listeners.onCreated({ ...base, id: 102 });
  await new Promise(setImmediate);
  assert.equal(h.captured.length, 1);
  assert.equal(h.captured[0].headers['X-Scorpion-Token'], 'unit-bridge-secret');
  assert.deepEqual(h.cancelled, []);
  resolveCapture({ ok: false });
  await Promise.all([p1, p2]);
  assert.deepEqual(h.cancelled, []);
  assert.deepEqual(h.erased, []);
});

test('incognito browser downloads are skipped without querying regular cookies or posting to desktop', async () => {
  const h = loadBackgroundHarness(async (url, opts, captured) => {
    captured.push(JSON.parse(opts.body));
    return { ok: true };
  });
  await h.listeners.onCreated({
    id: 201, url: 'https://files.test/private.zip', filename: 'private.zip',
    state: 'in_progress', mime: 'application/zip', fileSize: 500000, incognito: true,
  });
  assert.equal(h.cookieQueries.length, 0);
  assert.equal(h.captured.length, 0);
  assert.deepEqual(h.cancelled, []);
});

test('missing bridge-auth.json is retried on next call and /ping unauthenticated reports offline', async () => {
  let tokenExists = false;
  let pingStatus = { ok: true, authenticated: false, lang: 'ar' };
  const fetchCalls = [];
  const chrome = {
    storage: {
      local: { get: (_, cb) => cb({ scorpionConfig: { interceptAllDownloads: true, lang: 'ar' } }), set() {} },
      session: { set: async () => {}, get: async () => ({}), remove: async () => {} },
      onChanged: { addListener() {} },
    },
    runtime: {
      lastError: null,
      getURL: (rel) => `chrome-extension://ext-id/${rel}`,
      onInstalled: { addListener() {} },
      onStartup: { addListener() {} },
      onMessage: { addListener() {} },
    },
    contextMenus: { removeAll: (cb) => cb(), create() {}, onClicked: { addListener() {} } },
    tabs: { onCreated: { addListener() {} }, onActivated: { addListener() {} }, onUpdated: { addListener() {} }, onRemoved: { addListener() {} }, onReplaced: { addListener() {} }, sendMessage() {} },
    downloads: { onCreated: { addListener() {} }, cancel() {}, erase() {} },
    cookies: { getAllCookieStores: async () => [], getAll: async () => [] },
    webRequest: { onHeadersReceived: { addListener() {} }, onSendHeaders: { addListener() {} } },
  };
  const context = {
    chrome,
    ScorpionMedia: require(path.join(__dirname, '../browser-extension/media.js')),
    importScripts() {},
    navigator: { userAgent: 'Unit UA', languages: ['en'] },
    URL, AbortController, AbortSignal, setTimeout: () => 0, clearTimeout() {}, setInterval() {}, console,
    fetch: async (url, opts) => {
      fetchCalls.push({ url, headers: opts && opts.headers });
      if (url.endsWith('bridge-auth.json')) {
        return tokenExists ? { ok: true, json: async () => ({ token: 'late-secret-999' }) } : { ok: false, status: 404 };
      }
      if (url.includes('/ping')) return { ok: Boolean(pingStatus), status: pingStatus ? 200 : 403, json: async () => pingStatus };
      return { ok: true, json: async () => ({ ok: true }) };
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../browser-extension/background.js'), 'utf8'), context);
  await new Promise(setImmediate);
  assert.equal(await context.checkScorpionAlive(), false);
  tokenExists = true;
  pingStatus = { ok: true, authenticated: true, lang: 'ar' };
  const hdrsAfter = await context.getBridgeHeaders();
  assert.equal(hdrsAfter['X-Scorpion-Token'], 'late-secret-999');
  assert.equal(await context.checkScorpionAlive(), true);
});

test('transfer respects cooperative server throttleMs backpressure', async () => {
  const src = Buffer.alloc(CHUNK_SIZE * 2);
  let sentChunks = 0;
  const fetcher = async (_u, opts) => {
    const [, from, endReq] = /bytes=(\d+)-(\d+)/.exec(opts.headers.Range);
    const s = Number(from), e = Math.min(Number(endReq), src.length - 1);
    return new Response(src.subarray(s, e + 1), {
      status: 206,
      headers: { 'Content-Range': `bytes ${s}-${e}/${src.length}`, 'Content-Type': 'video/mp4' },
    });
  };
  const request = async (op) => {
    if (op === 'start') return { ok: true, transferId: 't1', chunkSize: 32768 };
    if (op === 'chunk') { sentChunks++; return { ok: true, throttleMs: 1 }; }
    return { ok: true };
  };
  await transfer('https://web.telegram.org/a/progressive/1', {}, request, fetcher);
  assert.ok(sentChunks > 2);
});

test('telegram-reader forwards chunkSize and transfer awaits full throttleMs above 60 seconds', async () => {
  let listener;
  const src = 'https://web.telegram.org/a/progressive/chunked';
  const limits = [];
  const window = { addEventListener: (_, cb) => { listener = cb; }, postMessage: () => {} };
  const context = {
    window,
    location: { origin: 'https://web.telegram.org', hostname: 'web.telegram.org' },
    document: { querySelectorAll: () => [{ currentSrc: src }] },
    URL,
    fetch: async () => {},
    btoa,
    ScorpionTransfer: {
      readRange: async (_u, _off, _tot, _f, limit) => {
        limits.push(limit);
        return { bytes: new Uint8Array(4096), total: 4096, mime: 'video/mp4' };
      },
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../browser-extension/telegram-reader.js'), 'utf8'), context);
  await listener({
    source: window,
    origin: context.location.origin,
    data: { action: 'SCORPION_READ_MEDIA_RANGE', requestId: 'r1', readerId: 'rd1', url: src, offset: 0, total: 0, chunkSize: 4096 },
  });
  assert.deepEqual(limits, [4096]);

  // Verify transfer sleeps full throttleMs (> 60000 ms) using sliced waits instead of truncating at 60s
  const waited = [];
  const fullSrc = fs.readFileSync(path.join(__dirname, '../browser-extension/browser-transfer.js'), 'utf8');
  const tMod = { exports: {} };
  const origSetTimeout = setTimeout;
  const modCtx = {
    module: tMod,
    exports: tMod.exports,
    setTimeout: (fn, ms) => { if (ms < 60000) { waited.push(ms); fn(); } return 1; },
    AbortController,
    clearTimeout() {},
    Uint8Array,
    btoa,
    Error,
    Math,
    Number,
  };
  vm.runInNewContext(fullSrc, modCtx);
  const fullWaitMs = 95000;
  let heartbeats = 0;
  const buf = Buffer.alloc(4096);
  const fetcher = async () => new Response(buf, {
    status: 206,
    headers: { 'Content-Range': 'bytes 0-4095/4096', 'Content-Type': 'video/mp4' },
  });
  const request = async (op) => {
    if (op === 'start') return { ok: true, transferId: 't-slow', chunkSize: 4096 };
    if (op === 'chunk') return { ok: true, throttleMs: fullWaitMs };
    if (op === 'heartbeat') heartbeats++;
    return { ok: true };
  };
  await tMod.exports.transfer('https://web.telegram.org/a/progressive/1', {}, request, fetcher);
  assert.ok(waited.length > 1);
  assert.equal(waited.reduce((a, b) => a + b, 0), fullWaitMs);
  assert.equal(heartbeats, 19);
});

test('initial transfer read is small and cancellation is observed during long backpressure', async () => {
  const context = { module: { exports: {} }, Uint8Array, Number, Math, Error, btoa,
    setTimeout: (fn) => { fn(); return 1; }, clearTimeout() {}, AbortController };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../browser-extension/browser-transfer.js'), 'utf8'), context);
  const limits = [], calls = [];
  const reader = async (_url, _offset, _total, _fetcher, limit) => {
    limits.push(limit);
    return { bytes: new Uint8Array(4096), total: 4096, mime: 'video/mp4' };
  };
  const request = async (op) => {
    calls.push(op);
    if (op === 'start') return { ok: true, transferId: 'cancelled', chunkSize: 4096 };
    if (op === 'chunk') return { ok: true, throttleMs: 500000 };
    if (op === 'heartbeat') return { ok: false, error: 'cancelled' };
    return { ok: true };
  };
  await assert.rejects(context.module.exports.transfer('https://web.telegram.org/a/progressive/v', {},
    request, () => {}, () => {}, reader), /cancelled/);
  assert.deepEqual(limits, [4096]);
  assert.deepEqual(calls, ['start', 'chunk', 'heartbeat', 'abort']);
});

test('bound Telegram reader survives long throttle only with matching reader heartbeats', async () => {
  let listener, now = 0;
  const source = 'https://web.telegram.org/a/progressive/heartbeat';
  const replies = [];
  const window = { addEventListener: (_, cb) => { listener = cb; }, postMessage: (v) => replies.push(v) };
  const context = { window, Date: { now: () => now }, location: { origin: 'https://web.telegram.org', hostname: 'web.telegram.org' },
    document: { querySelectorAll: () => [{ currentSrc: source }] }, URL, fetch: () => {}, btoa,
    ScorpionTransfer: { readRange: async (_url, offset) => ({ bytes: new Uint8Array(4096), total: 16384, mime: 'video/mp4' }) } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../browser-extension/telegram-reader.js'), 'utf8'), context);
  const send = async (action, extra = {}) => listener({ source: window, origin: context.location.origin,
    data: { action, readerId: 'reader', url: source, ...extra } });
  await send('SCORPION_READ_MEDIA_RANGE', { requestId: 'first', offset: 0, total: 0 });
  for (now = 5000; now <= 500000; now += 5000) await send('SCORPION_KEEP_MEDIA_READER');
  await send('SCORPION_READ_MEDIA_RANGE', { requestId: 'second', offset: 4096, total: 16384 });
  assert.ok(replies.find(r => r.requestId === 'second').part);
  now += 181000;
  await send('SCORPION_READ_MEDIA_RANGE', { requestId: 'expired', offset: 8192, total: 16384 });
  assert.ok(replies.find(r => r.requestId === 'expired').error);
});

test('right-click page download never falls back to the page URL when the video is unclear', async () => {
  const sent = [];
  const h = loadBackgroundHarness(async (url) => { sent.push(url); return { ok: true, json: async () => ({ ok: true }) }; },
    { tabReply: () => ({ ok: false, error: 'unclearSource' }) });
  await h.listeners.onMenuClicked({ menuItemId: 'scorpion-download-page-video', frameId: 0 },
    { id: 7, url: 'https://social.test/feed', title: 'Feed' });
  assert.deepEqual(sent.filter((u) => !u.includes('/ping')), []);
});

test('a top page URL change keeps the streams an embedded player found', () => {
  const h = loadBackgroundHarness(async () => ({ ok: true, json: async () => ({}) }));
  h.listeners.onUpdated(7, { url: 'https://news.test/article#comments' });
  assert.ok(h.sentToTabs.every((m) => m.msg.action !== 'SCORPION_URL_CHANGED' || m.frameId === 0));
});
