const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

function page(url = 'https://example.test/watch/123', options = {}) {
  const dom = new JSDOM('<!doctype html><html><body><button id="page-action">Page action</button></body></html>',
    { url, runScripts: 'outside-only', pretendToBeVisual: true });
  const window = dom.window;
  const timers = [];
  const messages = [];
  const sessionData = {};
  window.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
  window.clearTimeout = () => {};
  window.requestAnimationFrame = (fn) => { fn(); return 1; };
  window.fetch = global.fetch;
  window.performance.getEntriesByType = () => options.performanceEntries || [];
  window.PerformanceObserver = class { observe() {} };
  window.chrome = {
    storage: { local: { get: (keys, cb) => cb({ scorpionConfig: { lang: 'ar', showVideoFloatingBtn: true } }), set: () => {} },
      session: { set: async (data) => Object.assign(sessionData, data) },
      onChanged: { addListener() {} } },
    runtime: { lastError: null, onMessage: { addListener() {} }, sendMessage: (message, callback) => {
      messages.push(message);
      if (message.action === 'SCORPION_GET_TAB_STREAMS') callback({ streams: [] });
      else if (message.action === 'SCORPION_GET_APP_LANG') callback({ lang: 'ar' });
      else if (callback) callback({ ok: true });
    } },
  };
  const states = (options.videos || [{}]).map((initial) => ({
    src: 'https://cdn.test/full.mp4', paused: false, ended: false, readyState: 2, duration: 120,
    rect: { left: 100, top: 100, right: 740, bottom: 460, width: 640, height: 360 }, ...initial,
  }));
  const videos = states.map((state) => {
    const video = window.document.createElement('video');
    video.src = state.src;
    for (const key of ['paused', 'ended', 'readyState', 'duration'])
      Object.defineProperty(video, key, { configurable: true, get: () => state[key] });
    Object.defineProperty(video, 'currentSrc', { configurable: true, get: () => video.src });
    video.getBoundingClientRect = () => ({ ...state.rect });
    window.document.body.insertBefore(video, window.document.querySelector('#page-action'));
    return video;
  });
  if (options.beforeScripts) options.beforeScripts({ window, videos, states });
  for (const script of ['media.js', 'browser-transfer.js', 'content.js']) {
    if (script === 'content.js' && options.beforeContent) options.beforeContent({ window, videos, states });
    window.eval(fs.readFileSync(path.join(__dirname, '../browser-extension', script), 'utf8'));
  }
  return {
    dom, window, video: videos[0], videos, states, timers, messages, sessionData,
    get panel() { return window.document.querySelector('.scorpion-idm-video-panel'); },
  };
}

function fire(p, video, name) {
  video.dispatchEvent(new p.window.Event(name, { bubbles: true }));
}

function hidden(p) {
  return !p.panel || p.panel.style.display === 'none';
}

function downloads(p) {
  return p.messages.filter((message) => message.action === 'SCORPION_DOWNLOAD_VIDEO');
}

test('downloads keep their own sources while the bar remains a download action through progress, failure and success', async () => {
  const transfers = [];
  const sources = ['https://web.telegram.org/a/progressive/first', 'https://web.telegram.org/a/progressive/second'];
  const p = page('https://web.telegram.org/a/', {
    videos: sources.map((src) => ({ src, paused: true })),
    beforeContent: ({ window }) => {
      window.ScorpionTransfer.transfer = (...args) => new Promise((resolve, reject) => transfers.push({ args, resolve, reject }));
    },
  });
  try {
    fire(p, p.videos[0], 'pointerenter');
    const label = p.panel.querySelector('.scorpion-btn-text');
    const mainText = label.textContent;
    p.panel.querySelector('.scorpion-idm-trigger').click();
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(transfers.length, 1, 'a repeated click must not create a duplicate transfer');
    transfers[0].args[4](512, 1024);
    assert.equal(label.textContent, mainText);

    fire(p, p.videos[1], 'pointerenter');
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(transfers.length, 2, 'the first download must not block another selected video');
    assert.deepEqual(transfers.map((item) => item.args[0]), sources);
    transfers[0].args[4](768, 1024);
    assert.equal(label.textContent, mainText);
    assert.equal(label.title, '');

    transfers[0].reject(new Error('Private URL https://example.test/?token=secret'));
    transfers[1].resolve({ ok: true });
    await new Promise(setImmediate);
    assert.equal(label.textContent, mainText);
    assert.equal(label.title, '');
    assert.equal(p.sessionData.scorpionDownloadError.code, 'transfer');
    assert.equal(Object.keys(p.sessionData.scorpionDownloadError).sort().join(','), 'at,code');
    assert.ok(!JSON.stringify(p.sessionData).includes('secret'));

    fire(p, p.videos[0], 'pointerenter');
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(transfers.length, 3, 'a failed source can be retried');
    transfers[2].resolve({ ok: true });
    await new Promise(setImmediate);
    assert.equal(label.textContent, mainText);
  } finally { p.dom.window.close(); }
});

