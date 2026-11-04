importScripts('media.js');
const SCORPION_SERVER = 'http://127.0.0.1:19615';
// Required by the desktop app for any state-changing call (web pages cannot send it cross-site).
const SCORPION_HEADERS = { 'X-Scorpion-Client': '1' };

let config = {
  interceptAllDownloads: true,
  showVideoFloatingBtn: true,
  minFileSizeKb: 100,
  lang: 'ar',
};

function updateContextMenus(lang) {
  const isEn = lang === 'en';
  try {
    chrome.contextMenus.removeAll(() => {
      chrome.contextMenus.create({
        id: 'scorpion-download-link',
        title: isEn ? 'Download link with Scorpion IDM' : 'تحميل الرابط بواسطة Scorpion IDM',
        contexts: ['link'],
      });
      chrome.contextMenus.create({
        id: 'scorpion-download-media',
        title: isEn ? 'Download video with Scorpion IDM' : 'تحميل الفيديو بواسطة Scorpion IDM',
        contexts: ['video', 'audio'],
      });
      chrome.contextMenus.create({
        id: 'scorpion-download-page-video',
        title: isEn ? 'Grab this page video with Scorpion IDM' : 'سحب فيديو هذه الصفحة بواسطة Scorpion IDM',
        contexts: ['page'],
      });
    });
  } catch (_) {}
}

chrome.storage.local.get(['scorpionConfig'], (res) => {
  if (res && res.scorpionConfig) {
    config = { ...config, ...res.scorpionConfig };
  } else {
    chrome.storage.local.set({ scorpionConfig: config });
  }
  updateContextMenus(config.lang);
});

chrome.storage.onChanged.addListener((changes) => {
  if (changes.scorpionConfig && changes.scorpionConfig.newValue) {
    const prevLang = config.lang;
    config = { ...config, ...changes.scorpionConfig.newValue };
    if (config.lang !== prevLang) {
      updateContextMenus(config.lang);
    }
  }
});

chrome.runtime.onInstalled.addListener(() => {
  updateContextMenus(config.lang);
  checkScorpionAlive();
});

if (chrome.runtime && chrome.runtime.onStartup) {
  chrome.runtime.onStartup.addListener(() => {
    checkScorpionAlive();
  });
}

if (chrome.tabs) {
  chrome.tabs.onCreated.addListener(() => { checkScorpionAlive(); });
  chrome.tabs.onActivated.addListener(() => { checkScorpionAlive(); });
  chrome.tabs.onUpdated.addListener(() => { checkScorpionAlive(); });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (tab && ScorpionMedia.isTelegram(tab.url) &&
      ['scorpion-download-media', 'scorpion-download-page-video'].includes(info.menuItemId)) {
    chrome.tabs.sendMessage(tab.id, { action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA', src: info.srcUrl || '' },
      { frameId: info.frameId || 0 }, () => void chrome.runtime.lastError);
    return;
  }
  if (info.menuItemId === 'scorpion-download-link' && info.linkUrl) {
    await sendToScorpion({
      url: info.linkUrl,
      referer: info.pageUrl || '',
      type: 'file',
    });
  } else if (info.menuItemId === 'scorpion-download-media' && info.srcUrl) {
    await sendToScorpion({
      url: info.srcUrl,
      referer: info.pageUrl || '',
      type: 'video',
    });
  } else if (info.menuItemId === 'scorpion-download-page-video' && tab && tab.url) {
    await sendToScorpion({
      url: tab.url,
      pageUrl: tab.url,
      title: tab.title || 'Video',
      type: 'video',
      quality: 'best',
    });
  }
});

const DOWNLOAD_EXT_REGEX = /\.(torrent|zip|rar|7z|exe|msi|iso|dmg|pkg|deb|rpm|apk|mp4|mkv|avi|mov|webm|flv|mp3|flac|wav|m4a|pdf|doc|docx|xls|xlsx|ppt|pptx|tar|gz|tgz|csv|epub|bin)(\?|$)/i;
const IGNORE_WEB_ASSET_REGEX = /\.(html?|htm|json|xml|css|js|svg|ico|webp|gif|jpe?g|png)(\?|$)/i;

