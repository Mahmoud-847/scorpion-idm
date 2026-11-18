importScripts('media.js');
const SCORPION_SERVER = 'http://127.0.0.1:19615';
// Required by the desktop app for any state-changing call (web pages cannot send it cross-site).
const SCORPION_HEADERS = { 'X-Scorpion-Client': '1' };
let cachedBridgeToken = '';
let inflightTokenRead = null;

function persistTokenToStorage(tok) {
  try {
    if (tok && chrome && chrome.storage && chrome.storage.local && typeof chrome.storage.local.set === 'function') {
      chrome.storage.local.set({ scorpionBridgeToken: tok });
    }
  } catch (_) {}
}

async function readTokenFromNativeHost() {
  try {
    if (chrome && chrome.runtime && typeof chrome.runtime.sendNativeMessage === 'function') {
      const reply = await new Promise((resolve) => {
        try {
          chrome.runtime.sendNativeMessage('com.scorpionidm.bridge', { action: 'getBridgeToken' }, (res) => {
            if (chrome.runtime.lastError) resolve(null);
            else resolve(res || null);
          });
        } catch (_) {
          resolve(null);
        }
      });
      if (reply && typeof reply.token === 'string' && reply.token.trim()) {
        return reply.token.trim();
      }
    }
  } catch (_) {}
  return '';
}

async function getBridgeHeaders(forceRefresh = false) {
  if (forceRefresh) cachedBridgeToken = '';
  if (cachedBridgeToken) {
    return { ...SCORPION_HEADERS, 'X-Scorpion-Token': cachedBridgeToken };
  }
  if (!inflightTokenRead) {
    inflightTokenRead = (async () => {
      try {
        if (chrome && chrome.runtime && typeof chrome.runtime.getURL === 'function') {
          const res = await fetch(chrome.runtime.getURL('bridge-auth.json'));
          if (res && res.ok) {
            const data = await res.json();
            if (data && typeof data.token === 'string' && data.token.trim()) {
              cachedBridgeToken = data.token.trim();
              persistTokenToStorage(cachedBridgeToken);
              return cachedBridgeToken;
            }
          }
        }
      } catch (_) {}
      if (!forceRefresh && chrome && chrome.storage && chrome.storage.local && typeof chrome.storage.local.get === 'function') {
        const stored = await new Promise((resolve) => {
          try {
            chrome.storage.local.get(['scorpionBridgeToken'], (r) => resolve(r && r.scorpionBridgeToken ? String(r.scorpionBridgeToken).trim() : ''));
          } catch (_) {
            resolve('');
          }
        });
        if (stored) {
          cachedBridgeToken = stored;
          return cachedBridgeToken;
        }
      }
      const nativeTok = await readTokenFromNativeHost();
      if (nativeTok) {
        cachedBridgeToken = nativeTok;
        persistTokenToStorage(nativeTok);
        return cachedBridgeToken;
      }
      return '';
    })().finally(() => {
      inflightTokenRead = null;
    });
  }
  const tok = await inflightTokenRead;
  return tok ? { ...SCORPION_HEADERS, 'X-Scorpion-Token': tok } : { ...SCORPION_HEADERS };
}

async function bridgeFetch(url, options = {}) {
  const baseHeaders = options.headers || {};
  const headers = { ...baseHeaders, ...(await getBridgeHeaders(false)) };
  let res = await fetch(url, { ...options, headers });
  if (res && (res.status === 401 || res.status === 403)) {
    const freshHeaders = { ...baseHeaders, ...(await getBridgeHeaders(true)) };
    res = await fetch(url, { ...options, headers: freshHeaders });
  }
  return res;
}

let config = {
  interceptAllDownloads: true,
  showVideoFloatingBtn: true,
  minFileSizeKb: 100,
  lang: 'ar',
};

const VALID_ERROR_CODES = new Set(['connection', 'drmProtected', 'noVideo', 'telegramSource', 'telegramAudio', 'transfer']);
const DRM_VIDEO_HOST_RE = /(^|\.)(netflix\.com|disneyplus\.com|primevideo\.com|shahid\.mbc\.net|watchit\.com|osnplus\.com|tv\.apple\.com|hulu\.com|max\.com|peacocktv\.com|paramountplus\.com|tod\.tv|starzplay\.com)$/i;
const NO_COOKIE_MUSIC_HOST_RE = /(^|\.)(open\.spotify\.com|spotify\.com|music\.apple\.com|deezer\.com|anghami\.com)$/i;