test('a desktop connection failure leaves the video button unchanged and reports only a popup error code', () => {
  const p = page(undefined, { beforeContent: ({ window }) => {
    const send = window.chrome.runtime.sendMessage;
    window.chrome.runtime.sendMessage = (message, callback) => {
      if (message.action === 'SCORPION_DOWNLOAD_VIDEO') callback({ ok: false });
      else send(message, callback);
    };
  } });
  try {
    const label = p.panel.querySelector('.scorpion-btn-text');
    const mainText = label.textContent;
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(label.textContent, mainText);
    assert.equal(label.title, '');
    assert.equal(p.sessionData.scorpionDownloadError.code, 'connection');
  } finally { p.dom.window.close(); }
});

test('the download bar remains stable and has no auto-hide loop', () => {
  const p = page();
  try {
    assert.equal(p.panel.style.display, 'block');
    const before = p.panel.style.cssText;
    for (let i = 0; i < 20; i++) p.video.dispatchEvent(new p.window.MouseEvent('mousemove', { bubbles: true, clientX: 300, clientY: 200 }));
    assert.equal(p.panel.style.cssText, before);
    assert.equal(p.timers.some((timer) => [3800, 7500].includes(timer.ms)), false);
  } finally { p.dom.window.close(); }
});

test('close stays closed after playback, pointer movement, and DOM changes; page controls still work', async () => {
  const p = page();
  try {
    p.panel.querySelector('.scorpion-idm-close-btn').click();
    assert.equal(p.panel.style.display, 'none');
    for (const event of ['play', 'playing', 'loadeddata', 'pointerenter', 'mousemove'])
      p.video.dispatchEvent(new p.window.Event(event, { bubbles: true }));
    p.window.document.body.appendChild(p.window.document.createElement('div'));
    await new Promise(setImmediate);
    assert.equal(p.panel.style.display, 'none');
    let clicks = 0;
    p.window.document.querySelector('#page-action').addEventListener('click', () => clicks++);
    p.window.document.querySelector('#page-action').click();
    assert.equal(clicks, 1);
  } finally { p.dom.window.close(); }
});

test('dragging uses a separate handle, remains pinned, and releases control on pointer-up', () => {
  const p = page();
  try {
    const handle = p.panel.querySelector('.scorpion-idm-drag-handle');
    handle.setPointerCapture = () => {};
    handle.dispatchEvent(new p.window.MouseEvent('pointerdown', { bubbles: true, button: 0, buttons: 1, clientX: 20, clientY: 20 }));
    handle.dispatchEvent(new p.window.MouseEvent('pointermove', { bubbles: true, buttons: 1, clientX: 200, clientY: 150 }));
    const dragged = { left: p.panel.style.left, top: p.panel.style.top };
    handle.dispatchEvent(new p.window.MouseEvent('pointerup', { bubbles: true, button: 0, buttons: 0 }));
    p.video.dispatchEvent(new p.window.Event('pointerenter'));
    assert.deepEqual({ left: p.panel.style.left, top: p.panel.style.top }, dragged);
    p.panel.querySelector('.scorpion-idm-close-btn').click();
    assert.equal(p.panel.style.display, 'none');
  } finally { p.dom.window.close(); }
});