chrome.downloads.onCreated.addListener(async (downloadItem) => {
  if (!config.interceptAllDownloads) return;
  if (downloadItem.state && downloadItem.state !== 'in_progress') return;

  const targetUrl = downloadItem.finalUrl || downloadItem.url || '';
  if (!targetUrl.startsWith('http://') && !targetUrl.startsWith('https://')) return;
  if (targetUrl.startsWith(SCORPION_SERVER)) return;
  // Telegram's virtual addresses only exist inside the page's service worker.
  if (ScorpionMedia.isBrowserLocal(targetUrl) || ScorpionMedia.isFragment(targetUrl)) return;

  const fileSize = downloadItem.fileSize || 0;
  const fname = downloadItem.filename || '';
  const mime = (downloadItem.mime || '').toLowerCase();
  const isTorrent =
    mime.includes('bittorrent') ||
    /\.torrent(\?|$)/i.test(targetUrl) ||
    fname.toLowerCase().endsWith('.torrent');

  const matchesDownloadExt = isTorrent || DOWNLOAD_EXT_REGEX.test(targetUrl) || DOWNLOAD_EXT_REGEX.test(fname);
  const isSmallWebAsset =
    !isTorrent &&
    (IGNORE_WEB_ASSET_REGEX.test(targetUrl) || IGNORE_WEB_ASSET_REGEX.test(fname) || mime.startsWith('image/') || mime === 'text/html') &&
    fileSize < 2 * 1024 * 1024;

  if (!matchesDownloadExt && isSmallWebAsset) return;

  const alive = await checkScorpionAlive();
  if (!alive) return;

  try {
    const accepted = await sendToScorpion({
      url: targetUrl,
      filename: downloadItem.filename ? downloadItem.filename.split(/[\\/]/).pop() : '',
      referer: downloadItem.referrer || '',
      totalSize: fileSize > 0 ? fileSize : 0,
      type: isTorrent ? 'torrent' : (mime.startsWith('video/') ? 'video' : 'file'),
      cookies: await siteCookies([targetUrl, downloadItem.referrer]),
    });
    // Leave the original browser download alone if the desktop never accepted it.
    if (accepted) chrome.downloads.cancel(downloadItem.id, () => {
      if (!chrome.runtime.lastError) chrome.downloads.erase({ id: downloadItem.id });
    });
  } catch (err) {
    console.error('Scorpion error:', err);
  }
});

async function detectBrowserKey() {
  try {
    const ua = navigator.userAgent || '';
    if (ua.includes('Edg/')) return 'msedge';
    if (navigator.brave && typeof navigator.brave.isBrave === 'function') {
      const isBr = await navigator.brave.isBrave();
      if (isBr) return 'brave';
    }
    if (ua.includes('Brave')) return 'brave';
  } catch (_) {}
  return 'chrome';
}

async function checkScorpionAlive() {
  try {
    const br = await detectBrowserKey();
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 900);
    const res = await fetch(`${SCORPION_SERVER}/ping?ext=1&browser=${encodeURIComponent(br)}`, { signal: ctrl.signal, headers: SCORPION_HEADERS });
    clearTimeout(timer);
    if (res.ok) {
      try {
        const data = await res.json();
        if (data && (data.lang === 'en' || data.lang === 'ar') && data.lang !== config.lang) {
          config = { ...config, lang: data.lang };
          chrome.storage.local.set({ scorpionConfig: config });
        }
      } catch (_) {}
      return true;
    }
    return false;
  } catch (_) {
    return false;
  }
}

checkScorpionAlive();
setInterval(checkScorpionAlive, 2500);

