const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

function page(url = 'https://example.test/watch/123') {
  const dom = new JSDOM('<!doctype html><html><body><video src="https://cdn.test/full.mp4"></video><button id="page-action">Page action</button></body></html>',
    { url, runScripts: 'outside-only', pretendToBeVisual: true });
  const window = dom.window;
  const timers = [];
  window.setTimeout = (fn, ms) => { timers.push({ fn, ms }); return timers.length; };
  window.clearTimeout = () => {};
  window.requestAnimationFrame = (fn) => { fn(); return 1; };
  window.fetch = global.fetch;
  window.performance.getEntriesByType = () => [];
  window.PerformanceObserver = class { observe() {} };
  window.chrome = {
    storage: { local: { get: (keys, cb) => cb({ scorpionConfig: { lang: 'ar', showVideoFloatingBtn: true } }), set: () => {} },
      onChanged: { addListener() {} } },
    runtime: { lastError: null, onMessage: { addListener() {} }, sendMessage: (message, callback) => {
      if (message.action === 'SCORPION_GET_TAB_STREAMS') callback({ streams: [] });
      else if (message.action === 'SCORPION_GET_APP_LANG') callback({ lang: 'ar' });
      else if (callback) callback({ ok: true });
    } },
  };
  const video = window.document.querySelector('video');
  for (const [key, value] of Object.entries({ paused: false, readyState: 2, duration: 120 }))
    Object.defineProperty(video, key, { value });
  video.getBoundingClientRect = () => ({ left: 100, top: 100, right: 740, bottom: 460, width: 640, height: 360 });
  for (const script of ['media.js', 'browser-transfer.js', 'content.js'])
    window.eval(fs.readFileSync(path.join(__dirname, '../browser-extension', script), 'utf8'));
  return { dom, window, video, timers, panel: window.document.querySelector('.scorpion-idm-video-panel') };
}

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