test('panel mutations do not recursively rescan music pages', async () => {
  const p = page('https://soundcloud.com/artist/track');
  try {
    let scans = 0;
    const query = p.window.document.querySelectorAll.bind(p.window.document);
    p.window.document.querySelectorAll = (selector) => {
      if (selector === 'video, audio') scans++;
      return query(selector);
    };
    for (let i = 0; i < 10; i++) p.panel.querySelector('.scorpion-btn-text').textContent = 'Changed ' + i;
    await new Promise(setImmediate);
    assert.equal(scans, 0);
  } finally { p.dom.window.close(); }
});

test('pointer entry selects a visible paused video and allows downloading it', () => {
  const p = page(undefined, { videos: [{ paused: true, readyState: 2 }] });
  try {
    fire(p, p.video, 'pointerenter');
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 1);
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/full.mp4');
    assert.equal(downloads(p)[0].payload.expectedDuration, 120);
  } finally { p.dom.window.close(); }
});

test('pointing at a second paused video selects only that video instead of the running video', () => {
  const p = page(undefined, { videos: [
    { src: 'https://cdn.test/running.mp4', paused: false },
    { src: 'https://cdn.test/paused.mp4', paused: true, duration: 33 },
  ] });
  try {
    fire(p, p.videos[1], 'pointerenter');
    fire(p, p.videos[1], 'loadeddata');
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 1);
    const payload = downloads(p)[0].payload;
    assert.equal(payload.url, 'https://cdn.test/paused.mp4');
    assert.equal(payload.expectedDuration, 33);
    assert.equal((payload.candidates || []).includes('https://cdn.test/running.mp4'), false);
  } finally { p.dom.window.close(); }
});

test('loading another paused video does not replace an explicitly pointed-at video', () => {
  const p = page(undefined, { videos: [
    { src: 'https://cdn.test/selected.mp4', paused: true, duration: 81 },
    { src: 'https://cdn.test/loaded.mp4', paused: true, duration: 19 },
  ] });
  try {
    fire(p, p.videos[0], 'pointerenter');
    fire(p, p.videos[1], 'loadeddata');
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 1);
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/selected.mp4');
    assert.equal(downloads(p)[0].payload.expectedDuration, 81);
    assert.equal((downloads(p)[0].payload.candidates || []).includes('https://cdn.test/loaded.mp4'), false);
  } finally { p.dom.window.close(); }
});

test('playing a background video cannot steal a paused video explicitly selected by the pointer', () => {
  const p = page(undefined, { videos: [
    { src: 'https://cdn.test/first.mp4', paused: true },
    { src: 'https://cdn.test/second.mp4', paused: true, duration: 47 },
  ] });
  try {
    fire(p, p.videos[0], 'pointerenter');
    p.states[1].paused = false;
    fire(p, p.videos[1], 'play');
    fire(p, p.videos[1], 'playing');
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 1);
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/first.mp4');
    assert.equal(downloads(p)[0].payload.expectedDuration, 120);
    assert.equal((downloads(p)[0].payload.candidates || []).includes('https://cdn.test/second.mp4'), false);
  } finally { p.dom.window.close(); }
});

test('pointing at a paused video replaces an old quality menu, and stale buttons cannot download', () => {
  const p = page(undefined, { videos: [
    { src: 'https://cdn.test/first.mp4', paused: false },
    { src: 'https://cdn.test/second.mp4', paused: true, duration: 47 },
  ] });
  try {
    p.panel.querySelector('.scorpion-idm-badge').click();
    const oldOption = p.panel.querySelector('.scorpion-idm-option');
    assert.ok(p.panel.querySelector('.scorpion-idm-dropdown').classList.contains('open'));
    fire(p, p.videos[1], 'pointerenter');
    assert.equal(p.panel.querySelector('.scorpion-idm-dropdown').classList.contains('open'), false);
    oldOption.click();
    assert.equal(downloads(p).length, 0);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 1);
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/second.mp4');
    assert.equal(downloads(p)[0].payload.expectedDuration, 47);
  } finally { p.dom.window.close(); }
});

