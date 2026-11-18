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
    assert.equal(p.panel.querySelector('.scorpion-btn-text').textContent, 'تحميل الصوت بواسطة Scorpion');
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
    assert.equal(p.panel.querySelector('.scorpion-btn-text').textContent, 'تحميل الصوت بواسطة Scorpion');
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
    assert.equal(p.panel.querySelector('.scorpion-btn-text').textContent, 'تحميل الصوت بواسطة Scorpion');
    p.panel.querySelector('.scorpion-idm-trigger').click();
    const sent = downloads(p).map((msg) => msg.payload || msg);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].type, 'audio');
    assert.equal(sent[0].url, srcUrl);
  } finally { p.dom.window.close(); }
});

test('DRM video sites and EME-encrypted video players keep the floating bar hidden', () => {
  const nf = page('https://www.netflix.com/watch/80057281');
  try {
    assert.equal(hidden(nf), true);
  } finally { nf.dom.window.close(); }

  const eme = page('https://cinema.example.com/watch/99', {
    beforeScripts: ({ window, videos }) => {
      Object.defineProperty(videos[0], 'mediaKeys', { configurable: true, get: () => ({}) });
      window.__mark = true;
    },
  });
  try {
    assert.equal(hidden(eme), true);
  } finally { eme.dom.window.close(); }
});

test('SoundCloud /discover resolves exact track permalink from bottom player bar and keeps audio fallback enabled', () => {
  const p = page('https://soundcloud.com/discover', {
    videos: [],
    beforeScripts: ({ window }) => {
      window.navigator.mediaSession = {
        playbackState: 'playing',
        metadata: { title: 'Ya Bent El Sultan', artist: 'Ahmed Adaweya' },
      };
      const badge = window.document.createElement('div');
      badge.className = 'playbackSoundBadge';
      const link = window.document.createElement('a');
      link.className = 'playbackSoundBadge__titleLink';
      link.href = 'https://soundcloud.com/lebbo-2/oclf8fwewllb?in=lebbo-2/sets/top';
      link.textContent = 'Ya Bent El Sultan';
      badge.appendChild(link);
      window.document.body.appendChild(badge);
    },
  });
  try {
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    const sent = downloads(p).map((msg) => msg.payload || msg);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].url, 'https://soundcloud.com/lebbo-2/oclf8fwewllb');
    assert.equal(sent[0].type, 'audio');
    assert.equal(sent[0].strictTarget, false);
    assert.equal((sent[0].candidates || []).includes('https://soundcloud.com/discover'), false);
  } finally { p.dom.window.close(); }
});

test('Spotify virtual audio player updates active track when song changes in-place', async () => {
  let trackHref = '/track/111first';
  let trackTitle = 'First Song';
  let linkEl;
  const p = page('https://open.spotify.com/collection/tracks', {
    videos: [],
    beforeScripts: ({ window }) => {
      const tEl = window.document.createElement('title');
      tEl.textContent = 'First Song • Artist A';
      window.document.head.appendChild(tEl);
      window.navigator.mediaSession = {
        playbackState: 'playing',
        metadata: { title: trackTitle, artist: 'Artist A' },
      };
      linkEl = window.document.createElement('a');
      linkEl.setAttribute('data-testid', 'context-item-link');
      linkEl.setAttribute('href', trackHref);
      linkEl.textContent = trackTitle;
      window.document.body.appendChild(linkEl);
    },
  });
  try {
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();

    linkEl.setAttribute('href', '/track/222second');
    linkEl.textContent = 'Second Song';
    p.window.navigator.mediaSession.metadata = { title: 'Second Song', artist: 'Artist B' };
    p.window.document.querySelector('title').textContent = 'Second Song • Artist B';
    await new Promise(setImmediate);
    p.panel.querySelector('.scorpion-idm-trigger').click();

    const sent = downloads(p).map((msg) => msg.payload || msg);
    assert.equal(sent.length, 2);
    assert.equal(sent[0].url, 'https://open.spotify.com/track/111first');
    assert.equal(sent[1].url, 'https://open.spotify.com/track/222second');
    assert.equal(sent[1].strictTarget, false);
  } finally { p.dom.window.close(); }
});

