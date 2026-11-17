const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

async function popup(error, tabReply = { ok: false }, statusOverride = null) {
  const html = fs.readFileSync(path.join(__dirname, '../browser-extension/popup.html'), 'utf8');
  const dom = new JSDOM(html, { url: 'https://extension.test/popup.html', runScripts: 'outside-only' });
  const { window } = dom;
  const removed = [];
  window.fetch = async () => ({ ok: true });
  const statusPayload = statusOverride || { alive: true, config: { lang: 'ar' }, stats: null };
  window.chrome = {
    storage: {
      session: {
        get: async () => ({ scorpionDownloadError: error }),
        set: async () => {},
        remove: async (key) => removed.push(key),
      },
      local: { set() {} },
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
  return { dom, window, removed, document: window.document };
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