test('reusing the same video element for a new source invalidates old quality buttons', () => {
  const p = page();
  try {
    p.panel.querySelector('.scorpion-idm-badge').click();
    const oldOption = p.panel.querySelector('.scorpion-idm-option');
    p.video.src = 'https://cdn.test/replacement.mp4';
    p.states[0].duration = 55;
    fire(p, p.video, 'pointerenter');
    oldOption.click();
    assert.equal(downloads(p).length, 0);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/replacement.mp4');
    assert.equal(downloads(p)[0].payload.expectedDuration, 55);
  } finally { p.dom.window.close(); }
});

test('the bar hides when its selected video leaves the viewport, including after the bar was dragged', () => {
  const p = page();
  try {
    const handle = p.panel.querySelector('.scorpion-idm-drag-handle');
    handle.setPointerCapture = () => {};
    handle.dispatchEvent(new p.window.MouseEvent('pointerdown', { bubbles: true, button: 0, buttons: 1, clientX: 20, clientY: 20 }));
    handle.dispatchEvent(new p.window.MouseEvent('pointermove', { bubbles: true, buttons: 1, clientX: 200, clientY: 150 }));
    handle.dispatchEvent(new p.window.MouseEvent('pointerup', { bubbles: true, button: 0, buttons: 0 }));
    p.states[0].rect = { left: 100, top: -500, right: 740, bottom: -140, width: 640, height: 360 };
    p.window.dispatchEvent(new p.window.Event('scroll'));
    assert.equal(hidden(p), true);
  } finally { p.dom.window.close(); }
});

test('removing the active video hides its download bar', async () => {
  const p = page();
  try {
    p.video.remove();
    await new Promise(setImmediate);
    assert.equal(hidden(p), true);
  } finally { p.dom.window.close(); }
});

test('pausing a selected video keeps its download bar and correct source', () => {
  const p = page();
  try {
    fire(p, p.video, 'pointerenter');
    p.states[0].paused = true;
    fire(p, p.video, 'pause');
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 1);
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/full.mp4');
    assert.equal(downloads(p)[0].payload.expectedDuration, 120);
  } finally { p.dom.window.close(); }
});

test('scroll selects the visible paused video closest to the viewport center instead of DOM order', () => {
  const p = page(undefined, { videos: [
    { src: 'https://cdn.test/center.mp4', paused: true, duration: 71,
      rect: { left: 100, top: 250, right: 740, bottom: 610, width: 640, height: 360 } },
    { src: 'https://cdn.test/edge.mp4', paused: true, duration: 20,
      rect: { left: 100, top: -200, right: 740, bottom: 160, width: 640, height: 360 } },
  ] });
  try {
    p.window.dispatchEvent(new p.window.Event('scroll'));
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 1);
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/center.mp4');
    assert.equal(downloads(p)[0].payload.expectedDuration, 71);
    assert.equal((downloads(p)[0].payload.candidates || []).includes('https://cdn.test/edge.mp4'), false);
  } finally { p.dom.window.close(); }
});

test('scroll replaces an old pointer choice while part of that video remains visible', () => {
  const p = page(undefined, { videos: [
    { src: 'https://cdn.test/previous.mp4', paused: true, duration: 90 },
    { src: 'https://cdn.test/next.mp4', paused: true, duration: 44,
      rect: { left: 100, top: 900, right: 740, bottom: 1260, width: 640, height: 360 } },
  ] });
  try {
    fire(p, p.videos[0], 'pointerenter');
    p.states[0].rect = { left: 100, top: -250, right: 740, bottom: 110, width: 640, height: 360 };
    p.states[1].rect = { left: 100, top: 250, right: 740, bottom: 610, width: 640, height: 360 };
    p.window.dispatchEvent(new p.window.Event('scroll'));
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 1);
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/next.mp4');
    assert.equal(downloads(p)[0].payload.expectedDuration, 44);
    assert.equal((downloads(p)[0].payload.candidates || []).includes('https://cdn.test/previous.mp4'), false);
  } finally { p.dom.window.close(); }
});