test('direct MP4 on dropbox.com is not misclassified as x.com', () => {
  const p = page('https://www.dropbox.com/s/abc/demo', {
    videos: [{ src: 'https://uc.dropbox.com/raw/demo.mp4', paused: false }],
  });
  try {
    assert.equal(hidden(p), false);
    p.panel.querySelector('.scorpion-idm-trigger').click();
    const sent = downloads(p).map((msg) => msg.payload || msg);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].url, 'https://uc.dropbox.com/raw/demo.mp4');
  } finally { p.dom.window.close(); }
});

test('embedded iframe handles SCORPION_DOWNLOAD_CURRENT_MEDIA while ignoring SCORPION_GET_TITLE', () => {
  const handlers = [];
  const sentMessages = [];
  const p = page('https://player.test/embed/99', {
    beforeScripts: ({ window }) => {
      Object.defineProperty(window, 'self', { value: {} });
      window.chrome.runtime.onMessage.addListener = (cb) => handlers.push(cb);
    },
    beforeContent: ({ window }) => {
      const origSend = window.chrome.runtime.sendMessage;
      window.chrome.runtime.sendMessage = (msg, cb) => {
        sentMessages.push(msg);
        return origSend(msg, cb);
      };
    },
  });
  try {
    assert.equal(handlers.length, 1);
    let titleReply;
    assert.equal(handlers[0]({ action: 'SCORPION_GET_TITLE' }, {}, (r) => { titleReply = r; }), false);
    assert.equal(titleReply, undefined);
    fire(p, p.videos[0], 'pointerenter');
    assert.ok(sentMessages.some((m) => m.action === 'SCORPION_MARK_ACTIVE_FRAME'));
    let cmdReply;
    handlers[0]({ action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA' }, {}, (r) => { cmdReply = r; });
    assert.equal(cmdReply.ok, true);
    assert.equal(downloads(p).length, 1);
  } finally { p.dom.window.close(); }
});

test('explicit quality badge request does not reuse empty cookie-free prefetch cache', async () => {
  const requests = [];
  const p = page(undefined, {
    beforeContent: ({ window }) => {
      const orig = window.chrome.runtime.sendMessage;
      window.chrome.runtime.sendMessage = (msg, cb) => {
        if (msg.action === 'SCORPION_LIST_QUALITIES') {
          requests.push(msg.allowCookies);
          const payload = msg.allowCookies
            ? { ok: true, qualities: [{ quality: '1080p', label: '1080p', size: 1000000 }] }
            : { ok: true, qualities: [] };
          queueMicrotask(() => cb(payload));
        } else {
          orig(msg, cb);
        }
      };
    },
  });
  try {
    p.timers.find((tm) => tm.ms === 600).fn();
    await new Promise(setImmediate);
    p.panel.querySelector('.scorpion-idm-badge').click();
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    assert.deepEqual(requests, [false, true]);
    assert.ok(p.panel.querySelector('.scorpion-idm-dropdown').textContent.includes('1080p'));
  } finally { p.dom.window.close(); }
});

test('unrelated encrypted video does not block downloading a selected non-DRM video', () => {
  const handlers = [];
  const p = page(undefined, {
    videos: [{ src: 'https://cdn.test/drm.mp4' }, { src: 'https://cdn.test/open.mp4' }],
    beforeContent: ({ window, videos }) => {
      Object.defineProperty(videos[0], 'mediaKeys', { value: {} });
      window.chrome.runtime.onMessage.addListener = (cb) => handlers.push(cb);
    },
  });
  try {
    fire(p, p.videos[1], 'pointerenter');
    let reply;
    handlers[0]({ action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA' }, {}, (r) => { reply = r; });
    assert.equal(reply.ok, true);
    assert.equal(downloads(p).at(-1).payload.url, 'https://cdn.test/open.mp4');
  } finally { p.dom.window.close(); }
});

test('panel trigger and quality badge are keyboard-focusable buttons with menu ARIA and Escape/Arrow keys', () => {
  const p = page();
  try {
    const trigger = p.panel.querySelector('.scorpion-idm-trigger');
    const badge = p.panel.querySelector('.scorpion-idm-badge');
    const dropdown = p.panel.querySelector('.scorpion-idm-dropdown');
    assert.equal(trigger.tagName, 'BUTTON');
    assert.equal(badge.tagName, 'BUTTON');
    assert.ok(trigger.tabIndex >= 0);
    assert.ok(badge.tabIndex >= 0);
    assert.equal(dropdown.getAttribute('role'), 'menu');
    assert.equal(badge.getAttribute('aria-haspopup'), 'menu');
    assert.equal(badge.getAttribute('aria-expanded'), 'false');

    badge.click();
    assert.equal(badge.getAttribute('aria-expanded'), 'true');
    const items = Array.from(dropdown.querySelectorAll('.scorpion-idm-option'));
    assert.ok(items.length > 0);
    assert.equal(items[0].getAttribute('role'), 'menuitem');

    p.panel.dispatchEvent(new p.window.KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    assert.equal(p.window.document.activeElement, items[0]);
    p.panel.dispatchEvent(new p.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    assert.equal(dropdown.classList.contains('open'), false);
    assert.equal(badge.getAttribute('aria-expanded'), 'false');
    assert.equal(p.window.document.activeElement, badge);
  } finally { p.dom.window.close(); }
});

test('explicit/hover frame priority resists background play and rejected preferred frame never falls back', async () => {
  const vm = require('node:vm');
  const frames = new Map();
  let runtimeHandler;
  const chrome = {
    storage: { local: { get: (_, cb) => cb({ scorpionConfig: { interceptAllDownloads: true, lang: 'en' } }), set() {} }, session: { set: async () => {}, get: async () => ({}), remove: async () => {} }, onChanged: { addListener() {} } },
    runtime: { lastError: null, onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener: (cb) => { runtimeHandler = cb; } } },
    contextMenus: { removeAll: (cb) => cb(), create() {}, onClicked: { addListener() {} } },
    tabs: {
      onCreated: { addListener() {} }, onActivated: { addListener() {} }, onUpdated: { addListener() {} }, onRemoved: { addListener() {} }, onReplaced: { addListener() {} },
      sendMessage: (_tabId, msg, opts, cb) => {
        const fid = typeof opts === 'object' && opts ? opts.frameId : 0;
        const fn = frames.get(fid);
        if (fn) fn(msg, {}, cb);
        else cb({ ok: false });
      },
    },
    downloads: { onCreated: { addListener() {} }, cancel() {}, erase() {} },
    cookies: { getAllCookieStores: async () => [], getAll: async () => [] },
    webRequest: { onHeadersReceived: { addListener() {} }, onSendHeaders: { addListener() {} } },
  };
  const context = {
    chrome,
    ScorpionMedia: require(path.join(__dirname, '../browser-extension/media.js')),
    importScripts() {},
    navigator: { userAgent: 'UA', languages: ['en'] },
    URL, AbortController, AbortSignal, setTimeout: () => 0, clearTimeout() {}, setInterval() {}, console,
    fetch: async () => ({ ok: true, json: async () => ({ ok: true, authenticated: true }) }),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../browser-extension/background.js'), 'utf8'), context);

  frames.set(1, (_m, _s, cb) => cb({ ok: true }));
  frames.set(2, (_m, _s, cb) => cb({ ok: true }));
  runtimeHandler({ action: 'SCORPION_MARK_ACTIVE_FRAME', reason: 'hover' }, { tab: { id: 9 }, frameId: 1 }, () => {});
  runtimeHandler({ action: 'SCORPION_MARK_ACTIVE_FRAME', reason: 'play' }, { tab: { id: 9 }, frameId: 2 }, () => {});
  let res = await context.dispatchMediaCommandToTab(9, { action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA' });
  assert.equal(res.frameId, 1);

  frames.set(1, (_m, _s, cb) => cb({ ok: false, error: 'drmProtected' }));
  frames.set(0, (_m, _s, cb) => cb({ ok: true }));
  res = await context.dispatchMediaCommandToTab(9, { action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA' }, 1);
  assert.equal(res.ok, false);
  assert.equal(res.error, 'drmProtected');
});

test('anonymous quality request never reuses authenticated quality cache', async () => {
  let calls = 0;
  const p = page(undefined, {
    beforeContent: ({ window }) => {
      const orig = window.chrome.runtime.sendMessage;
      window.chrome.runtime.sendMessage = (msg, cb) => {
        if (msg.action === 'SCORPION_LIST_QUALITIES') {
          calls++;
          const q = msg.allowCookies ? [{ quality: '1080p', label: '1080p' }] : [{ quality: '360p', label: '360p' }];
          queueMicrotask(() => cb({ ok: true, qualities: q }));
        } else orig(msg, cb);
      };
    },
  });
  try {
    p.panel.querySelector('.scorpion-idm-badge').click();
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    p.timers.find((tm) => tm.ms === 600).fn();
    await new Promise(setImmediate);
    assert.equal(calls, 2);
  } finally { p.dom.window.close(); }
});

test('floating control uses golden scorpion vector, obsidian labels, and marks top quality with checkmark', async () => {
  const p = page(undefined, {
    beforeContent: ({ window }) => {
      const orig = window.chrome.runtime.sendMessage;
      window.chrome.runtime.sendMessage = (msg, cb) => {
        if (msg.action === 'SCORPION_LIST_QUALITIES') {
          queueMicrotask(() => cb({
            ok: true,
            qualities: [
              { quality: '1080p', label: '1080p', size: 120_000_000 },
              { quality: '720p', label: '720p', size: 75_000_000 },
            ],
          }));
        } else {
          orig(msg, cb);
        }
      };
    },
  });
  try {
    assert.ok(p.panel.querySelector('svg.scorpion-idm-emblem'));
    assert.equal(p.panel.textContent.includes('🦂'), false);
    assert.equal(p.panel.querySelector('.scorpion-btn-text').textContent, 'تحميل بواسطة Scorpion');

    p.panel.querySelector('.scorpion-idm-lang-btn').click();
    assert.equal(p.panel.querySelector('.scorpion-btn-text').textContent, 'Download with Scorpion');

    p.panel.querySelector('.scorpion-idm-badge').click();
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    const selected = p.panel.querySelectorAll('.scorpion-idm-option.is-selected');
    assert.equal(selected.length, 1);
    assert.match(selected[0].textContent, /1080p MP4/);
    assert.equal(selected[0].querySelector('.scorpion-idm-opt-check').textContent, '✓');
  } finally { p.dom.window.close(); }
});

test('newly hovered frame overrides an earlier explicit frame while background play still does not', async () => {
  const vm = require('node:vm');
  const frames = new Map();
  let runtimeHandler;
  const chrome = {
    storage: { local: { get: (_, cb) => cb({ scorpionConfig: { interceptAllDownloads: true, lang: 'en' } }), set() {} }, session: { set: async () => {}, get: async () => ({}), remove: async () => {} }, onChanged: { addListener() {} } },
    runtime: { lastError: null, onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener: (cb) => { runtimeHandler = cb; } } },
    contextMenus: { removeAll: (cb) => cb(), create() {}, onClicked: { addListener() {} } },
    tabs: {
      onCreated: { addListener() {} }, onActivated: { addListener() {} }, onUpdated: { addListener() {} }, onRemoved: { addListener() {} }, onReplaced: { addListener() {} },
      sendMessage: (_tabId, msg, opts, cb) => {
        const fid = typeof opts === 'object' && opts ? opts.frameId : 0;
        const fn = frames.get(fid);
        if (fn) fn(msg, {}, cb);
        else cb({ ok: false });
      },
    },
    downloads: { onCreated: { addListener() {} }, cancel() {}, erase() {} },
    cookies: { getAllCookieStores: async () => [], getAll: async () => [] },
    webRequest: { onHeadersReceived: { addListener() {} }, onSendHeaders: { addListener() {} } },
  };
  const context = {
    chrome,
    ScorpionMedia: require(path.join(__dirname, '../browser-extension/media.js')),
    importScripts() {},
    navigator: { userAgent: 'UA', languages: ['en'] },
    URL, AbortController, AbortSignal, setTimeout: () => 0, clearTimeout() {}, setInterval() {}, console,
    fetch: async () => ({ ok: true, json: async () => ({ ok: true, authenticated: true }) }),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../browser-extension/background.js'), 'utf8'), context);

  frames.set(1, (_m, _s, cb) => cb({ ok: true }));
  frames.set(2, (_m, _s, cb) => cb({ ok: true }));
  runtimeHandler({ action: 'SCORPION_MARK_ACTIVE_FRAME', reason: 'explicit' }, { tab: { id: 12 }, frameId: 1 }, () => {});
  runtimeHandler({ action: 'SCORPION_MARK_ACTIVE_FRAME', reason: 'play' }, { tab: { id: 12 }, frameId: 2 }, () => {});
  let res = await context.dispatchMediaCommandToTab(12, { action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA' });
  assert.equal(res.frameId, 1);

  runtimeHandler({ action: 'SCORPION_MARK_ACTIVE_FRAME', reason: 'hover' }, { tab: { id: 12 }, frameId: 2 }, () => {});
  res = await context.dispatchMediaCommandToTab(12, { action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA' });
  assert.equal(res.frameId, 2);
});

test('reopening quality menu on the same tab queries desktop again so session changes take effect', async () => {
  let session = 'A';
  const calls = [];
  const p = page(undefined, {
    beforeContent: ({ window }) => {
      const orig = window.chrome.runtime.sendMessage;
      window.chrome.runtime.sendMessage = (msg, cb) => {
        if (msg.action === 'SCORPION_LIST_QUALITIES') {
          calls.push(session);
          queueMicrotask(() => cb({ ok: true, qualities: [{ quality: '720p', label: `Session ${session}` }] }));
        } else {
          orig(msg, cb);
        }
      };
    },
  });
  try {
    p.panel.querySelector('.scorpion-idm-badge').click();
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    assert.ok(p.panel.textContent.includes('Session A'));

    session = 'B';
    p.panel.querySelector('.scorpion-idm-badge').click();
    p.panel.querySelector('.scorpion-idm-badge').click();
    await new Promise(setImmediate);
    await new Promise(setImmediate);
    assert.deepEqual(calls, ['A', 'B']);
    assert.ok(p.panel.textContent.includes('Session B'));
  } finally { p.dom.window.close(); }
});

test('a new account menu never shares an earlier account lookup still in flight', async () => {
  let session = 'A';
  const pending = [];
  const p = page(undefined, { beforeContent: ({ window }) => {
    const orig = window.chrome.runtime.sendMessage;
    window.chrome.runtime.sendMessage = (message, cb) => {
      if (message.action !== 'SCORPION_LIST_QUALITIES') return orig(message, cb);
      const account = session;
      pending.push({ account, complete: () => cb({ ok: true, qualities: [{ quality: '720p', label: `Account ${account}` }] }) });
    };
  } });
  try {
    p.panel.querySelector('.scorpion-idm-badge').click();
    await new Promise(setImmediate);
    session = 'B';
    p.panel.querySelector('.scorpion-idm-badge').click();
    p.panel.querySelector('.scorpion-idm-badge').click();
    await new Promise(setImmediate);
    assert.deepEqual(pending.map(x => x.account), ['A', 'B']);
    pending[1].complete();
    await new Promise(setImmediate);
    assert.ok(p.panel.textContent.includes('Account B'));
    pending[0].complete();
    await new Promise(setImmediate);
    assert.ok(p.panel.textContent.includes('Account B'));
    assert.ok(!p.panel.textContent.includes('Account A'));
  } finally { p.dom.window.close(); }
});

test('scroll selection publishes its frame while initial scan does not claim human selection', () => {
  const p = page(undefined, { videos: [{ paused: true }] });
  try {
    assert.equal(p.messages.filter(m => m.action === 'SCORPION_MARK_ACTIVE_FRAME').length, 0);
    p.window.dispatchEvent(new p.window.Event('scroll'));
    const markers = p.messages.filter(m => m.action === 'SCORPION_MARK_ACTIVE_FRAME');
    assert.equal(markers.at(-1).reason, 'viewport');
  } finally { p.dom.window.close(); }
});

test('quality lookup recovers after synchronous messaging failure in authenticated and anonymous modes', async () => {
  for (const authenticated of [true, false]) {
    let calls = 0;
    const p = page(undefined, { beforeContent: ({ window }) => {
      const orig = window.chrome.runtime.sendMessage;
      window.chrome.runtime.sendMessage = (message, cb) => {
        if (message.action !== 'SCORPION_LIST_QUALITIES') return orig(message, cb);
        assert.equal(message.allowCookies, authenticated);
        calls++;
        if (calls === 1) throw new Error('Extension context unavailable');
        cb({ ok: true, qualities: [{ quality: '720p', label: 'Recovered' }] });
      };
    } });
    try {
      if (authenticated) {
        p.panel.querySelector('.scorpion-idm-badge').click();
      } else {
        p.timers.filter(t => t.ms === 600).at(-1).fn();
      }
      await new Promise(setImmediate);
      if (authenticated) {
        p.panel.querySelector('.scorpion-idm-badge').click();
        p.panel.querySelector('.scorpion-idm-badge').click();
      } else {
        delete p.video.__scorpionPrefetchedFor;
        fire(p, p.video, 'pointerenter');
        p.timers.filter(t => t.ms === 600).at(-1).fn();
      }
      await new Promise(setImmediate);
      assert.equal(calls, 2, 'a synchronous failure must not leave a settled promise cached');
      if (authenticated) assert.ok(p.panel.textContent.includes('Recovered'));
    } finally { p.dom.window.close(); }
  }
});
