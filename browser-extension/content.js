(function () {
  if (window.__scorpionIdmInjectedV4) return;
  window.__scorpionIdmInjectedV4 = true;

  // Clean up any stale panels from an earlier extension version/reload
  document.querySelectorAll('.scorpion-idm-video-panel').forEach((el) => el.remove());

  let activeMedia = null;
  let activeMode = 'video'; // 'video' | 'audio'
  let panelEl = null;
  let dropdownEl = null;
  let labelEl = null;
  let langBtnEl = null;
  let closeBtnEl = null;
  let detectedStreams = [];
  let hideTimeout = null;
  let isHoveringPanel = false;
  let floatingBtnEnabled = true;
  let currentLang = 'ar';
  let dismissedForUrl = '';
  let panelDragging = false;
  let transferInProgress = false;
  let activeSource = '';
  let mediaGeneration = 0;
  let menuGeneration = 0;
  let pointerPosition = null;
  let selectionReason = 'viewport';
  let activePage = '';
  let viewportRefreshPending = false;

  function sourceOf(media) {
    return media && (media.currentSrc || media.src) || '';
  }

  function visibleArea(media) {
    if (!media || !media.isConnected || typeof media.getBoundingClientRect !== 'function') return 0;
    const rect = media.getBoundingClientRect();
    const isVideo = media.tagName === 'VIDEO';
    if (rect.width < (isVideo ? 160 : 120) || rect.height < (isVideo ? 100 : 20)) return 0;
    return Math.max(0, Math.min(window.innerWidth, rect.right) - Math.max(0, rect.left)) *
      Math.max(0, Math.min(window.innerHeight, rect.bottom) - Math.max(0, rect.top));
  }

  function isSelectableMedia(media) {
    if (!media || !sourceOf(media) || !visibleArea(media)) return false;
    const rect = media.getBoundingClientRect();
    return Math.min(window.innerHeight - 8, rect.bottom) - Math.max(8, rect.top + 10) >= 38;
  }

  function mediaSession() {
    return { media: activeMedia, source: sourceOf(activeMedia), page: location.href, generation: mediaGeneration,
      duration: ScorpionMedia.mediaDuration(activeMedia) };
  }

  function sessionIsCurrent(session) {
    if (!window.document) return false;
    return Boolean(session && session.media === activeMedia && session.source === sourceOf(activeMedia) &&
      session.page === location.href && session.generation === mediaGeneration && isSelectableMedia(activeMedia));
  }

  function hidePanel() {
    if (panelEl) panelEl.style.display = 'none';
    if (dropdownEl) dropdownEl.classList.remove('open');
    isHoveringPanel = false;
  }

  function chooseVisibleMedia() {
    const candidates = Array.from(document.querySelectorAll('video, audio'))
      .filter((media) => isSelectableMedia(media) && !isDismissed(media));
    const score = (media) => {
      const rect = media.getBoundingClientRect();
      const underPointer = pointerPosition && pointerPosition.x >= rect.left && pointerPosition.x <= rect.right &&
        pointerPosition.y >= rect.top && pointerPosition.y <= rect.bottom;
      const visibleCenter = (Math.max(0, rect.top) + Math.min(window.innerHeight, rect.bottom)) / 2;
      return { underPointer: Boolean(underPointer), distance: Math.abs(visibleCenter - window.innerHeight / 2) };
    };
    return candidates.sort((a, b) => {
      const sa = score(a), sb = score(b);
      return Number(sb.underPointer) - Number(sa.underPointer) || sa.distance - sb.distance || visibleArea(b) - visibleArea(a);
    })[0] || null;
  }

  const I18N = {
    ar: {
      dir: 'rtl',
      mainText: 'تحميل هذا الفيديو - Scorpion IDM',
      mainAudioText: '🎵 تحميل هذا الصوت - Scorpion IDM',
      sending: 'جاري الإرسال إلى Scorpion IDM... ⚡',
      sentOk: 'تم الإرسال إلى Scorpion IDM ✅',
      sentErr: 'تأكد من تشغيل Scorpion IDM ⚠️',
      bestHd: '🎬 أفضل جودة تشتغل على أي جهاز (MP4)',
      audioMp3: '🎵 تحميل الصوت فقط (MP3 Audio)',
      loadingQualities: '⏳ جاري قراءة الجودات المتاحة...',
      noQualities: 'تعذر قراءة الجودات — استخدم أفضل جودة',
      qualityItem: (label) => `🎞️ ${label}`,
      bestAudioOrig: '🎵 تحميل المقطع الصوتي بأعلى جودة (MP3 32-Port)',
      convertMp3: '🎧 تحويل وتحميل بصيغة MP3 (192kbps)',
      directHeader: 'الروابط المباشرة المكتشفة من المشغل:',
      directItem: (i, isAud) => (isAud ? `🎵 ملف صوتي مباشر #${i}` : `⚡ رابط مباشر #${i}`),
      langToggle: 'EN',
      langTitle: 'Switch to English',
      closeTitle: 'إغلاق الشريط',
      quickTitle: 'اضغط للتحميل بأفضل جودة — أو ▼ لاختيار الجودة',
      menuTitle: 'اختيار الجودة',
    },
    en: {
      dir: 'ltr',
      mainText: 'Download this video - Scorpion IDM',
      mainAudioText: '🎵 Download this audio - Scorpion IDM',
      sending: 'Sending to Scorpion IDM... ⚡',
      sentOk: 'Sent to Scorpion IDM ✅',
      sentErr: 'Make sure Scorpion IDM is running ⚠️',
      bestHd: '🎬 Best quality that plays everywhere (MP4)',
      audioMp3: '🎵 Audio Only (MP3 Audio)',
      loadingQualities: '⏳ Reading available qualities...',
      noQualities: "Couldn't read the qualities — use Best quality",
      qualityItem: (label) => `🎞️ ${label}`,
      bestAudioOrig: '🎵 Download Best Audio Quality (MP3 32-Port)',
      convertMp3: '🎧 Convert & Download as MP3 (192kbps)',
      directHeader: 'Direct streams detected from player:',
      directItem: (i, isAud) => (isAud ? `🎵 Direct Audio Stream #${i}` : `⚡ Direct Stream #${i}`),
      langToggle: 'ع',
      langTitle: 'التحويل إلى العربية',
      closeTitle: 'Close bar',
      quickTitle: 'Click to download in the best quality — or ▼ to pick a quality',
      menuTitle: 'Pick a quality',
    },
  };

  function t() {
    return I18N[currentLang] || I18N.ar;
  }

  function currentMainLabel() {
    const tr = t();
    return activeMode === 'audio' ? tr.mainAudioText : tr.mainText;
  }

  function applyLangToPanel() {
    const tr = t();
    if (!panelEl) return;
    panelEl.setAttribute('dir', tr.dir);
    panelEl.style.direction = tr.dir;
    if (labelEl) labelEl.textContent = currentMainLabel();
    if (langBtnEl) {
      langBtnEl.textContent = tr.langToggle;
      langBtnEl.title = tr.langTitle;
    }
    if (closeBtnEl) {
      closeBtnEl.title = tr.closeTitle;
    }
    if (dropdownEl && dropdownEl.classList.contains('open')) {
      renderDropdownOptions();
    }
  }

  function setLanguage(lang, syncRemote = true) {
    if (lang !== 'ar' && lang !== 'en') return;
    currentLang = lang;
    applyLangToPanel();
    try {
      chrome.storage.local.get(['scorpionConfig'], (res) => {
        const cfg =
          res && res.scorpionConfig
            ? { ...res.scorpionConfig, lang }
            : {
                interceptAllDownloads: true,
                showVideoFloatingBtn: true,
                minFileSizeKb: 100,
                lang,
              };
        chrome.storage.local.set({ scorpionConfig: cfg });
      });
    } catch (_) {}
    if (syncRemote) {
      try {
        chrome.runtime.sendMessage({ action: 'SCORPION_SET_APP_LANG', lang }, () => void chrome.runtime.lastError);
      } catch (_) {}
    }
  }

  function syncLangFromApp() {
    try {
      chrome.runtime.sendMessage({ action: 'SCORPION_GET_APP_LANG' }, (data) => {
        if (chrome.runtime.lastError) return;
        if (data && (data.lang === 'ar' || data.lang === 'en') && data.lang !== currentLang) {
          setLanguage(data.lang, false);
        }
      });
    } catch (_) {}
  }

  try {
    chrome.storage.local.get(['scorpionConfig'], (res) => {
      if (res && res.scorpionConfig) {
        if (typeof res.scorpionConfig.showVideoFloatingBtn === 'boolean') {
          floatingBtnEnabled = res.scorpionConfig.showVideoFloatingBtn;
        }
        if (res.scorpionConfig.lang === 'en' || res.scorpionConfig.lang === 'ar') {
          currentLang = res.scorpionConfig.lang;
          applyLangToPanel();
        }
      }
      syncLangFromApp();
    });
    chrome.storage.onChanged.addListener((changes) => {
      if (changes.scorpionConfig && changes.scorpionConfig.newValue) {
        const nv = changes.scorpionConfig.newValue;
        floatingBtnEnabled = Boolean(nv.showVideoFloatingBtn);
        if (!floatingBtnEnabled && panelEl) {
          panelEl.style.display = 'none';
        }
        if ((nv.lang === 'en' || nv.lang === 'ar') && nv.lang !== currentLang) {
          currentLang = nv.lang;
          applyLangToPanel();
        }
      }
    });
  } catch (_) {
    syncLangFromApp();
  }

  // ---------------------------------------------------------------------------
  // Stream sniffer for real Video AND Audio streams (ignoring DRM license / API endpoints)
  // ---------------------------------------------------------------------------
  const MANIFEST_RE = /\.(m3u8|mpd)(\?|#|$)/i;
  const VIDEO_RE = /\.(mp4|webm|m4v|mkv|flv|mov)(\?|#|$)/i;
  const AUDIO_RE = /\.(mp3|m4a|aac|ogg|opus|wav|flac|weba)(\?|#|$)/i;
  // Video streams whose address has no file extension (e.g. LinkedIn: dms.licdn.com/playlist/vid/.../mp4-720p-30fp/...)
  const VIDEO_HINT_RE = /\/playlist\/vid\/|[\/_-]mp4[-_\/]/i;
  // Interface sounds hosted as site assets (e.g. LinkedIn's static.licdn.com/aero-v1/sc/h/assets/<id>.m4a)
  const UI_SOUND_RE = /(^https?:\/\/static\.|\/(assets|sounds?|sfx)\/)/i;
  const IGNORE_STREAM_RE =
    /(widevine|playready|drm|license|spclient\.spotify\.com|telemetry|analytics|beacon|track_event|oauth|api-v2\.soundcloud\.com\/(me|announcements|promoted))/i;
  const MUSIC_SITE_RE = /(open\.spotify\.com|soundcloud\.com|anghami\.com|deezer\.com|music\.apple\.com|music\.youtube\.com)/i;
  const streamMap = new Map();
  let streamPage = location.href;
  let lastNetworkScan = 0;

  function detectAudioExt(url) {
    const m = String(url || '').match(/\.(mp3|m4a|aac|ogg|opus|wav|flac|weba)(\?|#|$)/i);
    return m ? m[1].toUpperCase() : 'MP3';
  }

  function considerUrl(url, initiator) {
    if (streamPage !== location.href) {
      streamMap.clear();
      detectedStreams = [];
      streamPage = location.href;
    }
    if (!url || !/^https?:\/\//i.test(url) || streamMap.has(url)) return;
    if (url.startsWith('http://127.0.0.1:19615')) return;
    if (IGNORE_STREAM_RE.test(url)) return;
    if (ScorpionMedia.isFragment(url) || ScorpionMedia.isBrowserLocal(url)) return;

    const isManifest = MANIFEST_RE.test(url) || initiator === 'manifest';
    const isAudio = !isManifest && (AUDIO_RE.test(url) || initiator === 'network-audio');
    const isVideo =
      !isManifest && !isAudio && (VIDEO_RE.test(url) || VIDEO_HINT_RE.test(url) || initiator === 'video' || initiator === 'network-video');
    if (!isManifest && !isAudio && !isVideo) return;

    // Ignore tiny UI notification sounds
    if (isAudio && /(beep|notification|click|ringtone|alert|ping|pop)\.(mp3|wav|ogg)/i.test(url)) return;
    if (isAudio && initiator !== 'audio' && UI_SOUND_RE.test(url)) return;

    // Video above audio: an audio file is never "the video" (it is offered in audio mode instead)
    let score = isManifest ? 50 : isVideo ? 40 : 30;
    if (/master|playlist|index/i.test(url)) score += 10;
    if (/(chunk|seg|frag|init)[-_]?\d*\./i.test(url)) score -= 40;
    const extTag = isManifest ? 'HLS / M3U8' : isAudio ? detectAudioExt(url) : 'MP4';
    const entry = { url, isManifest, isAudio, isVideo, extTag, score, initiator: initiator || '', t: Date.now() };
    streamMap.set(url, entry);
    if (streamMap.size > 128) streamMap.delete(streamMap.keys().next().value);
    detectedStreams = Array.from(streamMap.values()).sort((a, b) => b.score - a.score || b.t - a.t);

    // A network request alone never makes an overlay: it may belong to another player or a UI sound.
  }

  function scanPerformance() {
    try {
      performance.getEntriesByType('resource').forEach((e) => considerUrl(e.name, e.initiatorType));
    } catch (_) {}
    document.querySelectorAll('video, video source').forEach((el) => {
      considerUrl(el.currentSrc || el.src, 'video');
    });
    document.querySelectorAll('audio, audio source').forEach((el) => {
      considerUrl(el.currentSrc || el.src, 'audio');
    });
    if (Date.now() - lastNetworkScan > 1500) {
      lastNetworkScan = Date.now();
      const requestedPage = location.href;
      try {
        chrome.runtime.sendMessage({ action: 'SCORPION_GET_TAB_STREAMS' }, (res) => {
          if (chrome.runtime.lastError || requestedPage !== location.href) return;
          for (const stream of res && res.streams || []) considerUrl(stream.url,
            stream.isManifest ? 'manifest' : stream.mime.startsWith('audio/') ? 'network-audio' : 'network-video');
        });
      } catch (_) {}
    }
  }

  try {
    new PerformanceObserver((list) => {
      list.getEntries().forEach((e) => considerUrl(e.name, e.initiatorType));
    }).observe({ type: 'resource', buffered: true });
  } catch (_) {}
  scanPerformance();

  function bestStream(preferAudio = false) {
    scanPerformance();
    detectedStreams = detectedStreams.filter((s) => Date.now() - s.t < 180000);
    if (preferAudio) {
      const aud = detectedStreams.find((s) => s.isAudio || s.isManifest);
      if (aud) return aud;
      return detectedStreams.length > 0 ? detectedStreams[0] : null;
    }
    return detectedStreams.find((s) => !s.isAudio) || null;
  }

  // Embedded players often carry no video id in their address (Dailymotion's own pages load
  // geo.dailymotion.com/player/<player>.html? in an iframe). Rebuild the video page address from the
  // player's address or from the requests it made, which name the video.
  function resolveEmbeddedVideoPage(url) {
    try {
      const u = new URL(url);
      if (/(^|\.)dailymotion\.com$/i.test(u.hostname) && /^\/(player|embed)\b/i.test(u.pathname)) {
        let id = u.searchParams.get('video') || (u.pathname.match(/\/embed\/video\/([a-z0-9]+)/i) || [])[1];
        if (!id) {
          // The latest match wins, so the video playing now beats one played earlier in the same player
          for (const entry of performance.getEntriesByType('resource')) {
            const m = /dailymotion\.com\/(?:cdn\/manifest\/video|player\/metadata\/video|video)\/(x[a-z0-9]+)/i.exec(entry.name);
            if (m) id = m[1];
          }
        }
        if (id) return `https://www.dailymotion.com/video/${id}`;
      }
    } catch (_) {}
    return url;
  }

  // The address of the post holding a video on sites that show many videos in one feed (yt-dlp downloads posts)
  function resolvePostUrlForMedia(media, url) {
    try {
      if (/(^|\.)linkedin\.com$/i.test(location.hostname)) {
        const post = media && media.closest && media.closest('[data-urn*="urn:li:activity:"], [data-urn*="urn:li:ugcPost:"], [data-id*="urn:li:activity:"]');
        const urn = post && (post.getAttribute('data-urn') || post.getAttribute('data-id'));
        const m = urn && /urn:li:(activity|ugcPost):\d+/.exec(urn);
        if (m) return `https://www.linkedin.com/feed/update/${m[0]}/`;
      }
    } catch (_) {}
    return url;
  }

  // Addresses of a single post or video, on any site (feeds, profiles and timelines show many videos)
  // An address counts as a single post/video only with an id after the keyword (/videos/123, /status/170...),
  // so listings such as reddit.com/r/videos/ or a profile's "Videos" tab are not mistaken for one video
  const PERMALINK_RE =
    /\/(videos?|reels?|posts?|status(?:es)?|p|tv|shorts|clips?|comments|feed\/update|share\/[vrp]|embed)\/[\w:%.~-]{4,}|[?&](?:v|story_fbid|video_id|fbid)=[\w:%.~-]{4,}/i;
  const VIDEO_PERMALINK_RE = /\/(videos?|watch|reels?|shorts|clips?|tv|share\/[vr])(?:\/|\?|$)|[?&](?:v|video_id)=/i;

  function siteOf(host) {
    return String(host || '').toLowerCase().split('.').slice(-2).join('.');
  }

  // Walk up from the video to the nearest container holding links to a single post/video; on a feed that
  // is the post around the video, so the links name this video and not the ones in other posts
  function findPermalinksNearMedia(media) {
    const found = [];
    try {
      if (!media) return found;
      const site = siteOf(location.hostname);
      let el = media.parentElement;
      for (let depth = 0; el && el !== document.body && depth < 16 && !found.length; depth++, el = el.parentElement) {
        // Once a container holds several players, its links no longer identify this one safely.
        if (el.querySelectorAll('video, audio').length > 1) break;
        const anchors = el.querySelectorAll('a[href]');
        if (anchors.length > 400) break;
        for (const a of anchors) {
          let u;
          try {
            u = new URL(a.href, location.href);
          } catch (_) {
            continue;
          }
          if (!/^https?:$/.test(u.protocol) || siteOf(u.hostname) !== site) continue;
          if (!PERMALINK_RE.test(u.pathname + u.search) || u.href.split('#')[0] === location.href.split('#')[0]) continue;
          if (!found.includes(u.href)) found.push(u.href);
        }
      }
    } catch (_) {}
    const postIdentity = (url) => {
      const parsed = new URL(url);
      return parsed.origin + parsed.pathname.replace(/\/$/, '') +
        ['v', 'story_fbid', 'video_id', 'fbid'].map((key) => `|${key}=${parsed.searchParams.get(key) || ''}`).join('');
    };
    // Several different posts near one player are ambiguous. Never guess the first link.
    if (new Set(found.map(postIdentity)).size > 1) return [];
    return found.slice(0, 1);
  }

  // Extract the exact currently playing song title, artist, and track URL from music sites
  function extractPlayingTrackInfo() {
    const host = window.location.hostname.toLowerCase();
    let title = '';
    let artist = '';
    let trackUrl = '';

    // 1. Check MediaSession API first (supported by SoundCloud, Spotify, YouTube Music, Anghami, Deezer)
    try {
      if (navigator.mediaSession && navigator.mediaSession.metadata) {
        const md = navigator.mediaSession.metadata;
        if (md.title) title = String(md.title).trim();
        if (md.artist) artist = String(md.artist).trim();
      }
    } catch (_) {}

    // 2. SoundCloud bottom player bar (.playbackSoundBadge__titleLink has the real track URL!)
    if (host.includes('soundcloud.com')) {
      const titleLink = document.querySelector('a.playbackSoundBadge__titleLink, .playbackSoundBadge a[href*="/"]');
      const artistLink = document.querySelector('a.playbackSoundBadge__lightLink');
      if (titleLink) {
        const href = titleLink.getAttribute('href');
        if (href && href.startsWith('/') && href.split('/').filter(Boolean).length >= 2) {
          trackUrl = new URL(href.split('?')[0], 'https://soundcloud.com').href;
        }
        if (!title) {
          title = (titleLink.getAttribute('title') || titleLink.textContent || '').trim();
        }
      }
      if (artistLink && !artist) {
        artist = (artistLink.getAttribute('title') || artistLink.textContent || '').trim();
      }
    }

    // 3. Spotify bottom Now Playing bar
    if (host.includes('spotify.com')) {
      const spTitle = document.querySelector('[data-testid="context-item-link"], [data-testid="now-playing-widget"] a[href*="/track/"]');
      const spArtists = document.querySelectorAll('[data-testid="context-item-info-subtitles"] a, [data-testid="context-item-info-artist"]');
      if (spTitle) {
        if (!title) title = (spTitle.textContent || '').trim();
        const href = spTitle.getAttribute('href');
        if (href && href.includes('/track/')) {
          trackUrl = new URL(href, 'https://open.spotify.com').href;
        }
      }
      if (!artist && spArtists.length > 0) {
        artist = Array.from(spArtists)
          .map((el) => (el.textContent || '').trim())
          .filter(Boolean)
          .join(', ');
      }
    }

    let combinedTitle = '';
    if (title && artist && !title.toLowerCase().includes(artist.toLowerCase())) {
      combinedTitle = `${title} - ${artist}`;
    } else if (title) {
      combinedTitle = title;
    } else {
      const rawDocTitle = (document.title || '')
        .replace(/\s*(\||-)\s*(Spotify|SoundCloud|Anghami|Deezer|YouTube Music).*$/i, '')
        .replace(/^▶\s*/, '')
        .trim();
      combinedTitle = rawDocTitle;
    }

    return {
      title: combinedTitle || (activeMode === 'audio' ? 'Scorpion_Audio' : 'Scorpion_Video'),
      trackUrl: trackUrl || window.location.href,
    };
  }

  if (window.top === window.self) {
    try {
      chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
        if (msg && msg.action === 'SCORPION_GET_TITLE') {
          const info = extractPlayingTrackInfo();
          sendResponse({ title: info.title });
        }
        if (msg && msg.action === 'SCORPION_DOWNLOAD_CURRENT_MEDIA') {
          const media = msg.src ? Array.from(document.querySelectorAll('video')).find((el) => sourceOf(el) === msg.src) :
            (isSelectableMedia(activeMedia) ? activeMedia : chooseVisibleMedia());
          if (!isSelectableMedia(media)) { sendResponse({ ok: false }); return; }
          dismissedForUrl = '';
          media.__scorpionDismissed = '';
          activateMediaElement(media, 'explicit');
          const target = computeDownloadTarget();
          const ok = triggerVideoDownload({ url: target.targetUrl, pageUrl: target.effectivePageUrl, referer: location.href,
            candidates: target.candidates, strictTarget: true, title: target.pageTitle, quality: 'best', type: 'video' }, mediaSession());
          sendResponse({ ok });
        }
      });
    } catch (_) {}
  }

  function createFloatingPanel() {
    if (panelEl) return panelEl;

    const tr = t();
    panelEl = document.createElement('div');
    panelEl.className = 'scorpion-idm-video-panel';
    panelEl.setAttribute('dir', tr.dir);
    panelEl.style.display = 'none';

    const mainBtn = document.createElement('div');
    mainBtn.className = 'scorpion-idm-main-btn';

    const triggerEl = document.createElement('div');
    triggerEl.className = 'scorpion-idm-trigger';
    triggerEl.innerHTML = `
      <span>🦂</span>
      <span class="scorpion-btn-text">${currentMainLabel()}</span>
      <span class="scorpion-idm-badge">▼</span>
    `;
    labelEl = triggerEl.querySelector('.scorpion-btn-text');
    triggerEl.title = tr.quickTitle;
    triggerEl.querySelector('.scorpion-idm-badge').title = tr.menuTitle;

    langBtnEl = document.createElement('button');
    langBtnEl.type = 'button';
    langBtnEl.className = 'scorpion-idm-lang-btn';
    langBtnEl.textContent = tr.langToggle;
    langBtnEl.title = tr.langTitle;
    langBtnEl.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      setLanguage(currentLang === 'ar' ? 'en' : 'ar', true);
    });

    closeBtnEl = document.createElement('button');
    closeBtnEl.type = 'button';
    closeBtnEl.className = 'scorpion-idm-close-btn';
    closeBtnEl.innerHTML = '&#10005;';
    closeBtnEl.title = tr.closeTitle;
    closeBtnEl.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      dismissedForUrl = window.location.href;
      if (activeMedia) {
        activeMedia.__scorpionDismissed = window.location.href;
      }
      if (dropdownEl) dropdownEl.classList.remove('open');
      if (panelEl) panelEl.style.display = 'none';
      if (hideTimeout) clearTimeout(hideTimeout);
    });

    const dragHandle = document.createElement('button');
    dragHandle.type = 'button';
    dragHandle.className = 'scorpion-idm-drag-handle';
    dragHandle.textContent = '⠿';
    dragHandle.title = currentLang === 'ar' ? 'اسحب لتحريك الشريط' : 'Drag to move the bar';
    mainBtn.appendChild(dragHandle);
    mainBtn.appendChild(triggerEl);
    mainBtn.appendChild(langBtnEl);
    mainBtn.appendChild(closeBtnEl);

    dropdownEl = document.createElement('div');
    dropdownEl.className = 'scorpion-idm-dropdown';

    let didMove = false;
    let dragOffsetX = 0;
    let dragOffsetY = 0;

    dragHandle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();
      panelDragging = true;
      didMove = false;
      dragHandle.setPointerCapture(e.pointerId);
      const r = panelEl.getBoundingClientRect();
      dragOffsetX = e.clientX - r.left;
      dragOffsetY = e.clientY - r.top;
    });

    const endDrag = () => {
      panelDragging = false;
    };
    dragHandle.addEventListener('pointermove', (e) => {
      if (!panelDragging || !panelEl) return;
      // Button no longer held (release missed, e.g. outside the window): the drag is over
      if (!(e.buttons & 1)) {
        endDrag();
        return;
      }
      const dx = Math.abs(e.clientX - (panelEl.getBoundingClientRect().left + dragOffsetX));
      const dy = Math.abs(e.clientY - (panelEl.getBoundingClientRect().top + dragOffsetY));
      if (dx > 8 || dy > 8) didMove = true;
      if (!didMove) return;
      const panelW = panelEl.offsetWidth || 310;
      const newLeft = Math.max(8, Math.min(window.innerWidth - panelW - 8, e.clientX - dragOffsetX));
      const newTop = Math.max(8, Math.min(window.innerHeight - 52, e.clientY - dragOffsetY));
      panelEl.style.left = `${newLeft}px`;
      panelEl.style.top = `${newTop}px`;
      panelEl.style.right = 'auto';
      panelEl.style.bottom = 'auto';
      panelEl.__userDraggedPos = { left: newLeft, top: newTop };
    });

    // Capture phase: the panel stops presses from reaching the page, which must not hide the release from us
    dragHandle.addEventListener('pointerup', endDrag);
    dragHandle.addEventListener('pointercancel', endDrag);
    dragHandle.addEventListener('lostpointercapture', endDrag);
    window.addEventListener('blur', endDrag);

    triggerEl.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      renderDropdownOptions();
      if (!(e.target.closest && e.target.closest('.scorpion-idm-badge'))) {
        // Quick download: the first option is "best quality" (or best audio in audio mode)
        const first = dropdownEl.querySelector('.scorpion-idm-option');
        if (first) {
          first.click();
          return;
        }
      }
      if (panelEl && dropdownEl) {
        const pRect = panelEl.getBoundingClientRect();
        if (window.innerHeight - pRect.bottom < 220) {
          dropdownEl.classList.add('drop-up');
        } else {
          dropdownEl.classList.remove('drop-up');
        }
      }
      dropdownEl.classList.toggle('open');
    });

    panelEl.addEventListener('mouseenter', () => {
      isHoveringPanel = true;
      if (hideTimeout) clearTimeout(hideTimeout);
    });

    panelEl.addEventListener('mouseleave', () => {
      isHoveringPanel = false;
    });

    ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'touchstart', 'touchend', 'dblclick'].forEach((type) => {
      panelEl.addEventListener(type, (e) => e.stopPropagation());
    });

    panelEl.appendChild(mainBtn);
    panelEl.appendChild(dropdownEl);
    document.documentElement.appendChild(panelEl);
    return panelEl;
  }

  function computeDownloadTarget() {
    const pageUrl = window.location.href;
    const isFramed = window.top !== window.self;
    const trackInfo = extractPlayingTrackInfo();
    const pageTitle = trackInfo.title;

    const directMediaSrc =
      activeMedia &&
      (activeMedia.currentSrc || activeMedia.src) &&
      /^https?:\/\//i.test(activeMedia.currentSrc || activeMedia.src) &&
      !ScorpionMedia.isFragment(activeMedia.currentSrc || activeMedia.src) &&
      !IGNORE_STREAM_RE.test(activeMedia.currentSrc || activeMedia.src)
        ? activeMedia.currentSrc || activeMedia.src
        : null;

    // Requests are frame-wide, so only the actual element's source is a proven stream for this player.
    const sources = new Set([sourceOf(activeMedia), ...(activeMedia ? Array.from(activeMedia.querySelectorAll('source')).map((s) => s.src) : [])]);
    const scopedStreams = detectedStreams.filter((stream) => sources.has(stream.url));
    const sniffed = scopedStreams.find((stream) => stream.isManifest) || scopedStreams[0];
    const permalinks = findPermalinksNearMedia(activeMedia);
    // A track address from a music site wins; otherwise the post around the video beats the feed's address
    const trackUrl = activeMedia && activeMedia.tagName === 'AUDIO' && trackInfo.trackUrl && trackInfo.trackUrl !== pageUrl ? trackInfo.trackUrl : '';
    const effectivePageUrl =
      resolvePostUrlForMedia(activeMedia, resolveEmbeddedVideoPage(trackUrl || permalinks[0] || pageUrl));
    const isMusicPlatform = MUSIC_SITE_RE.test(isFramed ? document.referrer || effectivePageUrl : effectivePageUrl);
    const isKnownVideoSite =
      /youtube\.com|youtu\.be|facebook\.com|instagram\.com|tiktok\.com|twitter\.com|x\.com|vimeo\.com|dailymotion\.com|linkedin\.com\/(feed\/update|posts)\//i.test(
        isFramed ? document.referrer || effectivePageUrl : effectivePageUrl
      );

    let targetUrl = effectivePageUrl;
    const multipleMedia = document.querySelectorAll('video, audio').length > 1;
    const scopedPost = permalinks.length > 0 || resolvePostUrlForMedia(activeMedia, pageUrl) !== pageUrl ||
      !multipleMedia && (effectivePageUrl !== pageUrl || PERMALINK_RE.test(location.pathname + location.search));
    const ambiguous = multipleMedia && !scopedPost && !directMediaSrc && !ScorpionMedia.isTelegram(pageUrl);
    if ((!isKnownVideoSite && !isMusicPlatform) || multipleMedia && directMediaSrc) {
      if (directMediaSrc) targetUrl = directMediaSrc;
      else if (sniffed && sniffed.isManifest) targetUrl = sniffed.url;
      // A page extractor is safer than an unrelated short MP4 loaded by an ad or background animation.
    }
    const candidates = [];
    const addCandidate = (u) => {
      if (u && /^https?:\/\//i.test(u) && !candidates.includes(u)) candidates.push(u);
    };
    [targetUrl, ...permalinks, directMediaSrc, ...(!multipleMedia ? [effectivePageUrl] : [])].forEach(addCandidate);
    scopedStreams.forEach((stream) => addCandidate(stream.url));
    return { pageUrl, pageTitle, effectivePageUrl, isMusicPlatform, isKnownVideoSite, targetUrl, candidates, scopedStreams, ambiguous };
  }

  // Read the qualities as soon as the button shows, so the menu is complete when it opens
  function prefetchQualities() {
    if (activeMode !== 'video') return;
    if (ScorpionMedia.isTelegram(location.href)) return;
    try {
      const tgt = computeDownloadTarget();
      if (!tgt.isMusicPlatform && !tgt.ambiguous) listQualities(tgt.targetUrl, tgt.pageUrl, tgt.candidates);
    } catch (_) {}
  }

  function renderDropdownOptions() {
    if (!dropdownEl) return;
    const session = mediaSession();
    const renderedMenu = ++menuGeneration;
    dropdownEl.innerHTML = '';
    const tr = t();
    const { pageUrl, pageTitle, effectivePageUrl, isMusicPlatform, isKnownVideoSite, targetUrl, candidates, scopedStreams, ambiguous } = computeDownloadTarget();
    if (ambiguous) {
      const message = document.createElement('div');
      message.className = 'scorpion-idm-hint';
      message.textContent = currentLang === 'ar' ? 'افتح منشور الفيديو نفسه لتحديده بدقة، ثم شغّله.' :
        'Open this video’s own post and play it to identify its source.';
      dropdownEl.appendChild(message);
      return;
    }

    const isDirectAudioFile =
      activeMode === 'audio' &&
      !isMusicPlatform &&
      !isKnownVideoSite &&
      AUDIO_RE.test(targetUrl);

    let presets = [];
    if (activeMode === 'audio' || isMusicPlatform) {
      const extLower = isDirectAudioFile ? detectAudioExt(targetUrl).toLowerCase() : 'mp3';
      presets = [
        {
          label: tr.bestAudioOrig,
          tag: isDirectAudioFile ? detectAudioExt(targetUrl) : 'MP3 32-PORT',
          quality: isDirectAudioFile ? 'direct' : 'audio',
          type: 'audio',
          url: targetUrl,
          filename: `${pageTitle}.${extLower}`,
        },
        {
          label: tr.convertMp3,
          tag: 'MP3 192K',
          quality: 'audio',
          type: 'audio',
          url: effectivePageUrl,
          filename: `${pageTitle}.mp3`,
        },
      ];
    } else {
      presets = [
        {
          label: tr.bestHd,
          tag: 'BEST HD',
          quality: 'best',
          type: 'video',
          url: targetUrl,
        },
        {
          label: tr.audioMp3,
          tag: 'MP3',
          quality: 'audio',
          type: 'audio',
          url: targetUrl,
        },
      ];
    }

    const makeOption = (opt) => {
      const btn = document.createElement('button');
      btn.className = 'scorpion-idm-option';
      btn.innerHTML = `
        <span></span>
        <span class="scorpion-idm-option-tag"></span>
      `;
      btn.children[0].textContent = opt.label;
      btn.children[1].textContent = opt.tag;
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        triggerVideoDownload({
          url: opt.url,
          pageUrl: effectivePageUrl,
          referer: pageUrl,
          title: pageTitle,
          quality: opt.quality,
          type: opt.type || 'video',
          filename: opt.filename || '',
          candidates,
          strictTarget: true,
        }, session);
      });
      return btn;
    };
    presets.forEach((opt) => dropdownEl.appendChild(makeOption(opt)));

    // Every quality the video really offers, read by the app (yt-dlp), listed under "best"
    if (!(activeMode === 'audio' || isMusicPlatform || ScorpionMedia.isTelegram(pageUrl))) {
      const box = document.createElement('div');
      const status = document.createElement('div');
      status.style.cssText = 'font-size:11px;color:#94a3b8;padding:6px 10px;';
      status.textContent = tr.loadingQualities;
      box.appendChild(status);
      dropdownEl.insertBefore(box, dropdownEl.children[1] || null);
      listQualities(targetUrl, pageUrl, candidates).then((res) => {
        if (!sessionIsCurrent(session) || renderedMenu !== menuGeneration || !box.isConnected) return;
        const list = (res && res.qualities) || [];
        if (!list.length) {
          status.textContent = tr.noQualities;
          return;
        }
        status.remove();
        list.forEach((q) => {
          const size = q.size ? `~${q.size >= 1073741824 ? (q.size / 1073741824).toFixed(1) + ' GB' : Math.round(q.size / 1048576) + ' MB'}` : '';
          box.appendChild(
            makeOption({ label: t().qualityItem(q.label), tag: size || q.quality, quality: q.quality, type: 'video', url: targetUrl })
          );
        });
      });
    }

    // Only list raw network streams when not on a DRM music site (where raw URLs require DRM keys)
    if (!isMusicPlatform && scopedStreams.length > 0) {
      const sep = document.createElement('div');
      sep.style.cssText =
        'border-top:1px solid #1e293b;margin:4px 0;padding-top:4px;font-size:10px;color:#94a3b8;padding-inline:8px;';
      sep.textContent = tr.directHeader;
      dropdownEl.appendChild(sep);

      scopedStreams.slice(0, 4).forEach((st, idx) => {
        const tag = st.extTag || (st.isManifest ? 'HLS / M3U8' : st.isAudio ? 'MP3' : 'MP4');
        const btn = document.createElement('button');
        btn.className = 'scorpion-idm-option';
        btn.innerHTML = `
          <span>${tr.directItem(idx + 1, st.isAudio)}</span>
          <span class="scorpion-idm-option-tag">${tag}</span>
        `;
        btn.title = st.url;
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          e.preventDefault();
          const ext = st.isAudio ? detectAudioExt(st.url).toLowerCase() : 'mp4';
          triggerVideoDownload({
            url: st.url,
            pageUrl: effectivePageUrl,
            referer: pageUrl,
            title: pageTitle,
            quality: st.isManifest ? (activeMode === 'audio' ? 'audio' : 'best') : 'direct',
            type: st.isAudio ? 'audio' : st.isManifest ? 'video' : 'file',
            filename: st.isManifest ? '' : `${pageTitle}.${ext}`,
            candidates,
            strictTarget: true,
          }, session);
        });
        dropdownEl.appendChild(btn);
      });
    }
  }

  // Qualities per address, cached so reopening the menu is instant (one request per video)
  const qualityCache = new Map();
  function listQualities(url, referer, candidates) {
    if (!qualityCache.has(url)) {
      qualityCache.set(
        url,
        new Promise((resolve) => {
          try {
            chrome.runtime.sendMessage({ action: 'SCORPION_LIST_QUALITIES', url, referer, candidates: candidates || [], strictTarget: true }, (res) => {
              if (chrome.runtime.lastError || !res || !res.ok) qualityCache.delete(url);
              resolve(chrome.runtime.lastError ? null : res);
            });
          } catch (_) {
            qualityCache.delete(url);
            resolve(null);
          }
        })
      );
    }
    return qualityCache.get(url);
  }

  function triggerVideoDownload(payload, session = mediaSession()) {
    if (transferInProgress || !sessionIsCurrent(session)) return false;
    if (computeDownloadTarget().ambiguous) return false;
    payload.expectedDuration = session.duration;
    const tr = t();
    dropdownEl.classList.remove('open');
    if (labelEl) {
      labelEl.textContent = tr.sending;
    }

    const onDone = (ok, error = '') => {
      if (!sessionIsCurrent(session)) return;
      if (labelEl) {
        labelEl.textContent = ok ? tr.sentOk : error || tr.sentErr;
        labelEl.title = error;
      }
      setTimeout(() => {
        if (labelEl && sessionIsCurrent(session)) {
          labelEl.textContent = currentMainLabel();
        }
      }, 2200);
    };

    const directFallback = () => onDone(false);

    if (ScorpionMedia.isTelegram(location.href)) {
      // Use only THIS player's source, never another document found in the page's request history.
      const src = session.source;
      if (!src || !ScorpionMedia.isBrowserLocal(src) || /^blob:/i.test(src)) {
        onDone(false, currentLang === 'ar' ? 'افتح الفيديو وشغّله، ثم أعد المحاولة. يمكنك استخدام تنزيل تليجرام الأصلي.' :
          'Open and play this video, then retry. Telegram’s own download button is also available.');
        return;
      }
      if (payload.quality === 'audio') {
        onDone(false, currentLang === 'ar' ? 'نزّل فيديو تليجرام كاملًا أولًا؛ تحويل الصوت غير متاح لهذا المسار.' :
          'Download the full Telegram video first; audio conversion is not supported for this transfer.');
        return;
      }
      const request = (operation, data) => new Promise((resolve, reject) => {
        chrome.runtime.sendMessage({ action: 'SCORPION_BROWSER_TRANSFER', operation, payload: data }, (res) => {
          if (chrome.runtime.lastError || !res) reject(new Error('الاتصال بالبرنامج انقطع. أعد المحاولة.'));
          else resolve(res);
        });
      });
      transferInProgress = true;
      ScorpionTransfer.transfer(src, {
        filename: payload.filename || `${payload.title || 'Telegram_Video'}.mp4`,
        pageUrl: location.href, expectedDuration: payload.expectedDuration,
      }, request, fetch, (done, total) => {
        if (labelEl && sessionIsCurrent(session)) labelEl.textContent = `${currentLang === 'ar' ? 'جارٍ التنزيل' : 'Downloading'} ${Math.min(99, Math.floor(done / total * 100))}%`;
      }, readTelegramPageRange).then(() => onDone(true)).catch((err) => onDone(false, err.message))
        .finally(() => { transferInProgress = false; });
      return true;
    }

    try {
      chrome.runtime.sendMessage(
        {
          action: 'SCORPION_DOWNLOAD_VIDEO',
          payload,
        },
        (res) => {
          if (chrome.runtime.lastError || !res || !res.ok) {
            directFallback();
          } else {
            onDone(true);
          }
        }
      );
    } catch (_) {
      directFallback();
    }
    return true;
  }

  function readTelegramPageRange(url, offset, total) {
    return new Promise((resolve, reject) => {
      const requestId = crypto.randomUUID();
      const finish = (error, result) => {
        clearTimeout(timer);
        window.removeEventListener('message', listener);
        if (error) reject(error); else resolve(result);
      };
      const listener = (event) => {
        const msg = event.data;
        if (event.source !== window || event.origin !== location.origin || !msg ||
            msg.action !== 'SCORPION_MEDIA_RANGE_RESULT' || msg.requestId !== requestId) return;
        if (msg.error) return finish(new Error(msg.error));
        const part = msg.part;
        if (!part || typeof part.data !== 'string' || part.data.length > 710000 ||
            !Number.isSafeInteger(part.total) || part.total <= offset || total && part.total !== total)
          return finish(new Error('بيانات جزء الفيديو غير صالحة.'));
        try {
          const binary = atob(part.data);
          if (!binary.length || binary.length > ScorpionTransfer.CHUNK_SIZE || offset + binary.length > part.total)
            return finish(new Error('حجم جزء الفيديو غير صالح.'));
          finish(null, { bytes: Uint8Array.from(binary, (c) => c.charCodeAt(0)), total: part.total, mime: part.mime });
        } catch (_) { finish(new Error('تعذر قراءة جزء الفيديو.')); }
      };
      const timer = setTimeout(() => finish(new Error('تعذر الاتصال بمشغّل تليجرام. حدّث الإضافة وأعد تحميل الصفحة.')), 95000);
      window.addEventListener('message', listener);
      window.postMessage({ action: 'SCORPION_READ_MEDIA_RANGE', requestId, url, offset, total }, location.origin);
    });
  }

  function isDismissed(media) {
    if (dismissedForUrl && dismissedForUrl === window.location.href) return true;
    if (media && media.__scorpionDismissed && media.__scorpionDismissed === window.location.href) return true;
    return false;
  }

  function positionPanelOverMedia(media) {
    if (!floatingBtnEnabled || isDismissed(media) || !isSelectableMedia(media)) {
      hidePanel();
      return;
    }
    const rect = media.getBoundingClientRect();
    const visibleTop = Math.max(8, rect.top + 10);
    const visibleBottom = Math.min(window.innerHeight - 8, rect.bottom);
    if (visibleBottom - visibleTop < 38) { hidePanel(); return; }

    createFloatingPanel();
    if (labelEl && !transferInProgress && labelEl.textContent !== currentMainLabel()) labelEl.textContent = currentMainLabel();

    const hostEl = document.fullscreenElement || document.documentElement;
    if (panelEl.parentElement !== hostEl) {
      hostEl.appendChild(panelEl);
    }

    const panelW = Math.max(290, panelEl.offsetWidth || 320);

    if (panelEl.__userDraggedPos) {
      const clampedLeft = Math.max(8, Math.min(window.innerWidth - panelW - 8, panelEl.__userDraggedPos.left));
      const clampedTop = Math.max(8, Math.min(window.innerHeight - 52, panelEl.__userDraggedPos.top));
      panelEl.style.top = `${clampedTop}px`;
      panelEl.style.left = `${clampedLeft}px`;
      panelEl.style.bottom = 'auto';
      panelEl.style.right = 'auto';
      panelEl.style.display = 'block';
      return;
    }

    // Every path assigns viewport coordinates BEFORE showing the element. A partly scrolled video
    // must not leave a fixed element at the document's static position near the bottom of the page.
    panelEl.style.top = `${Math.min(visibleTop, visibleBottom - 38)}px`;
    panelEl.style.left = `${Math.max(8, Math.min(window.innerWidth - panelW - 8, rect.right - panelW - 10))}px`;
    panelEl.style.bottom = 'auto';
    panelEl.style.right = 'auto';
    panelEl.style.display = 'block';
  }

  function activateMediaElement(media, reason = 'scan') {
    if (!isSelectableMedia(media)) return false;
    // Playback in another feed item is not a selection. Hover, scroll, or an explicit command is.
    if (['play', 'scan'].includes(reason) && media !== activeMedia && isSelectableMedia(activeMedia)) return false;
    if (dismissedForUrl && dismissedForUrl !== window.location.href) {
      dismissedForUrl = '';
    }
    if (isDismissed(media)) return false;
    const changed = media !== activeMedia || sourceOf(media) !== activeSource || activePage !== location.href;
    if (changed) {
      mediaGeneration++;
      menuGeneration++;
      if (dropdownEl) { dropdownEl.classList.remove('open'); dropdownEl.innerHTML = ''; }
      if (panelEl) delete panelEl.__userDraggedPos;
      panelDragging = false;
      isHoveringPanel = false;
    }
    if (panelDragging && !changed) return false;
    const isAud = media.tagName === 'AUDIO' || MUSIC_SITE_RE.test(window.location.hostname);
    if (media.currentSrc || media.src) {
      considerUrl(media.currentSrc || media.src, isAud ? 'audio' : 'video');
    }
    activeMedia = media;
    activeSource = sourceOf(media);
    activePage = location.href;
    selectionReason = reason;
    activeMode = isAud ? 'audio' : 'video';
    positionPanelOverMedia(media);
    const session = mediaSession();
    const prefetchKey = `${location.href}|${activeSource}`;
    if (media.__scorpionPrefetchedFor !== prefetchKey) {
      media.__scorpionPrefetchedFor = prefetchKey;
      setTimeout(() => { if (sessionIsCurrent(session)) prefetchQualities(); }, 600);
    }
    return true;
  }

  function bindMediaElement(media) {
    if (media.__scorpionBoundV4) return;
    media.__scorpionBoundV4 = true;

    media.addEventListener('play', () => activateMediaElement(media, 'play'));
    media.addEventListener('playing', () => activateMediaElement(media, 'play'));
    media.addEventListener('pointerenter', () => activateMediaElement(media, 'hover'));
    media.addEventListener('mouseenter', () => activateMediaElement(media, 'hover'));
    media.addEventListener('loadeddata', () => refreshMediaSelection());
    // Pause/end do not invalidate an explicitly selected video; source/removal/visibility do.
    for (const event of ['pause', 'ended', 'emptied', 'error']) media.addEventListener(event, () => refreshMediaSelection());
  }

  function scanForMedia() {
    if (!window.document) return;
    document.querySelectorAll('video, audio').forEach(bindMediaElement);
    refreshMediaSelection();
  }

  function refreshMediaSelection(reason = 'scan') {
    if (!window.document) return;
    if (reason === 'viewport' && !panelDragging) {
      const selected = chooseVisibleMedia();
      if (selected) { activateMediaElement(selected, 'viewport'); return; }
    }
    if (isSelectableMedia(activeMedia) && !isDismissed(activeMedia)) {
      if (sourceOf(activeMedia) !== activeSource || activePage !== location.href) activateMediaElement(activeMedia, selectionReason);
      else if (!panelDragging && !isHoveringPanel) positionPanelOverMedia(activeMedia);
      return;
    }
    if (activeMedia) { mediaGeneration++; menuGeneration++; }
    activeMedia = null;
    activeSource = '';
    hidePanel();
    const next = chooseVisibleMedia();
    if (next) activateMediaElement(next, 'viewport');
  }

  document.addEventListener(
    'play',
    (e) => {
      const tEl = e.target;
      if (tEl && (tEl.tagName === 'VIDEO' || tEl.tagName === 'AUDIO')) {
        bindMediaElement(tEl);
        activateMediaElement(tEl, 'play');
      }
    },
    true
  );

  scanForMedia();
  let mediaScanPending = false;
  const observer = new MutationObserver((changes) => {
    // Do not observe our own label/menu changes or rescan an entire feed for every text mutation.
    const relevant = changes.some((change) => (!panelEl || !panelEl.contains(change.target)) &&
      (change.type === 'attributes' && change.target.matches('video, audio, source') ||
      [...change.addedNodes, ...change.removedNodes].some((node) => node.nodeType === 1 &&
        (node.matches('video, audio') || node.querySelector('video, audio')))));
    if (!relevant || mediaScanPending) return;
    mediaScanPending = true;
    requestAnimationFrame(() => { mediaScanPending = false; scanForMedia(); });
  });
  observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });

  function scheduleViewportRefresh() {
    if (viewportRefreshPending) return;
    viewportRefreshPending = true;
    requestAnimationFrame(() => { viewportRefreshPending = false; refreshMediaSelection('viewport'); });
  }

  window.addEventListener(
    'scroll',
    (event) => {
      if (panelEl && event.target && event.target.nodeType && panelEl.contains(event.target)) return;
      scheduleViewportRefresh();
    },
    { passive: true, capture: true }
  );
  window.addEventListener('resize', scheduleViewportRefresh, { passive: true });
  window.addEventListener('hashchange', scheduleViewportRefresh);
  window.addEventListener('popstate', scheduleViewportRefresh);
  document.addEventListener('fullscreenchange', scheduleViewportRefresh);
  document.addEventListener('pointermove', (event) => {
    if (!panelEl || !panelEl.contains(event.target)) pointerPosition = { x: event.clientX, y: event.clientY };
  }, { passive: true });
  document.addEventListener('pointerover', (event) => {
    if (panelEl && panelEl.contains(event.target)) return;
    pointerPosition = { x: event.clientX, y: event.clientY };
    // Poster images and player controls often cover the <video>. Resolve only their nearest
    // single-player container and verify the pointer is inside that player's actual rectangle.
    let target = event.target;
    for (let depth = 0; target && target !== document.body && target.nodeType === 1 && depth < 10; depth++, target = target.parentElement) {
      const players = target.matches('video, audio') ? [target] : Array.from(target.querySelectorAll('video, audio'));
      if (players.length > 1) break;
      if (!players.length) continue;
      const rect = players[0].getBoundingClientRect();
      if (event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom)
        activateMediaElement(players[0], 'hover');
      break;
    }
  }, { passive: true });

  // Intercept Magnet links & direct .torrent links so Scorpion IDM handles them automatically
  document.addEventListener(
    'click',
    (e) => {
      if (panelEl && dropdownEl && dropdownEl.classList.contains('open') && !panelEl.contains(e.target)) {
        dropdownEl.classList.remove('open');
      }
      const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
      if (!a) return;
      const href = (a.getAttribute('href') || '').trim();
      if (href.toLowerCase().startsWith('magnet:?')) {
        e.preventDefault();
        e.stopPropagation();
        const fallback = () => {
          window.location.href = href;
        };
        try {
          chrome.runtime.sendMessage(
            {
              action: 'SCORPION_DOWNLOAD_LINK',
              payload: {
                url: href,
                referer: window.location.href,
                title: document.title || 'Torrent',
                type: 'torrent',
              },
            },
            (res) => {
              if (chrome.runtime.lastError || !res || !res.ok) fallback();
            }
          );
        } catch (_) {
          fallback();
        }
      }
    },
    true
  );
})();