test('scroll focus changes source, duration and an open menu even when the previous video is partially visible', () => {
  const p = page(undefined, { videos: [
    { src: 'https://cdn.test/previous.mp4', paused: true, duration: 90 },
    { src: 'https://cdn.test/next.mp4', paused: true, duration: 44,
      rect: { left: 100, top: 900, right: 740, bottom: 1260, width: 640, height: 360 } },
  ] });
  try {
    fire(p, p.videos[0], 'pointerenter');
    p.panel.querySelector('.scorpion-idm-badge').click();
    const oldOption = p.panel.querySelector('.scorpion-idm-option');
    p.states[0].rect = { left: 100, top: -250, right: 740, bottom: 110, width: 640, height: 360 };
    p.states[1].rect = { left: 100, top: 250, right: 740, bottom: 610, width: 640, height: 360 };
    p.window.dispatchEvent(new p.window.Event('scroll'));
    assert.equal(p.panel.querySelector('.scorpion-idm-dropdown').classList.contains('open'), false);
    oldOption.click();
    assert.equal(downloads(p).length, 0);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/next.mp4');
    assert.equal(downloads(p)[0].payload.expectedDuration, 44);
    assert.equal((downloads(p)[0].payload.candidates || []).includes('https://cdn.test/previous.mp4'), false);
  } finally { p.dom.window.close(); }
});

test('a video clipped above the viewport receives valid visible bar coordinates at initialization', () => {
  const rect = { left: -80, top: -120, right: 560, bottom: 240, width: 640, height: 360 };
  const p = page(undefined, { videos: [{ paused: false, rect }] });
  try {
    assert.equal(hidden(p), false);
    const top = parseFloat(p.panel.style.top);
    const left = parseFloat(p.panel.style.left);
    assert.ok(Number.isFinite(top) && top >= 0 && top < rect.bottom, p.panel.style.cssText);
    assert.ok(Number.isFinite(left) && left >= 0 && left < rect.right, p.panel.style.cssText);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p)[0].payload.url, 'https://cdn.test/full.mp4');
  } finally { p.dom.window.close(); }
});

test('switching videos discards the old dragged position and places the bar near the new player', () => {
  const p = page(undefined, { videos: [
    { src: 'https://cdn.test/first.mp4', paused: false },
    { src: 'https://cdn.test/second.mp4', paused: true,
      rect: { left: 200, top: 400, right: 840, bottom: 760, width: 640, height: 360 } },
  ] });
  try {
    const handle = p.panel.querySelector('.scorpion-idm-drag-handle');
    handle.setPointerCapture = () => {};
    handle.dispatchEvent(new p.window.MouseEvent('pointerdown', { bubbles: true, button: 0, buttons: 1, clientX: 20, clientY: 20 }));
    handle.dispatchEvent(new p.window.MouseEvent('pointermove', { bubbles: true, buttons: 1, clientX: 50, clientY: 70 }));
    handle.dispatchEvent(new p.window.MouseEvent('pointerup', { bubbles: true, button: 0, buttons: 0 }));
    const dragged = { left: p.panel.style.left, top: p.panel.style.top };
    fire(p, p.videos[1], 'pointerenter');
    assert.notDeepEqual({ left: p.panel.style.left, top: p.panel.style.top }, dragged);
    const top = parseFloat(p.panel.style.top);
    assert.ok(top >= p.states[1].rect.top - 48 && top < p.states[1].rect.bottom);
  } finally { p.dom.window.close(); }
});

test('a second blob player on a Facebook reel page cannot download the first reel by reusing the page URL', () => {
  const p = page('https://www.facebook.com/reel/11111111', { videos: [
    { src: 'https://cdn.test/first-reel.mp4', paused: true },
    { src: 'blob:https://www.facebook.com/second-player', paused: true, duration: 29 },
  ] });
  try {
    fire(p, p.videos[1], 'pointerenter');
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 0);
  } finally { p.dom.window.close(); }
});

test('two players and two post links in one feed container do not prove either link belongs to the hovered blob player', () => {
  const p = page('https://www.facebook.com/', { videos: [
    { src: 'https://cdn.test/post-a.mp4', paused: true },
    { src: 'blob:https://www.facebook.com/post-b-player', paused: true, duration: 31 },
  ], beforeScripts: ({ window, videos }) => {
    const shared = window.document.createElement('article');
    for (const video of videos) shared.appendChild(video);
    for (const href of ['https://www.facebook.com/posts/11111111', 'https://www.facebook.com/posts/22222222']) {
      const anchor = window.document.createElement('a');
      anchor.href = href;
      anchor.textContent = 'Post';
      shared.appendChild(anchor);
    }
    window.document.body.appendChild(shared);
  } });
  try {
    fire(p, p.videos[1], 'pointerenter');
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 0);
  } finally { p.dom.window.close(); }
});