function isDrmVideoUrl(raw) {
  try {
    const u = new URL(String(raw || ''));
    return DRM_VIDEO_HOST_RE.test(u.hostname) ||
      (/(^|\.)amazon\.[a-z.]+$/i.test(u.hostname) && /^\/(gp\/video|detail|dp)\b/i.test(u.pathname));
  } catch (_) {
    return false;
  }
}

function recordPopupError(code) {
  if (!VALID_ERROR_CODES.has(code)) return;
  try {
    chrome.storage.session.set({ scorpionDownloadError: { code, at: Date.now() } }).catch(() => {});
  } catch (_) {}
}

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

const configReady = new Promise((resolve) => {
  chrome.storage.local.get(['scorpionConfig'], (res) => {
    if (res && res.scorpionConfig) {
      config = { ...config, ...res.scorpionConfig };
    } else {
      chrome.storage.local.set({ scorpionConfig: config });
    }
    updateContextMenus(config.lang);
    resolve(config);
  });
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

chrome.runtime.onInstalled.addListener(async () => {
  await configReady;
  updateContextMenus(config.lang);
  checkScorpionAlive();
});

if (chrome.runtime && chrome.runtime.onStartup) {
  chrome.runtime.onStartup.addListener(() => {
    checkScorpionAlive();
  });
}

let lastAliveCheckAt = 0;
function checkScorpionAliveThrottled() {
  const now = Date.now();
  if (now - lastAliveCheckAt < 2000) return;
  lastAliveCheckAt = now;
  checkScorpionAlive();
}

if (chrome.tabs) {
  chrome.tabs.onCreated.addListener(() => { checkScorpionAliveThrottled(); });
  chrome.tabs.onActivated.addListener(() => { checkScorpionAliveThrottled(); });
  chrome.tabs.onUpdated.addListener((_id, change) => { if (change.url) checkScorpionAliveThrottled(); });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const pageUrl = (info && info.pageUrl) || (tab && tab.url) || '';
  if (isDrmVideoUrl(pageUrl) || isDrmVideoUrl(info && info.srcUrl)) {
    recordPopupError('drmProtected');
    return;
  }
  if (tab && (info.menuItemId === 'scorpion-download-page-video' ||
      ScorpionMedia.isTelegram(tab.url) && info.menuItemId === 'scorpion-download-media')) {
    const hasExplicitFrame = Number.isInteger(info.frameId) && info.frameId > 0;
    const res = await dispatchMediaCommandToTab(
      tab.id,
      { action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA', src: info.srcUrl || '' },
      Number.isInteger(info.frameId) ? info.frameId : null
    );
    if (!res || !res.ok) {
      if (res && res.error === 'drmProtected') {
        recordPopupError('drmProtected');
        return;
      }
      if (!hasExplicitFrame && info.menuItemId === 'scorpion-download-page-video' && tab && tab.url) {
        await sendToScorpion({
          url: tab.url,
          pageUrl: tab.url,
          title: tab.title || 'Video',
          type: 'video',
          quality: 'best',
          incognito: Boolean(tab.incognito),
          cookies: await siteCookies([tab.url], tab),
        });
      }
    }
    return;
  }
  if (info.menuItemId === 'scorpion-download-link' && info.linkUrl) {
    await sendToScorpion({
      url: info.linkUrl,
      referer: info.pageUrl || '',
      type: 'file',
      incognito: Boolean(tab && tab.incognito),
      cookies: await siteCookies([info.linkUrl, info.pageUrl], tab),
    });
  } else if (info.menuItemId === 'scorpion-download-media' && info.srcUrl) {
    const isAudio = info.mediaType === 'audio' ||
      /\.(mp3|m4a|aac|ogg|opus|wav|flac|wma|amr|m4b|weba|aiff)(\?|$)/i.test(info.srcUrl);
    await sendToScorpion({
      url: info.srcUrl,
      referer: info.pageUrl || '',
      type: isAudio ? 'audio' : 'video',
      quality: isAudio ? 'direct' : 'best',
      incognito: Boolean(tab && tab.incognito),
      cookies: await siteCookies([info.srcUrl, info.pageUrl], tab),
    });
  } else if (info.menuItemId === 'scorpion-download-page-video' && tab && tab.url) {
    await sendToScorpion({
      url: tab.url,
      pageUrl: tab.url,
      title: tab.title || 'Video',
      type: 'video',
      quality: 'best',
      incognito: Boolean(tab.incognito),
      cookies: await siteCookies([tab.url], tab),
    });
  }
});

const DOWNLOAD_EXT_REGEX = /\.(torrent|zip|rar|7z|exe|msi|iso|dmg|pkg|deb|rpm|apk|mp4|mkv|avi|mov|webm|flv|mp3|flac|wav|m4a|ogg|opus|aac|wma|amr|m4b|weba|aiff|pdf|doc|docx|xls|xlsx|ppt|pptx|tar|gz|tgz|csv|epub|bin)(\?|$)/i;
const IGNORE_WEB_ASSET_REGEX = /\.(html?|htm|json|xml|css|js|svg|ico|webp|gif|jpe?g|png)(\?|$)/i;

chrome.downloads.onCreated.addListener(async (downloadItem) => {
  await configReady;
  if (!config.interceptAllDownloads) return;
  if (downloadItem.incognito) return;
  if (downloadItem.state && downloadItem.state !== 'in_progress') return;

  const targetUrl = downloadItem.finalUrl || downloadItem.url || '';
  if (!targetUrl.startsWith('http://') && !targetUrl.startsWith('https://')) return;
  if (targetUrl.startsWith(SCORPION_SERVER)) return;
  // Telegram's virtual addresses only exist inside the page's service worker. (No fragment check here:
  // a download the user started is a real file even if its name looks like a stream part, e.g. "init.exe" or "*.ts".)
  if (ScorpionMedia.isBrowserLocal(targetUrl)) return;

  const fileSize = downloadItem.fileSize || 0;
  const fname = downloadItem.filename || '';
  const mime = (downloadItem.mime || '').toLowerCase();
  const isTorrent =
    mime.includes('bittorrent') ||
    /\.torrent(\?|$)/i.test(targetUrl) ||
    fname.toLowerCase().endsWith('.torrent');

  const matchesDownloadExt = isTorrent || DOWNLOAD_EXT_REGEX.test(targetUrl) || DOWNLOAD_EXT_REGEX.test(fname) || mime.startsWith('audio/');
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
      type: isTorrent ? 'torrent' : (mime.startsWith('video/') ? 'video' : (mime.startsWith('audio/') ? 'audio' : 'file')),
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

let lastAppStats = null;

async function checkScorpionAlive() {
  lastAppStats = null;
  try {
    await configReady;
    const br = await detectBrowserKey();
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 1200);
    const res = await bridgeFetch(`${SCORPION_SERVER}/ping?ext=1&browser=${encodeURIComponent(br)}`, { signal: ctrl.signal });
    clearTimeout(timer);
    if (res && res.ok) {
      try {
        const data = await res.json();
        if (data && data.authenticated === false) {
          return false;
        }
        if (data && Number.isInteger(data.totalCount) && Number.isInteger(data.activeCount)) {
          lastAppStats = { totalCount: data.totalCount, activeCount: data.activeCount };
        }
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
// skipped for incognito tabs and DRM music domains whose playback routes through public fallback search.
async function siteCookies(urls, tab = null) {
  if (!chrome.cookies) return [];
  if (tab && tab.incognito) return [];
  let storeId;
  if (tab && Number.isInteger(tab.id)) {
    try {
      const stores = await chrome.cookies.getAllCookieStores();
      const hit = stores.find((s) => Array.isArray(s.tabIds) && s.tabIds.includes(tab.id));
      if (hit) storeId = hit.id;
    } catch (_) {}
  }
  const seen = new Map();
  for (const u of urls) {
    if (!u || !/^https?:\/\//i.test(u)) continue;
    try {
      const host = new URL(u).hostname;
      if (NO_COOKIE_MUSIC_HOST_RE.test(host) || DRM_VIDEO_HOST_RE.test(host)) continue;
      const query = storeId ? { url: u, storeId } : { url: u };
      for (const c of await chrome.cookies.getAll(query)) {
        seen.set(`${c.domain}|${c.path}|${c.name}`, {
          domain: c.domain, path: c.path, secure: c.secure, hostOnly: c.hostOnly,
          expirationDate: c.expirationDate || 0, name: c.name, value: c.value,
        });
      }
    } catch (_) {}
  }
  return Array.from(seen.values());
}

const recentCaptures = new Map();

async function sendToScorpion(payload) {
  const dedupKey = `${payload.url || ''}|${payload.quality || ''}|${payload.type || ''}|${payload.pageUrl || ''}`;
  const now = Date.now();
  const prev = recentCaptures.get(dedupKey);
  if (prev && (!prev.settled || (prev.ok && now - prev.ts < 1500))) {
    return prev.promise;
  }
  if (recentCaptures.size > 64) {
    for (const [k, item] of recentCaptures) {
      if ((item.settled && (!item.ok || now - item.ts >= 1500)) || recentCaptures.size > 64) {
        recentCaptures.delete(k);
      }
    }
  }
  const clientHdrs = clientHeadersFor([
    payload.url,
    payload.referer,
    payload.pageUrl,
    payload.tabUrl,
    ...(Array.isArray(payload.candidates) ? payload.candidates : []),
  ]);
  const bodyPayload = { ...clientHdrs, ...payload };
  const entry = { ts: now, settled: false, ok: false, promise: null };
  entry.promise = (async () => {
    try {
      const res = await bridgeFetch(`${SCORPION_SERVER}/capture`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bodyPayload),
      });
      let accepted = Boolean(res && res.ok);
      if (accepted && typeof res.json === 'function') {
        const data = await res.json().catch(() => ({ ok: true }));
        if (data && data.ok === false) accepted = false;
      }
      entry.settled = true;
      entry.ok = accepted;
      entry.ts = Date.now();
      if (!accepted) {
        recentCaptures.delete(dedupKey);
        return false;
      }
      return true;
    } catch (_) {
      entry.settled = true;
      entry.ok = false;
      recentCaptures.delete(dedupKey);
      return false;
    }
  })();
  recentCaptures.set(dedupKey, entry);
  return entry.promise;
}

const activeMediaFrameByTab = new Map();
const FRAME_REASON_PRIORITY = { explicit: 2, hover: 2, viewport: 2, play: 1 };

function sendMessageToFrame(tabId, message, frameId) {
  return new Promise((resolve) => {
    try {
      chrome.tabs.sendMessage(tabId, message, { frameId }, (res) => {
        if (chrome.runtime.lastError || !res) {
          resolve({ ok: false, noListener: Boolean(chrome.runtime.lastError) });
        } else {
          resolve(res);
        }
      });
    } catch (_) {
      resolve({ ok: false, noListener: true });
    }
  });
}

async function dispatchMediaCommandToTab(tabId, message, preferredFrameId = null) {
  if (Number.isInteger(preferredFrameId) && preferredFrameId >= 0) {
    const res = await sendMessageToFrame(tabId, message, preferredFrameId);
    if (res && res.ok) return { ok: true, frameId: preferredFrameId };
    return {
      ok: false,
      frameId: preferredFrameId,
      ...(res && res.error ? { error: res.error } : {}),
    };
  }
  const active = activeMediaFrameByTab.get(tabId);
  const tried = new Set();
  if (active && Number.isInteger(active.frameId) && active.frameId >= 0) {
    tried.add(active.frameId);
    const res = await sendMessageToFrame(tabId, message, active.frameId);
    if (res && res.ok) return { ok: true, frameId: active.frameId };
    if (res && res.error === 'drmProtected') {
      return { ok: false, error: 'drmProtected', frameId: active.frameId };
    }
    if ((active.prio || 1) >= 2 && !res.noListener) {
      return { ok: false, frameId: active.frameId };
    }
  }
  const frameOrder = [];
  const pushFrame = (fid) => {
    if (Number.isInteger(fid) && fid >= 0 && !tried.has(fid) && !frameOrder.includes(fid)) {
      frameOrder.push(fid);
    }
  };
  const streams = tabStreams.get(tabId);
  if (streams) {
    for (const s of Array.from(streams.values()).reverse()) {
      pushFrame(s.frameId);
    }
  }
  pushFrame(0);
  for (const fid of frameOrder) {
    const res = await sendMessageToFrame(tabId, message, fid);
    if (res && res.ok) return { ok: true, frameId: fid };
    if (res && res.error === 'drmProtected') {
      return { ok: false, error: 'drmProtected', frameId: fid };
    }
  }
  return { ok: false };
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
chrome.tabs.onRemoved.addListener((id) => {
  tabStreams.delete(id);
  activeMediaFrameByTab.delete(id);
});
chrome.tabs.onReplaced.addListener((_, removedId) => {
  tabStreams.delete(removedId);
  activeMediaFrameByTab.delete(removedId);
});
chrome.tabs.onUpdated.addListener((id, change) => {
  if (change.url) {
    tabStreams.delete(id);
    activeMediaFrameByTab.delete(id);
    chrome.tabs.sendMessage(id, { action: 'SCORPION_URL_CHANGED', url: change.url }, () => void chrome.runtime.lastError);
  }
});

function defaultAcceptLanguage() {
  try {
    const langs = Array.isArray(navigator.languages) && navigator.languages.length
      ? navigator.languages.filter(Boolean)
      : (navigator.language ? [navigator.language] : []);
    if (langs.length) {
      return langs.map((l, idx) => (idx === 0 ? l : `${l};q=${Math.max(0.1, (1 - idx * 0.1)).toFixed(1)}`)).join(',');
    }
  } catch (_) {}
  return 'en-US,en;q=0.9,ar;q=0.8';
}

const requestClientHeaders = new Map();
function recordClientHeaders(details) {
  if (!details || details.tabId < 0 || !details.url || !Array.isArray(details.requestHeaders)) return;
  let userAgent = '';
  let acceptLanguage = '';
  for (const h of details.requestHeaders) {
    const n = (h.name || '').toLowerCase();
    if (n === 'user-agent' && h.value) userAgent = h.value;
    else if (n === 'accept-language' && h.value) acceptLanguage = h.value;
  }
  if (!userAgent && !acceptLanguage) return;
  requestClientHeaders.delete(details.url);
  requestClientHeaders.set(details.url, { userAgent, acceptLanguage });
  if (requestClientHeaders.size > 120) requestClientHeaders.delete(requestClientHeaders.keys().next().value);
}

if (chrome.webRequest && chrome.webRequest.onSendHeaders) {
  try {
    chrome.webRequest.onSendHeaders.addListener(recordClientHeaders, { urls: ['http://*/*', 'https://*/*'] }, ['requestHeaders', 'extraHeaders']);
  } catch (_) {
    try {
      chrome.webRequest.onSendHeaders.addListener(recordClientHeaders, { urls: ['http://*/*', 'https://*/*'] }, ['requestHeaders']);
    } catch (_) {}
  }
}

function clientHeadersFor(urls) {
  let hit = null;
  for (const u of urls || []) {
    if (!u || typeof u !== 'string') continue;
    hit = requestClientHeaders.get(u) || requestClientHeaders.get(u.split('#')[0]);
    if (hit) break;
  }
  return {
    userAgent: (hit && hit.userAgent) || navigator.userAgent || '',
    acceptLanguage: (hit && hit.acceptLanguage) || defaultAcceptLanguage(),
  };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'SCORPION_REPORT_ERROR') {
    recordPopupError(msg.code);
    sendResponse({ ok: true });
    return false;
  }
  if (msg.action === 'SCORPION_MARK_ACTIVE_FRAME') {
    if (sender && sender.tab && Number.isInteger(sender.tab.id)) {
      const tabId = sender.tab.id;
      const fid = sender.frameId || 0;
      const prio = FRAME_REASON_PRIORITY[msg.reason] || 1;
      const prev = activeMediaFrameByTab.get(tabId);
      const prevFresh = prev && Date.now() - prev.at < 300000;
      if (!(prevFresh && prev.frameId !== fid && prev.prio > prio)) {
        activeMediaFrameByTab.set(tabId, { frameId: fid, prio, at: Date.now() });
      }
    }
    sendResponse({ ok: true });
    return false;
  }
  if (msg.action === 'SCORPION_GRAB_TAB_MEDIA') {
    (async () => {
      if (!Number.isInteger(msg.tabId)) {
        sendResponse({ handled: true, ok: false });
        return;
      }
      const res = await dispatchMediaCommandToTab(msg.tabId, {
        action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA',
        src: msg.src || '',
      });
      if (!res || !res.ok) {
        recordPopupError(res && res.error === 'drmProtected' ? 'drmProtected' : 'noVideo');
      }
      sendResponse({ handled: true, ...res });
    })();
    return true;
  }
  if (msg.action === 'SCORPION_BROWSER_TRANSFER') {
    const operation = msg.operation;
    const payload = msg.payload || {};
    const owner = `${sender.tab && sender.tab.id}:${sender.frameId || 0}:${sender.documentId || ''}`;
    if (!sender.tab || !ScorpionMedia.isTelegram(sender.url) ||
        !['start', 'chunk', 'finish', 'abort', 'heartbeat'].includes(operation) ||
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
      const res = await bridgeFetch(`${SCORPION_SERVER}/browser-transfer/${operation}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload), signal: AbortSignal.timeout(operation === 'finish' ? 120000 : 30000),
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
    if (sender && sender.tab && sender.tab.incognito) {
      payload.incognito = true;
    }
    if (isDrmVideoUrl(payload.url) || isDrmVideoUrl(payload.pageUrl)) {
      recordPopupError('drmProtected');
      sendResponse({ ok: false, error: 'drmProtected' });
      return false;
    }
    // From an embedded player (iframe): also send the page the user is on, for when the player's own
    // address doesn't identify the video
    if (sender && sender.tab && sender.frameId && sender.tab.url) payload.tabUrl = sender.tab.url;
    const generic = !payload.title || /^(scorpion_video|video|embed|player)$/i.test(String(payload.title).trim());
    const finish = async () => {
      if (msg.action === 'SCORPION_DOWNLOAD_VIDEO') {
        const tabUrl = sender && sender.tab && sender.tab.url;
        payload.cookies = await siteCookies([payload.url, payload.pageUrl, tabUrl, ...(payload.candidates || [])], sender && sender.tab);
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
    configReady.then(() => {
      const streams = tabStreams.get(sender.tab && sender.tab.id);
      sendResponse({ streams: Array.from(streams ? streams.values() : []).filter((s) =>
        Date.now() - s.t < 180000 && s.frameId === (sender.frameId || 0)).reverse(), config });
    });
    return true;
  }
  if (msg.action === 'SCORPION_LIST_QUALITIES') {
    // Reading a video's qualities can take several seconds (the app asks yt-dlp).
    // Passive hover prefetches omit cookies so tokens are never transmitted before user interaction.
    const tabUrl = (sender && sender.tab && sender.tab.url) || '';
    if (isDrmVideoUrl(msg.url) || isDrmVideoUrl(tabUrl)) {
      sendResponse({ ok: false, qualities: [] });
      return false;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 60000);
    const cookiePromise = msg.allowCookies
      ? siteCookies([msg.url, tabUrl, ...(msg.candidates || [])], sender && sender.tab)
      : Promise.resolve([]);
    cookiePromise
      .then((cookies) =>
        bridgeFetch(`${SCORPION_SERVER}/formats`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url: msg.url || '',
            referer: msg.referer || '',
            tab: tabUrl,
            candidates: msg.candidates || [],
            cookies,
            strictTarget: Boolean(msg.strictTarget),
            ...clientHeadersFor([msg.url, msg.referer, tabUrl, ...(msg.candidates || [])]),
          }),
          signal: ctrl.signal,
        })
      )
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => sendResponse(data || { ok: false }))
      .catch(() => sendResponse({ ok: false }))
      .finally(() => clearTimeout(timer));
    return true;
  }
  if (msg.action === 'SCORPION_SET_APP_LANG') {
    const lang = msg.lang === 'en' ? 'en' : 'ar';
    bridgeFetch(`${SCORPION_SERVER}/ping?set_lang=${lang}`)
      .then((r) => sendResponse({ ok: Boolean(r && r.ok) }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
  if (msg.action === 'SCORPION_GET_APP_LANG') {
    bridgeFetch(`${SCORPION_SERVER}/ping`, { signal: AbortSignal.timeout(1500) })
      .then((r) => (r && r.ok ? r.json() : null))
      .then((data) => sendResponse({ lang: data && data.lang }))
      .catch(() => sendResponse({ lang: null }));
    return true;
  }
  if (msg.action === 'SCORPION_CHECK_STATUS') {
    configReady
      .then(() => checkScorpionAlive())
      .then((alive) => sendResponse({ alive, config, stats: alive ? lastAppStats : null }));
    return true;
  }
});
