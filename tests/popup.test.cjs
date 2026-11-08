const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

async function popup(error) {
  const html = fs.readFileSync(path.join(__dirname, '../browser-extension/popup.html'), 'utf8');
  const dom = new JSDOM(html, { url: 'https://extension.test/popup.html', runScripts: 'outside-only' });
  const { window } = dom;
  const removed = [];
  window.fetch = async () => ({ ok: true });
  window.chrome = {
    storage: {
      session: { get: async () => ({ scorpionDownloadError: error }), remove: async (key) => removed.push(key) },
      local: { set() {} },
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
