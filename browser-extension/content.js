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
    /(widevine|playready|drm|license|spclient\.spotify\.com|telemetry|analytics|beacon|track_event|oauth|token|api-v2\.soundcloud\.com\/(me|announcements|promoted))/i;
  const MUSIC_SITE_RE = /(open\.spotify\.com|soundcloud\.com|anghami\.com|deezer\.com|music\.apple\.com|music\.youtube\.com)/i;
  const streamMap = new Map();

  function detectAudioExt(url) {
    const m = String(url || '').match(/\.(mp3|m4a|aac|ogg|opus|wav|flac|weba)(\?|#|$)/i);
    return m ? m[1].toUpperCase() : 'MP3';
  }

  function considerUrl(url, initiator) {
    if (!url || !/^https?:\/\//i.test(url) || streamMap.has(url)) return;
    if (url.startsWith('http://127.0.0.1:19615')) return;
    if (IGNORE_STREAM_RE.test(url)) return;

    const isManifest = MANIFEST_RE.test(url);
    const isAudio = !isManifest && AUDIO_RE.test(url);
    const isVideo =
      !isManifest && !isAudio && (VIDEO_RE.test(url) || VIDEO_HINT_RE.test(url) || initiator === 'video');
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
    detectedStreams = Array.from(streamMap.values()).sort((a, b) => b.score - a.score || b.t - a.t);

    if (isAudio && (!activeMedia || activeMode === 'audio') && window.top === window.self) {
      showForAudioStream();
    }
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
  }

  try {
    new PerformanceObserver((list) => {
      list.getEntries().forEach((e) => considerUrl(e.name, e.initiatorType));
    }).observe({ type: 'resource', buffered: true });
  } catch (_) {}
  scanPerformance();

  function bestStream(preferAudio = false) {
    scanPerformance();
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
    });

    mainBtn.appendChild(triggerEl);
    mainBtn.appendChild(langBtnEl);
    mainBtn.appendChild(closeBtnEl);

    dropdownEl = document.createElement('div');
    dropdownEl.className = 'scorpion-idm-dropdown';

    let isDragging = false;
    let didMove = false;
    let dragOffsetX = 0;
    let dragOffsetY = 0;

    mainBtn.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      if (e.target === langBtnEl || e.target === closeBtnEl) return;
      isDragging = true;
      didMove = false;
      const r = panelEl.getBoundingClientRect();
      dragOffsetX = e.clientX - r.left;
      dragOffsetY = e.clientY - r.top;
    });

    window.addEventListener('mousemove', (e) => {
      if (!isDragging || !panelEl) return;
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

    window.addEventListener('mouseup', () => {
      isDragging = false;
    });

    triggerEl.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (didMove) {
        didMove = false;
        return;
      }
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
      scheduleHide();
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
      !IGNORE_STREAM_RE.test(activeMedia.currentSrc || activeMedia.src)
        ? activeMedia.currentSrc || activeMedia.src
        : null;

    const sniffed = bestStream(activeMode === 'audio');
    const effectivePageUrl = resolvePostUrlForMedia(activeMedia, resolveEmbeddedVideoPage(trackInfo.trackUrl || pageUrl));
    const isMusicPlatform = MUSIC_SITE_RE.test(isFramed ? document.referrer || effectivePageUrl : effectivePageUrl);
    const isKnownVideoSite =
      /youtube\.com|youtu\.be|facebook\.com|instagram\.com|tiktok\.com|twitter\.com|x\.com|vimeo\.com|dailymotion\.com|linkedin\.com\/(feed\/update|posts)\//i.test(
        isFramed ? document.referrer || effectivePageUrl : effectivePageUrl
      );

    let targetUrl = effectivePageUrl;
    if (!isKnownVideoSite && !isMusicPlatform) {
      if (directMediaSrc) targetUrl = directMediaSrc;
      else if (sniffed && sniffed.isManifest) targetUrl = sniffed.url;
      else if (sniffed) targetUrl = sniffed.url;
    }
    return { pageUrl, pageTitle, effectivePageUrl, isMusicPlatform, isKnownVideoSite, targetUrl };
  }

  // Read the qualities as soon as the button shows, so the menu is complete when it opens
  function prefetchQualities() {
    if (activeMode !== 'video') return;
    try {
      const tgt = computeDownloadTarget();
      if (!tgt.isMusicPlatform) listQualities(tgt.targetUrl, tgt.pageUrl);
    } catch (_) {}
  }

  function renderDropdownOptions() {
    if (!dropdownEl) return;
    dropdownEl.innerHTML = '';
    const tr = t();
    const { pageUrl, pageTitle, effectivePageUrl, isMusicPlatform, isKnownVideoSite, targetUrl } = computeDownloadTarget();

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
        });
      });
      return btn;
    };
    presets.forEach((opt) => dropdownEl.appendChild(makeOption(opt)));

    // Every quality the video really offers, read by the app (yt-dlp), listed under "best"
    if (!(activeMode === 'audio' || isMusicPlatform)) {
      const box = document.createElement('div');
      const status = document.createElement('div');
      status.style.cssText = 'font-size:11px;color:#94a3b8;padding:6px 10px;';
      status.textContent = tr.loadingQualities;
      box.appendChild(status);
      dropdownEl.insertBefore(box, dropdownEl.children[1] || null);
      listQualities(targetUrl, pageUrl).then((res) => {
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
    if (!isMusicPlatform && detectedStreams.length > 0) {
      const sep = document.createElement('div');
      sep.style.cssText =
        'border-top:1px solid #1e293b;margin:4px 0;padding-top:4px;font-size:10px;color:#94a3b8;padding-inline:8px;';
      sep.textContent = tr.directHeader;
      dropdownEl.appendChild(sep);

      detectedStreams.slice(0, 4).forEach((st, idx) => {
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
          });
        });
        dropdownEl.appendChild(btn);
      });
    }
  }

  // Qualities per address, cached so reopening the menu is instant (one request per video)
  const qualityCache = new Map();
  function listQualities(url, referer) {
    if (!qualityCache.has(url)) {
      qualityCache.set(
        url,
        new Promise((resolve) => {
          try {
            chrome.runtime.sendMessage({ action: 'SCORPION_LIST_QUALITIES', url, referer }, (res) => {
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

  function triggerVideoDownload(payload) {
    const tr = t();
    dropdownEl.classList.remove('open');
    if (labelEl) {
      labelEl.textContent = tr.sending;
    }

    const onDone = (ok) => {
      if (labelEl) {
        labelEl.textContent = ok ? tr.sentOk : tr.sentErr;
      }
      setTimeout(() => {
        if (labelEl) {
          labelEl.textContent = currentMainLabel();
        }
      }, 2200);
    };

    const directFallback = () => onDone(false);

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
  }

  function isDismissed(media) {
    if (dismissedForUrl && dismissedForUrl === window.location.href) return true;
    if (media && media.__scorpionDismissed && media.__scorpionDismissed === window.location.href) return true;
    return false;
  }

  function positionPanelOverMedia(media) {
    if (!floatingBtnEnabled || isDismissed(media)) return;
    const isAudioEl = !media || media.tagName === 'AUDIO' || activeMode === 'audio' || MUSIC_SITE_RE.test(window.location.hostname);
    const rect =
      media && media.getBoundingClientRect ? media.getBoundingClientRect() : { width: 0, height: 0, top: 0, right: 0 };

    if (!isAudioEl && (rect.width < 160 || rect.height < 100)) return;

    createFloatingPanel();
    if (labelEl) labelEl.textContent = currentMainLabel();

    const hostEl = document.fullscreenElement || document.documentElement;
    if (panelEl.parentElement !== hostEl) {
      hostEl.appendChild(panelEl);
    }

    panelEl.style.display = 'block';
    const panelW = Math.max(290, panelEl.offsetWidth || 320);

    if (panelEl.__userDraggedPos) {
      const clampedLeft = Math.max(8, Math.min(window.innerWidth - panelW - 8, panelEl.__userDraggedPos.left));
      const clampedTop = Math.max(8, Math.min(window.innerHeight - 52, panelEl.__userDraggedPos.top));
      panelEl.style.top = `${clampedTop}px`;
      panelEl.style.left = `${clampedLeft}px`;
      panelEl.style.bottom = 'auto';
      panelEl.style.right = 'auto';
      return;
    }

    if (!MUSIC_SITE_RE.test(window.location.hostname) && rect.width >= 140 && rect.height >= 24 && rect.top >= -20 && rect.top < window.innerHeight - 20) {
      const top = isAudioEl ? Math.max(10, Math.min(window.innerHeight - 180, rect.top - 42)) : Math.max(10, rect.top + 12);
      const left = Math.max(10, Math.min(window.innerWidth - panelW - 12, rect.right - panelW - 12));
      panelEl.style.top = `${top}px`;
      panelEl.style.left = `${left}px`;
      panelEl.style.bottom = 'auto';
      panelEl.style.right = 'auto';
    } else if (isAudioEl) {
      const top = 64;
      const left = Math.max(12, window.innerWidth - panelW - 24);
      panelEl.style.top = `${top}px`;
      panelEl.style.left = `${left}px`;
      panelEl.style.bottom = 'auto';
      panelEl.style.right = 'auto';
    }
  }

  function showForAudioStream() {
    if (!floatingBtnEnabled || isDismissed(null)) return;
    activeMode = 'audio';
    positionPanelOverMedia(activeMedia);
    scheduleHide(7500);
  }

  function scheduleHide(delayMs = 3800) {
    if (hideTimeout) clearTimeout(hideTimeout);
    hideTimeout = setTimeout(() => {
      if (dropdownEl && dropdownEl.classList.contains('open')) return;
      if (!isHoveringPanel && panelEl) {
        dropdownEl.classList.remove('open');
        panelEl.style.display = 'none';
      }
    }, delayMs);
  }

  function activateMediaElement(media) {
    if (!media) return;
    if (dismissedForUrl && dismissedForUrl !== window.location.href) {
      dismissedForUrl = '';
    }
    if (isDismissed(media)) return;
    const isAud = media.tagName === 'AUDIO' || MUSIC_SITE_RE.test(window.location.hostname);
    if (media.currentSrc || media.src) {
      considerUrl(media.currentSrc || media.src, isAud ? 'audio' : 'video');
    }
    activeMedia = media;
    activeMode = isAud ? 'audio' : 'video';
    positionPanelOverMedia(media);
    scheduleHide(isAud ? 7500 : 3800);
    if (media.__scorpionPrefetchedFor !== window.location.href) {
      media.__scorpionPrefetchedFor = window.location.href;
      setTimeout(prefetchQualities, 600);
    }
  }

  let lastPointerCheck = 0;
  document.addEventListener(
    'mousemove',
    (e) => {
      const now = Date.now();
      if (now - lastPointerCheck < 250) return;
      lastPointerCheck = now;
      for (const media of document.querySelectorAll('video')) {
        if (!media.__scorpionBoundV4 || isDismissed(media)) continue;
        const r = media.getBoundingClientRect();
        if (r.width > 80 && r.height > 60 && e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) {
          activateMediaElement(media);
          break;
        }
      }
    },
    { capture: true, passive: true }
  );

  function bindMediaElement(media) {
    if (media.__scorpionBoundV4) return;
    media.__scorpionBoundV4 = true;

    const showForThis = () => activateMediaElement(media);

    media.addEventListener('play', showForThis);
    media.addEventListener('playing', showForThis);
    media.addEventListener('loadeddata', showForThis);
    media.addEventListener('mouseenter', showForThis);
    media.addEventListener('mousemove', showForThis);

    if (!media.paused || (media.tagName === 'VIDEO' && media.readyState >= 2)) {
      showForThis();
    }
  }

  function scanForMedia() {
    document.querySelectorAll('video, audio').forEach(bindMediaElement);
    // On music streaming sites (Spotify, SoundCloud, Anghami, Deezer), check if mediaSession is active
    if (MUSIC_SITE_RE.test(window.location.hostname) && window.top === window.self) {
      try {
        if (
          (navigator.mediaSession && navigator.mediaSession.metadata && navigator.mediaSession.metadata.title) ||
          document.querySelector('.playing, [data-testid="control-button-playpause"][aria-label*="Pause"], .playControl.playing')
        ) {
          showForAudioStream();
        }
      } catch (_) {}
    }
  }

  document.addEventListener(
    'play',
    (e) => {
      const tEl = e.target;
      if (tEl && (tEl.tagName === 'VIDEO' || tEl.tagName === 'AUDIO')) {
        bindMediaElement(tEl);
        activateMediaElement(tEl);
      }
    },
    true
  );

  scanForMedia();
  const observer = new MutationObserver(() => scanForMedia());
  observer.observe(document.documentElement, { childList: true, subtree: true });

  window.addEventListener(
    'scroll',
    () => {
      if (panelEl && panelEl.style.display !== 'none' && !isDismissed(activeMedia)) {
        positionPanelOverMedia(activeMedia);
      }
    },
    { passive: true }
  );

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