test('one blob player with two different reel links in its own article does not guess either post identity', () => {
  const p = page('https://www.facebook.com/', { videos: [
    { src: 'https://cdn.test/other-post.mp4', paused: true },
    { src: 'blob:https://www.facebook.com/selected-player', paused: true, duration: 57 },
  ], beforeScripts: ({ window, videos }) => {
    const article = window.document.createElement('article');
    article.appendChild(videos[1]);
    for (const href of ['https://www.facebook.com/reel/11111111', 'https://www.facebook.com/reel/22222222']) {
      const anchor = window.document.createElement('a');
      anchor.href = href;
      anchor.textContent = 'Reel';
      article.appendChild(anchor);
    }
    window.document.body.appendChild(article);
  } });
  try {
    fire(p, p.videos[1], 'pointerenter');
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 0);
    const hint = p.panel.querySelector('.scorpion-idm-hint');
    assert.ok(hint && hint.textContent.trim().length > 0);
    assert.ok(p.panel.querySelector('.scorpion-idm-dropdown').classList.contains('open'));
  } finally { p.dom.window.close(); }
});

test('a lone blob player in an embed frame sends the manifest its frame loaded', () => {
  const manifest = 'https://cdn.test/hls2/01/abc/master.m3u8?t=1';
  const p = page('https://player.test/embed-abc.html', {
    videos: [{ src: 'blob:https://player.test/mse', duration: 1808 }],
    performanceEntries: [{ name: manifest, initiatorType: 'xmlhttprequest' }],
  });
  try {
    fire(p, p.video, 'pointerenter');
    p.panel.querySelector('.scorpion-idm-trigger').click();
    const sent = downloads(p).at(-1);
    assert.ok(sent, 'a download was sent');
    const payload = sent.payload || sent;
    assert.ok([payload.url, ...(payload.candidates || [])].includes(manifest));
  } finally { p.dom.window.close(); }
});

test('a frame manifest is not attached when the document has several players', () => {
  const manifest = 'https://cdn.test/hls2/01/other/master.m3u8';
  const p = page('https://player.test/feed', {
    videos: [{ src: 'blob:https://player.test/one', duration: 30 }, { src: 'blob:https://player.test/two', duration: 40 }],
    performanceEntries: [{ name: manifest, initiatorType: 'xmlhttprequest' }],
  });
  try {
    fire(p, p.videos[1], 'pointerenter');
    const trigger = p.panel && p.panel.querySelector('.scorpion-idm-trigger');
    if (trigger) trigger.click();
    for (const sent of downloads(p)) {
      const payload = sent.payload || sent;
      assert.ok(![payload.url, ...(payload.candidates || [])].includes(manifest));
    }
  } finally { p.dom.window.close(); }
});

test('a player whose video lives inside a shadow root gets the download bar', () => {
  const p = page('https://ok.test/videoembed/123', {
    videos: [{ src: 'blob:https://ok.test/mse', duration: 1810 }],
    beforeScripts: ({ window, videos }) => {
      const host = window.document.createElement('div');
      const root = host.attachShadow({ mode: 'open' });
      root.appendChild(videos[0]);
      window.document.body.appendChild(host);
    },
  });
  try {
    assert.equal(p.window.document.querySelectorAll('video').length, 0, 'the video is not in the light DOM');
    fire(p, p.video, 'play');
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    assert.equal(downloads(p).length, 1);
  } finally { p.dom.window.close(); }
});

