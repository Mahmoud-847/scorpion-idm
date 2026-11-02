const SCORPION_SERVER = 'http://127.0.0.1:19615';

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
    chrome.downloads.cancel(downloadItem.id, () => {
      chrome.downloads.erase({ id: downloadItem.id });
    });

    await sendToScorpion({
      url: targetUrl,
      filename: downloadItem.filename ? downloadItem.filename.split(/[\\/]/).pop() : '',
      referer: downloadItem.referrer || '',
      totalSize: fileSize > 0 ? fileSize : 0,
      type: isTorrent ? 'torrent' : 'file',
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
    const res = await fetch(`${SCORPION_SERVER}/ping?ext=1&browser=${encodeURIComponent(br)}`, { signal: ctrl.signal });
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

async function sendToScorpion(payload) {
  try {
    const res = await fetch(`${SCORPION_SERVER}/capture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return res.ok;
  } catch (_) {
    return false;
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'SCORPION_DOWNLOAD_VIDEO' || msg.action === 'SCORPION_DOWNLOAD_LINK') {
    const payload = { ...(msg.payload || {}) };
    const generic = !payload.title || /^(scorpion_video|video|embed|player)$/i.test(String(payload.title).trim());
    const finish = () => sendToScorpion(payload).then((ok) => sendResponse({ ok }));
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
    sendResponse({ streams: [], config });
    return true;
  }
  if (msg.action === 'SCORPION_CHECK_STATUS') {
    checkScorpionAlive().then((alive) => sendResponse({ alive, config }));
    return true;
  }
});
