const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

async function popup(error, tabReply = { ok: false }) {
  const html = fs.readFileSync(path.join(__dirname, '../browser-extension/popup.html'), 'utf8');
  const dom = new JSDOM(html, { url: 'https://extension.test/popup.html', runScripts: 'outside-only' });
  const { window } = dom;
  const removed = [];
  window.fetch = async () => ({ ok: true });
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
    runtime: { sendMessage: (_, callback) => callback({ alive: true, config: { lang: 'ar' } }) },
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
    assert.match(badge.textContent, /متصل بالبرنامج 🟢/);
    p.document.getElementById('langToggleBtn').click();
    assert.match(message.textContent, /Point to the video or scroll to it/);
    assert.match(badge.textContent, /Connected 🟢/);
    p.document.getElementById('dismissErrorBtn').click();
    assert.equal(card.hidden, true);
    assert.equal(message.textContent, '');
    assert.ok(p.removed.includes('scorpionDownloadError'));
  } finally { p.dom.window.close(); }
});