test('a shadow player added after load is found when the pointer moves over it', () => {
  const p = page('https://ok.test/videoembed/456', { videos: [] });
  try {
    const { window } = p;
    const host = window.document.createElement('div');
    const root = host.attachShadow({ mode: 'open' });
    window.document.body.appendChild(host);
    const video = window.document.createElement('video');
    video.src = 'blob:https://ok.test/late';
    for (const [key, value] of Object.entries({ paused: false, ended: false, readyState: 4, duration: 600 }))
      Object.defineProperty(video, key, { configurable: true, get: () => value });
    Object.defineProperty(video, 'currentSrc', { configurable: true, get: () => video.src });
    video.getBoundingClientRect = () => ({ left: 100, top: 100, right: 740, bottom: 460, width: 640, height: 360 });
    const controls = window.document.createElement('div');
    controls.getBoundingClientRect = video.getBoundingClientRect;
    root.append(video, controls);
    controls.dispatchEvent(new window.MouseEvent('pointerover', { bubbles: true, composed: true, clientX: 300, clientY: 200 }));
    assert.equal(hidden(p), false);
  } finally { p.dom.window.close(); }
});

test('visible <audio controls> with child <source> shows the audio bar and sends a direct audio download', () => {
  const srcUrl = 'https://cdn.example.com/episode.mp3';
  const p = page('https://podcast.test/ep1', {
    videos: [],
    beforeScripts: ({ window }) => {
      const audio = window.document.createElement('audio');
      audio.controls = true;
      const source = window.document.createElement('source');
      source.src = srcUrl;
      audio.appendChild(source);
      audio.getBoundingClientRect = () => ({ left: 40, top: 120, right: 340, bottom: 152, width: 300, height: 32 });
      window.document.body.appendChild(audio);
    },
  });
  try {
    assert.equal(hidden(p), false);
    assert.equal(p.panel.querySelector('.scorpion-btn-text').textContent, '🎵 تحميل هذا الصوت - Scorpion IDM');
    p.panel.querySelector('.scorpion-idm-trigger').click();
    const sent = downloads(p).map((msg) => msg.payload || msg);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].quality, 'direct');
    assert.equal(sent[0].type, 'audio');
    assert.equal(sent[0].url, srcUrl);
  } finally { p.dom.window.close(); }
});

test('hidden 0x0 custom <audio> player anchors the audio bar at bottom-right and downloads as audio', () => {
  const srcUrl = 'https://cdn.example.com/track.m4a';
  const p = page('https://music.test/player', {
    videos: [],
    beforeScripts: ({ window }) => {
      const audio = window.document.createElement('audio');
      audio.src = srcUrl;
      Object.defineProperty(audio, 'currentSrc', { configurable: true, get: () => srcUrl });
      audio.getBoundingClientRect = () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 });
      window.document.body.appendChild(audio);
    },
  });
  try {
    assert.equal(hidden(p), false);
    assert.equal(p.panel.querySelector('.scorpion-btn-text').textContent, '🎵 تحميل هذا الصوت - Scorpion IDM');
    assert.ok(parseFloat(p.panel.style.top) > 0 && parseFloat(p.panel.style.left) > 0);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    const sent = downloads(p).map((msg) => msg.payload || msg);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].type, 'audio');
    assert.equal(sent[0].quality, 'direct');
    assert.equal(sent[0].url, srcUrl);
  } finally { p.dom.window.close(); }
});

test('standalone browser audio tab (<video> playing audio/*) is detected in audio mode', () => {
  const srcUrl = 'https://cdn.example.com/song.mp3';
  const p = page(srcUrl, {
    videos: [],
    beforeScripts: ({ window }) => {
      Object.defineProperty(window.document, 'contentType', { configurable: true, get: () => 'audio/mpeg' });
      const video = window.document.createElement('video');
      video.controls = true;
      video.src = srcUrl;
      Object.defineProperty(video, 'currentSrc', { configurable: true, get: () => srcUrl });
      video.getBoundingClientRect = () => ({ left: 100, top: 200, right: 400, bottom: 254, width: 300, height: 54 });
      window.document.body.appendChild(video);
    },
  });
  try {
    assert.equal(hidden(p), false);
    assert.equal(p.panel.querySelector('.scorpion-btn-text').textContent, '🎵 تحميل هذا الصوت - Scorpion IDM');
    p.panel.querySelector('.scorpion-idm-trigger').click();
    const sent = downloads(p).map((msg) => msg.payload || msg);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].type, 'audio');
    assert.equal(sent[0].url, srcUrl);
  } finally { p.dom.window.close(); }
});
