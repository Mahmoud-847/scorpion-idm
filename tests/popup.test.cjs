const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

async function popup(error, tabReply = { ok: false }, statusOverride = null, local = {}, browserLang = 'en-US') {
  const html = fs.readFileSync(path.join(__dirname, '../browser-extension/popup.html'), 'utf8');
  const dom = new JSDOM(html, { url: 'https://extension.test/popup.html', runScripts: 'outside-only' });
  const { window } = dom;
  Object.defineProperty(window.navigator, 'language', { value: browserLang });
  const removed = [];
  let poll;
  window.setInterval = (fn) => { poll = fn; return 1; };
  window.fetch = async () => ({ ok: true });
  let statusPayload = statusOverride || { alive: true, config: { lang: 'ar' }, stats: null };
  window.chrome = {
    storage: {
      session: {
        get: async () => ({ scorpionDownloadError: error }),
        set: async () => {},
        remove: async (key) => removed.push(key),
      },
      local: { get: (_, callback) => callback({ ...local }), set: (values) => Object.assign(local, values) },
    },
    tabs: {
      query: (_, callback) => callback([{ id: 7, url: 'https://example.com/watch' }]),
      sendMessage: (_id, _msg, callback) => callback(tabReply),
    },
    runtime: { sendMessage: (_, callback) => callback(statusPayload) },
  };
  window.eval(fs.readFileSync(path.join(__dirname, '../browser-extension/popup.js'), 'utf8'));
  await new Promise((resolve) => window.document.addEventListener('DOMContentLoaded', resolve, { once: true }));
  await new Promise(setImmediate);
  return { dom, window, removed, document: window.document, setStatus(next) { statusPayload = next; poll(); } };
}

test('popup shows and dismisses localized errors separately from connection status and exposes the public privacy policy', async () => {
  const p = await popup({ code: 'transfer', at: Date.now() });
  try {
    const card = p.document.getElementById('downloadErrorCard');
    const message = p.document.getElementById('downloadErrorMessage');
    assert.equal(card.hidden, false);
    assert.match(message.textContent, /تعذر إكمال تنزيل/);
    assert.match(p.document.getElementById('statusBadge').textContent, /متصل/);
    p.document.getElementById('langToggleBtn').click();
    assert.match(message.textContent, /Telegram download could not finish/);
    const link = p.document.getElementById('privacyLink');
    assert.equal(link.href, 'https://github.com/Mahmoud-847/scorpion-idm/blob/main/PRIVACY.md');
    assert.equal(link.textContent, 'Privacy policy');
    p.document.getElementById('dismissErrorBtn').click();
    assert.equal(card.hidden, true);
    assert.deepEqual(p.removed, ['scorpionDownloadError']);
  } finally { p.dom.window.close(); }
});

test('installer card follows live connection state, with browser locale when no choice is saved', async () => {
  const p = await popup({ code: 'connection', at: Date.now() }, null, { alive: false }, {}, 'ar-EG');
  try {
    const card = p.document.getElementById('installCard');
    const link = p.document.getElementById('installerLink');
    assert.equal(p.document.documentElement.dir, 'rtl');
    assert.equal(card.hidden, false);
    const qtSrc = fs.readFileSync(path.join(__dirname, '../native_app/scorpion_qt.py'), 'utf8');
    const appVer = qtSrc.match(/APP_VERSION\s*=\s*"([^"]+)"/)?.[1];
    assert.ok(appVer);
    assert.ok(link.href.endsWith(`/releases/download/v${appVer}/Scorpion-Setup-${appVer}.exe`));
    assert.equal(p.document.getElementById('downloadErrorCard').hidden, false);
    p.setStatus({ alive: true });
    assert.equal(card.hidden, true);
    assert.equal(p.document.getElementById('downloadErrorCard').hidden, true);
    assert.equal(p.document.getElementById('grabCurrentPageBtn').disabled, false);
  } finally { p.dom.window.close(); }
});

test('review invitation requires three completed downloads and appears once per profile', async () => {
  const local = {};
  const status = (count) => ({ alive: true, stats: { totalCount: 7, activeCount: 2, extensionCompletedCount: count } });
  const p = await popup(null, null, status(2), local);
  try {
    const card = p.document.getElementById('reviewCard');
    assert.equal(card.hidden, true);
    assert.equal(p.document.getElementById('reviewLink').hidden, false);
    p.setStatus(status(3));
    assert.equal(card.hidden, false);
    p.document.getElementById('dismissReviewBtn').click();
    p.setStatus(status(3));
    assert.equal(card.hidden, true);
  } finally { p.dom.window.close(); }
  const reopened = await popup(null, null, status(3), local);
  try { assert.equal(reopened.document.getElementById('reviewCard').hidden, true); }
  finally { reopened.dom.window.close(); }
});

