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