// The user's cookies for the video's site, so the app can download what the browser can see (videos that
// need a sign-in: Facebook, Instagram, X, private posts...). Sent only to the local app, only for these sites;
// the app keeps them in memory and in a temporary file deleted after the download.
async function siteCookies(urls) {
  if (!chrome.cookies) return [];
  const seen = new Map();
  for (const u of urls) {
    if (!u || !/^https?:\/\//i.test(u)) continue;
    try {
      for (const c of await chrome.cookies.getAll({ url: u })) {
        seen.set(`${c.domain}|${c.path}|${c.name}`, {
          domain: c.domain, path: c.path, secure: c.secure, hostOnly: c.hostOnly,
          expirationDate: c.expirationDate || 0, name: c.name, value: c.value,
        });
      }
    } catch (_) {}
  }
  return Array.from(seen.values());
}

async function sendToScorpion(payload) {
  try {
    const res = await fetch(`${SCORPION_SERVER}/capture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...SCORPION_HEADERS },
      body: JSON.stringify(payload),
    });
    return res.ok;
  } catch (_) {
    return false;
  }
}

// Response headers find extensionless manifests/media that performance entries cannot identify.
// Keep a bounded per-tab cache. Navigation discards streams from the previous page.
const tabStreams = new Map();
if (chrome.webRequest) chrome.webRequest.onHeadersReceived.addListener((details) => {
  if (details.tabId < 0 || ![200, 206].includes(details.statusCode) || ScorpionMedia.isFragment(details.url)) return;
  const headers = Object.fromEntries((details.responseHeaders || []).map((h) => [h.name.toLowerCase(), h.value || '']));
  const mime = (headers['content-type'] || '').toLowerCase();
  const isManifest = /mpegurl|dash\+xml/.test(mime) || ScorpionMedia.isManifest(details.url);
  if (!isManifest && !/^(video|audio)\//.test(mime)) return;
  const streams = tabStreams.get(details.tabId) || new Map();
  streams.delete(details.url);
  streams.set(details.url, { url: details.url, mime, isManifest, frameId: details.frameId, t: Date.now() });
  if (streams.size > 80) streams.delete(streams.keys().next().value);
  tabStreams.set(details.tabId, streams);
}, { urls: ['http://*/*', 'https://*/*'] }, ['responseHeaders']);
chrome.tabs.onRemoved.addListener((id) => tabStreams.delete(id));
chrome.tabs.onUpdated.addListener((id, change) => { if (change.url) tabStreams.delete(id); });

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'SCORPION_BROWSER_TRANSFER') {
    const operation = msg.operation;
    const payload = msg.payload || {};
    const owner = `${sender.tab && sender.tab.id}:${sender.frameId || 0}:${sender.documentId || ''}`;
    if (!sender.tab || !ScorpionMedia.isTelegram(sender.url) ||
        !['start', 'chunk', 'finish', 'abort'].includes(operation) ||
        (operation === 'start' && (!ScorpionMedia.isBrowserLocal(payload.url) ||
          new URL(payload.url).origin !== new URL(sender.url).origin))) {
      sendResponse({ ok: false, error: 'مصدر التنزيل غير صالح.' });
      return false;
    }
    (async () => {
      // MV3 suspends the service worker between chunks. Ownership must survive that suspension.
      const key = `scorpionTransfer:${payload.transferId || ''}`;
      if (operation !== 'start' && (await chrome.storage.session.get(key))[key] !== owner)
        return sendResponse({ ok: false, error: 'جلسة التنزيل انتهت. أعد المحاولة من الفيديو.' });
      const res = await fetch(`${SCORPION_SERVER}/browser-transfer/${operation}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...SCORPION_HEADERS },
        body: JSON.stringify(payload), signal: AbortSignal.timeout(operation === 'finish' ? 65000 : 20000),
      });
      const data = await res.json();
      if (operation === 'start' && data.ok) await chrome.storage.session.set({ [`scorpionTransfer:${data.transferId}`]: owner });
      if (operation === 'finish' && data.ok || operation === 'abort') await chrome.storage.session.remove(key);
      sendResponse(data);
    })().catch(() => sendResponse({ ok: false, retryable: true, error: 'الاتصال بالبرنامج انقطع. تأكد من تشغيله وتحديثه.' }));
    return true;
  }
  if (msg.action === 'SCORPION_DOWNLOAD_VIDEO' || msg.action === 'SCORPION_DOWNLOAD_LINK') {
    const payload = { ...(msg.payload || {}) };
    // From an embedded player (iframe): also send the page the user is on, for when the player's own
    // address doesn't identify the video
    if (sender && sender.tab && sender.frameId && sender.tab.url) payload.tabUrl = sender.tab.url;
    const generic = !payload.title || /^(scorpion_video|video|embed|player)$/i.test(String(payload.title).trim());
    const finish = async () => {
      if (msg.action === 'SCORPION_DOWNLOAD_VIDEO') {
        const tabUrl = sender && sender.tab && sender.tab.url;
        payload.cookies = await siteCookies([payload.url, payload.pageUrl, tabUrl, ...(payload.candidates || [])]);
      }
      sendResponse({ ok: await sendToScorpion(payload) });
    };
    if (generic && sender && sender.tab && sender.frameId) {
      chrome.tabs.sendMessage(sender.tab.id, { action: 'SCORPION_GET_TITLE' }, { frameId: 0 }, (res) => {
        if (!chrome.runtime.lastError && res && res.title) payload.title = res.title;
        finish();
      });
    } else {
      finish();
    }
    return true;
  }
  if (msg.action === 'SCORPION_GET_TAB_STREAMS') {
    const streams = tabStreams.get(sender.tab && sender.tab.id);
    sendResponse({ streams: Array.from(streams ? streams.values() : []).filter((s) =>
      Date.now() - s.t < 180000 && s.frameId === (sender.frameId || 0)).reverse(), config });
    return true;
  }
  if (msg.action === 'SCORPION_LIST_QUALITIES') {
    // Reading a video's qualities can take several seconds (the app asks yt-dlp)
    const tabUrl = (sender && sender.tab && sender.tab.url) || '';
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 60000);
    siteCookies([msg.url, tabUrl, ...(msg.candidates || [])])
      .then((cookies) =>
        fetch(`${SCORPION_SERVER}/formats`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...SCORPION_HEADERS },
          body: JSON.stringify({ url: msg.url || '', referer: msg.referer || '', tab: tabUrl, candidates: msg.candidates || [], cookies }),
          signal: ctrl.signal,
        })
      )
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => sendResponse(data || { ok: false }))
      .catch(() => sendResponse({ ok: false }))
      .finally(() => clearTimeout(timer));
    return true;
  }
  if (msg.action === 'SCORPION_SET_APP_LANG') {
    const lang = msg.lang === 'en' ? 'en' : 'ar';
    fetch(`${SCORPION_SERVER}/ping?set_lang=${lang}`, { headers: SCORPION_HEADERS })
      .then((r) => sendResponse({ ok: r.ok }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
  if (msg.action === 'SCORPION_GET_APP_LANG') {
    fetch(`${SCORPION_SERVER}/ping`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => sendResponse({ lang: data && data.lang }))
      .catch(() => sendResponse({ lang: null }));
    return true;
  }
  if (msg.action === 'SCORPION_CHECK_STATUS') {
    checkScorpionAlive().then((alive) => sendResponse({ alive, config }));
    return true;
  }
});