test('welcome switches to connected and enables the sample only after a successful status check', () => {
  const dir = path.join(__dirname, '../browser-extension');
  const dom = new JSDOM(fs.readFileSync(path.join(dir, 'welcome.html'), 'utf8'), { runScripts: 'outside-only' });
  const { window } = dom;
  let alive = false;
  let poll;
  const messages = [];
  window.setInterval = (fn) => { poll = fn; };
  window.chrome = { runtime: { sendMessage(message, callback) {
    messages.push(message.action);
    callback(message.action === 'SCORPION_CHECK_STATUS' ? { alive } : { ok: true });
  } } };
  try {
    window.eval(fs.readFileSync(path.join(dir, 'welcome.js'), 'utf8'));
    const indicator = window.document.getElementById('connectionStatus');
    const button = window.document.getElementById('tryDownload');
    assert.equal(indicator.classList.contains('online'), false);
    assert.equal(button.hidden, true);
    alive = true;
    poll();
    assert.equal(indicator.classList.contains('online'), true);
    assert.equal(button.hidden, false);
    button.click();
    assert.equal(messages.at(-1), 'SCORPION_TRY_SAMPLE');
    assert.match(window.document.getElementById('sampleStatus').textContent, /Check the desktop app/);
  } finally { window.close(); }
});

test('popup renders drmProtected localized warning in Arabic and English', async () => {
  const p = await popup({ code: 'drmProtected', at: Date.now() });
  try {
    const card = p.document.getElementById('downloadErrorCard');
    const message = p.document.getElementById('downloadErrorMessage');
    assert.equal(card.hidden, false);
    assert.match(message.textContent, /DRM|Netflix/);
    p.document.getElementById('langToggleBtn').click();
    assert.match(message.textContent, /DRM-protected/);
  } finally { p.dom.window.close(); }
});

test('expired, future and unknown errors are never displayed in the popup', async () => {
  for (const error of [{ code: 'connection', at: Date.now() - 3600001 },
    { code: 'transfer', at: Date.now() + 60000 }, { code: '<script>private</script>', at: Date.now() }]) {
    const p = await popup(error);
    try {
      assert.equal(p.document.getElementById('downloadErrorCard').hidden, true);
      assert.equal(p.document.getElementById('downloadErrorMessage').textContent, '');
    } finally { p.dom.window.close(); }
  }
});

test('grabCurrentPageBtn shows noVideo inside errorCard without mutating statusBadge', async () => {
  const p = await popup(null, { ok: false });
  try {
    const badge = p.document.getElementById('statusBadge');
    const card = p.document.getElementById('downloadErrorCard');
    const message = p.document.getElementById('downloadErrorMessage');
    p.document.getElementById('grabCurrentPageBtn').click();
    assert.equal(card.hidden, false);
    assert.match(message.textContent, /قف على الفيديو المطلوب/);
    assert.match(badge.textContent, /متصل ببرنامج سطح المكتب/);
    p.document.getElementById('langToggleBtn').click();
    assert.match(message.textContent, /Point to the video or scroll to it/);
    assert.match(badge.textContent, /Desktop App Connected/);
    p.document.getElementById('dismissErrorBtn').click();
    assert.equal(card.hidden, true);
    assert.equal(message.textContent, '');
    assert.ok(p.removed.includes('scorpionDownloadError'));
  } finally { p.dom.window.close(); }
});

test('popup renders golden scorpion vector without emoji and omits unavailable stats until connected with real counts', async () => {
  const noStats = await popup(null, { ok: false }, { alive: true, config: { lang: 'en' }, stats: null });
  try {
    assert.ok(noStats.document.querySelector('svg.brand-emblem'));
    assert.equal(noStats.document.body.textContent.includes('🦂'), false);
    assert.equal(noStats.document.getElementById('statsRow').hidden, true);
  } finally { noStats.dom.window.close(); }

  const offlineWithStats = await popup(null, { ok: false }, { alive: false, config: { lang: 'en' }, stats: { totalCount: 4, activeCount: 1 } });
  try {
    assert.equal(offlineWithStats.document.getElementById('statsRow').hidden, true);
    assert.equal(offlineWithStats.document.getElementById('statusBadge').textContent, 'Desktop App Disconnected');
  } finally { offlineWithStats.dom.window.close(); }

  const withStats = await popup(null, { ok: false }, { alive: true, config: { lang: 'ar' }, stats: { totalCount: 6, activeCount: 2 } });
  try {
    const row = withStats.document.getElementById('statsRow');
    assert.equal(row.hidden, false);
    assert.equal(withStats.document.getElementById('lblDownloadsCount').textContent, 'التحميلات: 6');
    assert.equal(withStats.document.getElementById('lblActiveCount').textContent, 'النشطة: 2');
    withStats.document.getElementById('langToggleBtn').click();
    assert.equal(withStats.document.getElementById('lblDownloadsCount').textContent, 'Downloads: 6');
    assert.equal(withStats.document.getElementById('lblActiveCount').textContent, 'Active: 2');
  } finally { withStats.dom.window.close(); }
});
