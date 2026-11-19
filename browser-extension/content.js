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
  let badgeEl = null;
  let langBtnEl = null;
  let closeBtnEl = null;
  let detectedStreams = [];
  let hideTimeout = null;
  let isHoveringPanel = false;
  let floatingBtnEnabled = true;
  let currentLang = /^ar(?:-|$)/i.test(navigator.language || '') ? 'ar' : 'en';
  let connectionNotice = null;
  let connectionNoticeTimer = null;
  let dismissedForUrl = '';
  let panelDragging = false;
  const activeTransfers = new Set(); // Each source keeps its own transfer while selection changes.
  let activeSource = '';
  let mediaGeneration = 0;
  let menuGeneration = 0;
  let pointerPosition = null;
  let selectionReason = 'viewport';
  let activePage = '';
  let viewportRefreshPending = false;
  let virtualAudioMedia = null;
  let virtualAudioSrc = '';

  const AUDIO_RE = /\.(mp3|m4a|aac|ogg|opus|wav|flac|wma|amr|m4b|weba|aiff)(\?|#|$)/i;
  const UI_SOUND_RE = /(^https?:\/\/static\.|\/(assets|sounds?|sfx)\/)/i;
  const TINY_UI_SOUND_RE = /(beep|notification|click|ringtone|alert|ping|pop)\.(mp3|wav|ogg)/i;
  const MUSIC_SITE_RE = /(open\.spotify\.com|soundcloud\.com|anghami\.com|deezer\.com|music\.apple\.com|music\.youtube\.com|bandcamp\.com|mixcloud\.com|audiomack\.com|mp3quran\.net)/i;
  const DRM_MUSIC_SITE_RE = /(open\.spotify\.com|music\.apple\.com|deezer\.com|anghami\.com)/i;
  const MUSIC_FALLBACK_SITE_RE = /(open\.spotify\.com|soundcloud\.com|anghami\.com|deezer\.com|music\.apple\.com)/i;
  const DRM_VIDEO_SITE_RE = /(^|\.)(netflix\.com|disneyplus\.com|primevideo\.com|shahid\.mbc\.net|watchit\.com|osnplus\.com|tv\.apple\.com|hulu\.com|max\.com|peacocktv\.com|paramountplus\.com|tod\.tv|starzplay\.com)$/i;

  function cleanVirtualUrl(u) {
    return String(u || '').replace(/#scorpion-track=.*$/, '');
  }

  function isDrmVideoSite(host = window.location.hostname, path = window.location.pathname) {
    if (DRM_VIDEO_SITE_RE.test(String(host || ''))) return true;
    return /(^|\.)amazon\.[a-z.]+$/i.test(String(host || '')) && /^\/(gp\/video|detail)\b/i.test(String(path || ''));
  }

  function isDrmProtectedMedia(media) {
    if (!media || MUSIC_SITE_RE.test(window.location.hostname)) return false;
    return isDrmVideoSite() || Boolean(media.mediaKeys) || Boolean(media.__scorpionEncrypted);
  }

  function isFloatingVirtual(media) {
    return Boolean(media && media.isVirtual);
  }

  function sourceOf(media) {
    if (!media) return '';
    if (isFloatingVirtual(media)) return media.src || '';
    const direct = media.currentSrc || media.src;
    if (direct) return direct;
    const child = typeof media.querySelector === 'function' ? media.querySelector('source[src]') : null;
    return (child && child.src) || '';
  }

  function isAudioMedia(media) {
    if (!media) return false;
    if (isFloatingVirtual(media) || media.tagName === 'AUDIO') return true;
    if (MUSIC_SITE_RE.test(window.location.hostname)) return true;
    const docType = String((document && document.contentType) || '').toLowerCase();
    if (docType.startsWith('audio/')) return true;
    const src = sourceOf(media);
    return Boolean(src && AUDIO_RE.test(src));
  }

  // Players built as web components keep their <video> inside an open shadow root, which
  // querySelectorAll on the page cannot see. Remember those roots and search them as well.
  const shadowRoots = new Set();
  const OBSERVE_OPTS = { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] };
  let mediaObserver = null;
  let shadowScanAt = 0;
  function addShadowRoot(root) {
    if (!root || shadowRoots.has(root)) return;
    shadowRoots.add(root);
    if (mediaObserver) mediaObserver.observe(root, OBSERVE_OPTS);
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) addShadowRoot(el.shadowRoot);
  }
  function discoverShadowRoots() {
    // A full walk is cheap but not free on huge feeds: at most every 2 seconds
    if (Date.now() - shadowScanAt < 2000) return;
    shadowScanAt = Date.now();
    const all = document.getElementsByTagName('*');
    for (let i = 0; i < all.length; i++) if (all[i].shadowRoot) addShadowRoot(all[i].shadowRoot);
  }
  // Media (or another selector) under root, including inside the shadow roots of hosts within it
  function queryMedia(root = document, selector = 'video, audio') {
    const found = Array.from(root.querySelectorAll(selector));
    for (const sr of shadowRoots) {
      if (!sr.host || !sr.host.isConnected) { shadowRoots.delete(sr); continue; }
      if (root === document || root === sr.host || root.contains(sr.host)) found.push(...sr.querySelectorAll(selector));
    }
    return found;
  }

  function hasVisibleRect(media) {
    if (!media || isFloatingVirtual(media) || !media.isConnected || typeof media.getBoundingClientRect !== 'function') return false;
    try {
      const style = window.getComputedStyle && window.getComputedStyle(media);
      if (style && (style.visibility === 'hidden' || style.display === 'none' || style.opacity === '0')) return false;
    } catch (_) {}
    const rect = media.getBoundingClientRect();
    const audio = isAudioMedia(media);
    if (rect.width < (audio ? 80 : 160) || rect.height < (audio ? 16 : 100)) return false;
    return Math.max(0, Math.min(window.innerWidth, rect.right) - Math.max(0, rect.left)) *
      Math.max(0, Math.min(window.innerHeight, rect.bottom) - Math.max(0, rect.top)) > 0;
  }

  function visibleArea(media) {
    if (!media || !media.isConnected) return 0;
    if (isFloatingVirtual(media)) return 1;
    if (!hasVisibleRect(media)) return 0;
    const rect = media.getBoundingClientRect();
    return Math.max(0, Math.min(window.innerWidth, rect.right) - Math.max(0, rect.left)) *
      Math.max(0, Math.min(window.innerHeight, rect.bottom) - Math.max(0, rect.top));
  }

  function isHiddenAudio(media) {
    if (!media || !isAudioMedia(media) || !media.isConnected || isFloatingVirtual(media)) return false;
    if (hasVisibleRect(media)) return false;
    const src = sourceOf(media);
    if (!src) return false;
    if (typeof media.getBoundingClientRect === 'function') {
      const rect = media.getBoundingClientRect();
      // Visible audio bars scrolled out of view stay hidden while paused.
      if (rect.width >= 80 && rect.height >= 16 && media.paused) return false;
    }
    if (!media.paused || MUSIC_SITE_RE.test(window.location.hostname)) return true;
    if (UI_SOUND_RE.test(src) || TINY_UI_SOUND_RE.test(src)) return false;
    return AUDIO_RE.test(src) || /^https?:\/\//i.test(src);
  }

  function getVirtualAudioMedia() {
    const isMusicSite = MUSIC_SITE_RE.test(window.location.hostname);
    const audioStream = detectedStreams.find(
      (s) => (s.isAudio || (isMusicSite && s.isManifest)) && !UI_SOUND_RE.test(s.url) && !TINY_UI_SOUND_RE.test(s.url)
    );
    let url = audioStream ? audioStream.url : '';
    let trackTag = '';
    if (isMusicSite) {
      const info = extractPlayingTrackInfo();
      const ms = navigator.mediaSession;
      const hasMeta = Boolean(ms && ((ms.playbackState === 'playing') || (ms.metadata && ms.metadata.title)));
      const hasTrackUrl = Boolean(info.trackUrl && info.trackUrl !== window.location.href);
      if (url || hasMeta || hasTrackUrl) {
        if (!url) url = info.trackUrl || window.location.href;
        if (info.title) trackTag = `#scorpion-track=${encodeURIComponent(info.title)}`;
      }
    }
    if (!url) return null;
    const versionedSrc = url + trackTag;
    if (!virtualAudioMedia || virtualAudioSrc !== versionedSrc) {
      virtualAudioSrc = versionedSrc;
      virtualAudioMedia = {
        isVirtual: true,
        tagName: 'AUDIO',
        src: versionedSrc,
        currentSrc: versionedSrc,
        isConnected: true,
        paused: false,
        getBoundingClientRect: () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }),
      };
    }
    return virtualAudioMedia;
  }

  function isSelectableMedia(media) {
    if (!media || !sourceOf(media) || isDrmProtectedMedia(media)) return false;
    if (!isAudioMedia(media)) {
      if (!hasVisibleRect(media)) return false;
      const rect = media.getBoundingClientRect();
      return Math.min(window.innerHeight - 8, rect.bottom) - Math.max(8, rect.top + 10) >= 38;
    }
    if (isFloatingVirtual(media)) return true;
    return hasVisibleRect(media) || isHiddenAudio(media);
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
    setDropdownOpen(false);
    isHoveringPanel = false;
  }

  function chooseVisibleMedia() {
    const allMedia = queryMedia();
    const visibleCandidates = allMedia.filter((media) => hasVisibleRect(media) && isSelectableMedia(media) && !isDismissed(media));
    const score = (media) => {
      const rect = media.getBoundingClientRect();
      const underPointer = pointerPosition && pointerPosition.x >= rect.left && pointerPosition.x <= rect.right &&
        pointerPosition.y >= rect.top && pointerPosition.y <= rect.bottom;
      const visibleCenter = (Math.max(0, rect.top) + Math.min(window.innerHeight, rect.bottom)) / 2;
      return { underPointer: Boolean(underPointer), distance: Math.abs(visibleCenter - window.innerHeight / 2) };
    };
    if (visibleCandidates.length > 0) {
      return visibleCandidates.sort((a, b) => {
        const sa = score(a), sb = score(b);
        return Number(sb.underPointer) - Number(sa.underPointer) || sa.distance - sb.distance || visibleArea(b) - visibleArea(a);
      })[0] || null;
    }
    const hiddenAudio = allMedia.filter((media) => isHiddenAudio(media) && !isDismissed(media))
      .sort((a, b) => Number(!b.paused) - Number(!a.paused))[0];
    if (hiddenAudio) return hiddenAudio;
    const vAudio = getVirtualAudioMedia();
    if (vAudio && isSelectableMedia(vAudio) && !isDismissed(vAudio)) return vAudio;
    return null;
  }

  const SCORPION_INLINE_SVG = `<svg class="scorpion-idm-emblem" viewBox="0 0 256 256" width="18" height="18" fill="none" aria-hidden="true">
    <defs>
      <linearGradient id="scorp-idm-grad-shell" x1="56" y1="186" x2="192" y2="30" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stop-color="#D46608"/><stop offset="32%" stop-color="#F89B22"/>
        <stop offset="62%" stop-color="#FFCA58"/><stop offset="86%" stop-color="#F69216"/><stop offset="100%" stop-color="#BF5003"/>
      </linearGradient>
      <linearGradient id="scorp-idm-grad-hi" x1="78" y1="170" x2="178" y2="48" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stop-color="#F69D26"/><stop offset="50%" stop-color="#FFD46E"/><stop offset="100%" stop-color="#EA800E"/>
      </linearGradient>
      <linearGradient id="scorp-idm-grad-leg" x1="90" y1="110" x2="212" y2="196" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stop-color="#FFB444"/><stop offset="62%" stop-color="#DF7710"/><stop offset="100%" stop-color="#8E3B02"/>
      </linearGradient>
      <linearGradient id="scorp-idm-grad-claw" x1="34" y1="214" x2="132" y2="124" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stop-color="#FFC254"/><stop offset="48%" stop-color="#F79318"/><stop offset="100%" stop-color="#AD4603"/>
      </linearGradient>
      <linearGradient id="scorp-idm-grad-sting" x1="138" y1="24" x2="112" y2="82" gradientUnits="userSpaceOnUse">
        <stop offset="0%" stop-color="#FFD673"/><stop offset="55%" stop-color="#F59318"/><stop offset="100%" stop-color="#7D3202"/>
      </linearGradient>
    </defs>
    <g stroke="#451B02" stroke-width="2.3" stroke-linejoin="round" stroke-linecap="round">
      <path d="M107 120 L92 103 L89 88 L96 94 L100 104 L114 115 Z" fill="url(#scorp-idm-grad-leg)"/>
      <path d="M121 110 L108 91 L106 77 L113 85 L116 95 L127 107 Z" fill="url(#scorp-idm-grad-leg)"/>
      <path d="M136 102 L125 84 L124 72 L131 80 L133 89 L141 99 Z" fill="url(#scorp-idm-grad-leg)"/>
      <path d="M140 146 L158 158 L165 180 L159 199 L152 191 L156 177 L149 162 L133 150 Z" fill="url(#scorp-idm-grad-leg)"/>
      <path d="M151 136 L174 148 L185 169 L184 190 L176 181 L176 167 L166 153 L145 142 Z" fill="url(#scorp-idm-grad-leg)"/>
      <path d="M161 126 L188 134 L203 153 L207 173 L198 166 L194 152 L180 139 L157 132 Z" fill="url(#scorp-idm-grad-leg)"/>
      <path d="M168 113 L195 117 L214 131 L222 149 L212 144 L204 132 L188 124 L166 120 Z" fill="url(#scorp-idm-grad-leg)"/>
      <path d="M100 128 C88 121 76 120 67 124 L59 133 C45 143 35 160 35 178 C35 186 38 193 42 197 C42 184 44 171 50 162 C50 172 52 184 57 195 C60 183 61 168 64 157 C68 147 76 141 85 140 C93 139 98 136 103 132 Z" fill="url(#scorp-idm-grad-claw)"/>
      <path d="M47 146 C55 137 64 131 74 132 C64 137 56 144 50 155 C45 164 42 175 41 184 C39 170 40 156 47 146 Z" fill="url(#scorp-idm-grad-hi)" stroke="none"/>
      <path d="M123 153 L131 164 C136 173 134 184 127 192 C117 204 97 215 76 220 C64 222 53 221 46 218 C61 214 78 207 88 197 C76 203 60 205 47 203 C62 196 78 188 90 178 C100 169 109 167 116 168 C120 163 119 156 116 151 Z" fill="url(#scorp-idm-grad-claw)"/>
      <path d="M121 168 C124 178 118 189 107 197 C96 205 83 210 70 213 C85 206 96 196 102 186 C109 176 116 169 121 168 Z" fill="url(#scorp-idm-grad-hi)" stroke="none"/>
      <path d="M84 150 C79 142 84 130 96 123 C106 117 118 120 126 128 C134 136 135 148 127 156 C118 164 102 164 91 156 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M86 152 L75 161 L82 162 L90 156 Z" fill="#F8A832"/>
      <path d="M93 158 L84 168 L91 168 L98 160 Z" fill="#E88412"/>
      <path d="M111 119 C121 110 135 112 145 121 C152 129 150 141 140 148 C132 154 122 151 115 143 C109 135 104 126 111 119 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M127 108 C136 99 151 101 159 110 C166 118 163 129 154 136 C146 142 136 139 130 131 C124 123 121 114 127 108 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M142 97 C151 89 164 92 171 100 C177 108 174 118 165 125 C158 130 149 127 144 120 C139 112 136 103 142 97 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M155 87 C163 80 174 83 180 91 C185 98 182 108 174 114 C167 119 159 116 155 109 C151 102 149 93 155 87 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M96 134 C104 128 113 131 120 137 C114 143 103 144 96 138 Z" fill="url(#scorp-idm-grad-hi)" stroke="none"/>
      <path d="M121 120 C129 117 139 120 143 127 C134 132 124 130 121 120 Z" fill="url(#scorp-idm-grad-hi)" stroke="none"/>
      <path d="M137 108 C144 105 154 108 157 115 C149 119 140 117 137 108 Z" fill="url(#scorp-idm-grad-hi)" stroke="none"/>
      <path d="M150 98 C157 95 165 97 168 103 C161 107 153 105 150 98 Z" fill="url(#scorp-idm-grad-hi)" stroke="none"/>
      <path d="M166 80 C175 72 185 73 189 81 C193 89 188 99 178 103 C171 105 164 100 163 92 C162 87 163 83 166 80 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M173 64 C182 58 192 61 195 70 C197 78 190 87 180 88 C172 89 166 83 167 74 C168 69 170 66 173 64 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M175 47 C183 42 194 47 196 56 C197 65 188 72 178 71 C170 70 166 63 168 55 C169 51 172 49 175 47 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M167 31 C176 26 187 31 191 41 C193 49 185 55 175 53 C167 51 162 44 162 37 C163 34 165 32 167 31 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M148 21 C159 18 171 22 177 31 C180 38 174 44 164 43 C155 42 148 36 145 29 C143 25 144 22 148 21 Z" fill="url(#scorp-idm-grad-shell)"/>
      <path d="M151 26 C160 24 168 28 171 34 C163 36 153 33 151 26 Z" fill="#FFD978" stroke="none"/>
      <path d="M171 36 C179 34 185 39 185 45 C177 45 171 41 171 36 Z" fill="#FFD36B" stroke="none"/>
      <path d="M148 22 C137 20 126 27 125 38 C124 47 129 53 132 59 C134 63 133 70 127 78 C136 74 142 66 142 57 C143 51 148 45 151 37 C153 30 152 24 148 22 Z" fill="url(#scorp-idm-grad-sting)"/>
      <path d="M141 26 C135 26 130 31 130 38 C130 43 134 46 138 45 C143 43 146 34 141 26 Z" fill="#FFD772" stroke="none"/>
    </g>
  </svg>`;

  const I18N = {
    ar: {
      dir: 'rtl',
      mainText: 'تحميل بواسطة Scorpion',
      mainAudioText: 'تحميل الصوت بواسطة Scorpion',
      bestHd: 'أفضل جودة (MP4)',
      audioMp3: 'الصوت فقط MP3',
      loadingQualities: 'جاري قراءة الجودات المتاحة...',
      noQualities: 'تعذر قراءة الجودات — استخدم أفضل جودة',
      qualityItem: (label) => (/mp4/i.test(String(label || '')) ? String(label) : `${label} MP4`),
      bestAudioOrig: 'أعلى جودة صوتية (MP3)',
      convertMp3: 'تحويل وتحميل بصيغة MP3',
      directHeader: 'الروابط المباشرة المكتشفة من المشغل:',
      directItem: (i, isAud) => (isAud ? `ملف صوتي مباشر #${i}` : `رابط مباشر #${i}`),
      langToggle: 'EN',
      langTitle: 'Switch to English',
      closeTitle: 'إغلاق الشريط',
      quickTitle: 'اضغط للتحميل بأفضل جودة — أو اختر الجودة من القائمة',
      menuTitle: 'اختيار الجودة',
    },
    en: {
      dir: 'ltr',
      mainText: 'Download with Scorpion',
      mainAudioText: 'Download Audio with Scorpion',
      bestHd: 'Best Quality MP4',
      audioMp3: 'Audio Only MP3',
      loadingQualities: 'Reading available qualities...',
      noQualities: "Couldn't read the qualities — use Best quality",
      qualityItem: (label) => (/mp4/i.test(String(label || '')) ? String(label) : `${label} MP4`),
      bestAudioOrig: 'Best Audio Quality',
      convertMp3: 'Audio Only MP3',
      directHeader: 'Direct streams detected from player:',
      directItem: (i, isAud) => (isAud ? `Direct Audio #${i}` : `Direct Stream #${i}`),
      langToggle: 'ع',
      langTitle: 'التحويل إلى العربية',
      closeTitle: 'Close bar',
      quickTitle: 'Click to download in the best quality — or pick a quality',
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
    if (badgeEl) {
      badgeEl.title = tr.menuTitle;
      badgeEl.setAttribute('aria-label', tr.menuTitle);
    }
    if (closeBtnEl) {
      closeBtnEl.title = tr.closeTitle;
    }
    if (panelEl) {
      const trig = panelEl.querySelector('.scorpion-idm-trigger');
      if (trig) trig.title = tr.quickTitle;
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
  } catch (_) {}

  // ---------------------------------------------------------------------------
  // Stream sniffer for real Video AND Audio streams (ignoring DRM license / API endpoints)
  // ---------------------------------------------------------------------------
  const MANIFEST_RE = /\.(m3u8|mpd)(\?|#|$)/i;
  const VIDEO_RE = /\.(mp4|webm|m4v|mkv|flv|mov)(\?|#|$)/i;
  // Video streams whose address has no file extension (e.g. LinkedIn: dms.licdn.com/playlist/vid/.../mp4-720p-30fp/...)
  const VIDEO_HINT_RE = /\/playlist\/vid\/|[\/_-]mp4[-_\/]/i;
  const IGNORE_STREAM_RE =
    /(widevine|playready|drm|license|spclient\.spotify\.com|telemetry|analytics|beacon|track_event|oauth|api-v2\.soundcloud\.com\/(me|announcements|promoted))/i;
  const streamMap = new Map();
  let streamPage = location.href;
  let lastNetworkScan = 0;

  function detectAudioExt(url) {
    const m = String(url || '').match(/\.(mp3|m4a|aac|ogg|opus|wav|flac|wma|amr|m4b|weba|aiff)(\?|#|$)/i);
    return m ? m[1].toUpperCase() : 'MP3';
  }

  let perfIndex = 0;

  function resetRouteStreams() {
    streamMap.clear();
    detectedStreams = [];
    streamPage = location.href;
    qualityCache.clear();
    try {
      perfIndex = performance.getEntriesByType('resource').length;
    } catch (_) {
      perfIndex = 0;
    }
  }

  function considerUrl(url, initiator) {
    if (streamPage !== location.href) {
      resetRouteStreams();
    }
    if (!url || !/^https?:\/\//i.test(url)) return;
    if (streamMap.has(url)) {
      const existing = streamMap.get(url);
      existing.t = Date.now();
      detectedStreams = Array.from(streamMap.values()).sort((a, b) => b.score - a.score || b.t - a.t);
      return;
    }
    if (url.startsWith('http://127.0.0.1:19615')) return;
    if (IGNORE_STREAM_RE.test(url)) return;
    if (ScorpionMedia.isFragment(url) || ScorpionMedia.isBrowserLocal(url)) return;

    const isManifest = MANIFEST_RE.test(url) || initiator === 'manifest';
    const isAudio = !isManifest && (AUDIO_RE.test(url) || initiator === 'audio' || initiator === 'network-audio');
    const isVideo =
      !isManifest && !isAudio && (VIDEO_RE.test(url) || VIDEO_HINT_RE.test(url) || initiator === 'video' || initiator === 'network-video');
    if (!isManifest && !isAudio && !isVideo) return;

    // Ignore tiny UI notification sounds
    if (isAudio && TINY_UI_SOUND_RE.test(url)) return;
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

    if (
      ((isAudio && (initiator === 'network-audio' || initiator === 'audio' || initiator === 'fetch' || initiator === 'xmlhttprequest')) ||
        (isManifest && MUSIC_SITE_RE.test(window.location.hostname))) &&
      (!activeMedia || isFloatingVirtual(activeMedia))
    ) {
      scheduleViewportRefresh();
    }
    // A network video request alone never makes an overlay: it may belong to another player.
  }

  function scanPerformance() {
    if (streamPage !== location.href) {
      resetRouteStreams();
    }
    try {
      const entries = performance.getEntriesByType('resource');
      if (perfIndex > entries.length) perfIndex = 0;
      entries.slice(perfIndex).forEach((e) => considerUrl(e.name, e.initiatorType));
      perfIndex = entries.length;
    } catch (_) {}
    queryMedia(document, 'video, video source').forEach((el) => {
      considerUrl(el.currentSrc || el.src, 'video');
    });
    queryMedia(document, 'audio, audio source').forEach((el) => {
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
        if (queryMedia(el).length > 1) break;
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
      const scNavFirst = new Set(['you', 'discover', 'stream', 'search', 'pages', 'settings', 'messages', 'notifications', 'charts', 'tags']);
      const scNavSecond = new Set(['sets', 'tracks', 'albums', 'likes', 'reposts', 'followers', 'following', 'comments', 'recommended']);
      const validScTrack = (href) => {
        if (!href) return '';
        try {
          const u = new URL(href, 'https://soundcloud.com');
          if (!/soundcloud\.com$/i.test(u.hostname)) return '';
          const segs = u.pathname.split('/').filter(Boolean);
          if (segs.length >= 2 && !scNavFirst.has(segs[0].toLowerCase()) && !scNavSecond.has(segs[1].toLowerCase())) {
            return `${u.origin}${u.pathname}`;
          }
        } catch (_) {}
        return '';
      };
      const scLinks = document.querySelectorAll(
        'a.playbackSoundBadge__titleLink, [class*="playbackSoundBadge"] a[href], .playControls a[href]'
      );
      for (const link of scLinks) {
        const resolved = validScTrack(link.getAttribute('href'));
        if (resolved) {
          trackUrl = resolved;
          if (!title) {
            title = (link.getAttribute('title') || link.textContent || '').trim();
          }
          break;
        }
      }
      if (!trackUrl) {
        trackUrl = validScTrack(window.location.pathname);
      }
      if (!title) {
        const scHero = document.querySelector('h1.soundTitle__title');
        if (scHero) title = (scHero.textContent || '').trim();
      }
      const artistLink = document.querySelector('a.playbackSoundBadge__lightLink, .soundTitle__usernameHero');
      if (artistLink && !artist) {
        artist = (artistLink.getAttribute('title') || artistLink.textContent || '').trim();
      }
    }

    // 2b. MP3Quran player bar (#soraName + #reciterName verified on live site)
    if (host.includes('mp3quran.net')) {
      const soraEl = document.querySelector('div.audio-player #soraName, .apdp-sora');
      const reciterEl = document.querySelector('div.audio-player #reciterName, .apdp-reciter');
      if (!title && soraEl) title = (soraEl.textContent || '').trim();
      if (!artist && reciterEl) artist = (reciterEl.textContent || '').trim();
    }

    // 3. Spotify bottom Now Playing bar
    if (host.includes('spotify.com')) {
      const spTitle = document.querySelector(
        '[data-testid="context-item-link"], [data-testid="now-playing-widget"] a[href*="/track/"], footer a[href*="/track/"]'
      );
      const spArtists = document.querySelectorAll('[data-testid="context-item-info-subtitles"] a, [data-testid="context-item-info-artist"]');
      if (spTitle) {
        if (!title) title = (spTitle.textContent || '').trim();
        const href = spTitle.getAttribute('href');
        if (href && /\/(track|episode)\//i.test(href)) {
          try {
            const u = new URL(href, 'https://open.spotify.com');
            trackUrl = `${u.origin}${u.pathname}`;
          } catch (_) {}
        }
      }
      if (!trackUrl && /^\/(track|episode)\//i.test(window.location.pathname)) {
        trackUrl = `${window.location.origin}${window.location.pathname}`;
      }
      if (!artist && spArtists.length > 0) {
        artist = Array.from(spArtists)
          .map((el) => (el.textContent || '').trim())
          .filter(Boolean)
          .join(', ');
      }
    }

    // 4. YouTube Music player bar
    if (host === 'music.youtube.com') {
      const ytLink = document.querySelector('ytmusic-player-bar a[href*="watch?v="]');
      if (ytLink) {
        try { trackUrl = new URL(ytLink.getAttribute('href'), 'https://music.youtube.com').href; } catch (_) {}
      }
      const ytTitle = document.querySelector('ytmusic-player-bar .title');
      const ytArtist = document.querySelector('ytmusic-player-bar .byline');
      if (!title && ytTitle) title = (ytTitle.textContent || '').trim();
      if (!artist && ytArtist) artist = (ytArtist.textContent || '').split('•')[0].trim();
    }

    // 5. Anghami / Deezer player links
    if (host.includes('anghami.com') || host.includes('deezer.com')) {
      const mLink = document.querySelector('a[href*="/song/"], a[href*="/track/"]');
      if (mLink) {
        try { trackUrl = new URL(mLink.getAttribute('href'), window.location.origin).href; } catch (_) {}
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

  function setDropdownOpen(open) {
    if (!dropdownEl) return;
    if (open && panelEl) {
      const pRect = panelEl.getBoundingClientRect();
      if (window.innerHeight - pRect.bottom < 220) {
        dropdownEl.classList.add('drop-up');
      } else {
        dropdownEl.classList.remove('drop-up');
      }
    }
    dropdownEl.classList.toggle('open', Boolean(open));
    if (badgeEl) {
      badgeEl.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
  }

  try {
    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (msg && msg.action === 'SCORPION_GET_TITLE') {
        if (window.top !== window.self) return false;
        const info = extractPlayingTrackInfo();
        sendResponse({ title: info.title });
        return false;
      }
      if (msg && msg.action === 'SCORPION_URL_CHANGED') {
        resetRouteStreams();
        qualityCache.clear();
        dismissedForUrl = '';
        scheduleViewportRefresh();
        return false;
      }
      if (msg && msg.action === 'SCORPION_DOWNLOAD_CURRENT_MEDIA') {
        if (isDrmVideoSite()) {
          try {
            chrome.runtime.sendMessage({ action: 'SCORPION_REPORT_ERROR', code: 'drmProtected' }, () => void chrome.runtime.lastError);
            if (chrome.storage && chrome.storage.session && chrome.storage.session.set) {
              chrome.storage.session.set({ scorpionDownloadError: { code: 'drmProtected', at: Date.now() } }).catch(() => {});
            }
          } catch (_) {}
          sendResponse({ ok: false, error: 'drmProtected' });
          return false;
        }
        const rawTarget = msg.src
          ? queryMedia(document, 'video, audio').find((el) => sourceOf(el) === msg.src)
          : (activeMedia || chooseVisibleMedia());
        if (rawTarget && isDrmProtectedMedia(rawTarget)) {
          try {
            chrome.runtime.sendMessage({ action: 'SCORPION_REPORT_ERROR', code: 'drmProtected' }, () => void chrome.runtime.lastError);
            if (chrome.storage && chrome.storage.session && chrome.storage.session.set) {
              chrome.storage.session.set({ scorpionDownloadError: { code: 'drmProtected', at: Date.now() } }).catch(() => {});
            }
          } catch (_) {}
          sendResponse({ ok: false, error: 'drmProtected' });
          return false;
        }
        if (!isSelectableMedia(rawTarget)) {
          if (queryMedia(document, 'video').some((el) => isDrmProtectedMedia(el))) {
            try {
              chrome.runtime.sendMessage({ action: 'SCORPION_REPORT_ERROR', code: 'drmProtected' }, () => void chrome.runtime.lastError);
              if (chrome.storage && chrome.storage.session && chrome.storage.session.set) {
                chrome.storage.session.set({ scorpionDownloadError: { code: 'drmProtected', at: Date.now() } }).catch(() => {});
              }
            } catch (_) {}
            sendResponse({ ok: false, error: 'drmProtected' });
            return false;
          }
          sendResponse({ ok: false });
          return false;
        }
        const media = rawTarget;
        dismissedForUrl = '';
        media.__scorpionDismissed = '';
        activateMediaElement(media, 'explicit');
        const target = computeDownloadTarget();
        const targetIsAudio = isAudioMedia(media) || AUDIO_RE.test(target.targetUrl);
        const isMusicFallback = target.isMusicPlatform && MUSIC_FALLBACK_SITE_RE.test(target.effectivePageUrl);
        const ok = triggerVideoDownload({
          url: target.targetUrl,
          pageUrl: target.effectivePageUrl,
          referer: location.href,
          candidates: target.candidates,
          strictTarget: !isMusicFallback,
          title: target.pageTitle,
          quality: targetIsAudio ? (AUDIO_RE.test(target.targetUrl) && !target.isMusicPlatform ? 'direct' : 'audio') : 'best',
          type: targetIsAudio ? 'audio' : 'video',
        }, mediaSession());
        sendResponse({ ok });
        return false;
      }
    });
  } catch (_) {}

  function createFloatingPanel() {
    if (panelEl) return panelEl;

    const tr = t();
    panelEl = document.createElement('div');
    panelEl.className = 'scorpion-idm-video-panel';
    panelEl.setAttribute('dir', tr.dir);
    panelEl.style.display = 'none';

    const mainBtn = document.createElement('div');
    mainBtn.className = 'scorpion-idm-main-btn';

    const triggerEl = document.createElement('button');
    triggerEl.type = 'button';
    triggerEl.className = 'scorpion-idm-trigger';
    triggerEl.innerHTML = `
      ${SCORPION_INLINE_SVG}
      <span class="scorpion-btn-text"></span>
    `;
    labelEl = triggerEl.querySelector('.scorpion-btn-text');
    labelEl.textContent = currentMainLabel();
    triggerEl.title = tr.quickTitle;

    badgeEl = document.createElement('button');
    badgeEl.type = 'button';
    badgeEl.className = 'scorpion-idm-badge';
    badgeEl.innerHTML = '&#9662;';
    badgeEl.title = tr.menuTitle;
    badgeEl.setAttribute('aria-label', tr.menuTitle);
    badgeEl.setAttribute('aria-haspopup', 'menu');
    badgeEl.setAttribute('aria-expanded', 'false');

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
      setDropdownOpen(false);
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
    mainBtn.appendChild(badgeEl);
    mainBtn.appendChild(langBtnEl);
    mainBtn.appendChild(closeBtnEl);

    dropdownEl = document.createElement('div');
    dropdownEl.className = 'scorpion-idm-dropdown';
    dropdownEl.setAttribute('role', 'menu');

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
      // Quick download: the first option is "best quality" (or best audio in audio mode)
      const first = dropdownEl.querySelector('.scorpion-idm-option');
      if (first) {
        first.click();
        return;
      }
      setDropdownOpen(!dropdownEl.classList.contains('open'));
    });

    badgeEl.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      const willOpen = !dropdownEl.classList.contains('open');
      if (willOpen) renderDropdownOptions();
      setDropdownOpen(willOpen);
    });

    panelEl.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (dropdownEl && dropdownEl.classList.contains('open')) {
          e.stopPropagation();
          e.preventDefault();
          setDropdownOpen(false);
          if (badgeEl) badgeEl.focus();
        }
        return;
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        if (!dropdownEl) return;
        const isOpen = dropdownEl.classList.contains('open');
        if (!isOpen && e.target === badgeEl && e.key === 'ArrowDown') {
          e.stopPropagation();
          e.preventDefault();
          renderDropdownOptions();
          setDropdownOpen(true);
          const firstItem = dropdownEl.querySelector('.scorpion-idm-option');
          if (firstItem) firstItem.focus();
          return;
        }
        if (isOpen) {
          const items = Array.from(dropdownEl.querySelectorAll('.scorpion-idm-option'));
          if (!items.length) return;
          e.stopPropagation();
          e.preventDefault();
          const curIdx = items.indexOf(document.activeElement);
          const nextIdx = e.key === 'ArrowDown'
            ? (curIdx < 0 ? 0 : (curIdx + 1) % items.length)
            : (curIdx <= 0 ? items.length - 1 : curIdx - 1);
          items[nextIdx].focus();
        }
      }
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

    const rawMediaSrc = sourceOf(activeMedia);
    const mediaSrc = cleanVirtualUrl(rawMediaSrc);
    if ((activeMedia && /^blob:/i.test(mediaSrc)) || isFloatingVirtual(activeMedia)) {
      scanPerformance();
    }
    const virtualHasRawMedia =
      !isFloatingVirtual(activeMedia) ||
      AUDIO_RE.test(mediaSrc) ||
      MANIFEST_RE.test(mediaSrc) ||
      detectedStreams.some((s) => s.url === mediaSrc && (s.isAudio || s.isManifest));
    const directMediaSrc =
      virtualHasRawMedia &&
      mediaSrc &&
      /^https?:\/\//i.test(mediaSrc) &&
      !ScorpionMedia.isFragment(mediaSrc) &&
      !IGNORE_STREAM_RE.test(mediaSrc)
        ? mediaSrc
        : null;

    // Requests are frame-wide, so only the actual element's source (or audio stream when in audio mode) is scoped.
    const childSources = activeMedia && !isFloatingVirtual(activeMedia) && typeof activeMedia.querySelectorAll === 'function'
      ? Array.from(activeMedia.querySelectorAll('source')).map((s) => s.src) : [];
    const sources = new Set([mediaSrc, ...childSources]);
    const multipleMedia = isFloatingVirtual(activeMedia) ? false : queryMedia().length > 1;
    const nowTs = Date.now();
    const scopedStreams = detectedStreams.filter(
      (stream) =>
        nowTs - stream.t < 180000 &&
        (sources.has(stream.url) || (activeMode === 'audio' && stream.isAudio && !multipleMedia))
    );
    // A lone player fed through MSE (blob:) has no address of its own. When it is the only media element
    // in this document (typically an embedded player's iframe), the manifests this frame loaded are its
    // stream. Read them from the full map: the player fetched its manifest when playback began, which
    // may be long before the button is pressed.
    if (activeMedia && /^blob:/i.test(mediaSrc) && !multipleMedia) {
      Array.from(streamMap.values()).filter((s) => s.isManifest && !scopedStreams.includes(s))
        .sort((a, b) => b.score - a.score || b.t - a.t).forEach((s) => scopedStreams.push(s));
    }
    const sniffed = scopedStreams.find((stream) => stream.isManifest) || scopedStreams[0];
    const permalinks = isFloatingVirtual(activeMedia) ? [] : findPermalinksNearMedia(activeMedia);
    // A track address from a music site wins; otherwise the post around the video beats the feed's address
    const trackUrl = isAudioMedia(activeMedia) && trackInfo.trackUrl ? trackInfo.trackUrl : '';
    const effectivePageUrl = isFloatingVirtual(activeMedia)
      ? resolveEmbeddedVideoPage(trackUrl || pageUrl)
      : resolvePostUrlForMedia(activeMedia, resolveEmbeddedVideoPage(trackUrl || permalinks[0] || pageUrl));
    const platformUrl = isFramed && !directMediaSrc ? (document.referrer || effectivePageUrl) : effectivePageUrl;
    const isMusicPlatform = MUSIC_SITE_RE.test(platformUrl);
    const isKnownVideoSite =
      /(?:^|\/\/|\.)(youtube\.com|youtu\.be|facebook\.com|instagram\.com|tiktok\.com|twitter\.com|x\.com|vimeo\.com|dailymotion\.com|linkedin\.com\/(?:feed\/update|posts)\/)/i.test(
        platformUrl
      );

    let targetUrl = effectivePageUrl;
    const scopedPost = isFloatingVirtual(activeMedia) || permalinks.length > 0 ||
      resolvePostUrlForMedia(activeMedia, pageUrl) !== pageUrl ||
      !multipleMedia && (effectivePageUrl !== pageUrl || PERMALINK_RE.test(location.pathname + location.search));
    const ambiguous = multipleMedia && !scopedPost && !directMediaSrc && !ScorpionMedia.isTelegram(pageUrl);
    const allowDirectOnMusicSite =
      isMusicPlatform &&
      directMediaSrc &&
      AUDIO_RE.test(directMediaSrc) &&
      !MUSIC_FALLBACK_SITE_RE.test(effectivePageUrl) &&
      !/music\.youtube\.com/i.test(effectivePageUrl);
    if ((!isKnownVideoSite && (!isMusicPlatform || allowDirectOnMusicSite)) || multipleMedia && directMediaSrc) {
      if (directMediaSrc) targetUrl = directMediaSrc;
      else if (sniffed && (sniffed.isManifest || (activeMode === 'audio' && sniffed.isAudio))) targetUrl = sniffed.url;
      // A page extractor is safer than an unrelated short MP4 loaded by an ad or background animation.
    }
    const isGenericMusicUrl = (u) => {
      if (!u || !isMusicPlatform) return false;
      try {
        const parsed = new URL(u);
        const pathClean = parsed.pathname.replace(/\/+$/, '');
        if (!pathClean) return true;
        if (/soundcloud\.com$/i.test(parsed.hostname)) {
          const segs = pathClean.split('/').filter(Boolean);
          if (segs.length < 2) return true;
          if (['you', 'discover', 'stream', 'search', 'charts', 'tags'].includes(segs[0].toLowerCase())) return true;
        }
        if (/spotify\.com$/i.test(parsed.hostname) && !/^\/(track|episode)\//i.test(pathClean)) return true;
      } catch (_) {}
      return false;
    };
    const rawCandidates = [];
    const addCandidate = (u) => {
      if (u && /^https?:\/\//i.test(u) && !rawCandidates.includes(u)) rawCandidates.push(u);
    };
    [targetUrl, ...permalinks, directMediaSrc, ...(!multipleMedia ? [effectivePageUrl] : [])].forEach(addCandidate);
    scopedStreams.forEach((stream) => addCandidate(stream.url));
    const candidates = rawCandidates.some((c) => !isGenericMusicUrl(c))
      ? rawCandidates.filter((c) => !isGenericMusicUrl(c))
      : rawCandidates;
    return { pageUrl, pageTitle, effectivePageUrl, isMusicPlatform, isKnownVideoSite, targetUrl, candidates, scopedStreams, ambiguous };
  }

  // Read the qualities as soon as the button shows, so the menu is complete when it opens
  function prefetchQualities() {
    if (activeMode !== 'video') return;
    if (ScorpionMedia.isTelegram(location.href)) return;
    try {
      const tgt = computeDownloadTarget();
      if (!tgt.isMusicPlatform && !tgt.ambiguous) listQualities(tgt.targetUrl, tgt.pageUrl, tgt.candidates, false);
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

    const isDrmMusicSite = isMusicPlatform && DRM_MUSIC_SITE_RE.test(effectivePageUrl);
    const isMusicFallbackSite = isMusicPlatform && MUSIC_FALLBACK_SITE_RE.test(effectivePageUrl);
    const isDirectAudioStream = Boolean(scopedStreams.some((s) => s.url === targetUrl && s.isAudio));
    const isDirectAudioFile =
      activeMode === 'audio' &&
      !isMusicFallbackSite &&
      !/music\.youtube\.com/i.test(effectivePageUrl) &&
      !isKnownVideoSite &&
      (AUDIO_RE.test(targetUrl) || isDirectAudioStream);

    let presets = [];
    if (activeMode === 'audio' || isMusicPlatform) {
      const extLower = isDirectAudioFile ? detectAudioExt(targetUrl).toLowerCase() : 'mp3';
      presets = [
        {
          label: tr.bestAudioOrig,
          tag: isDirectAudioFile ? detectAudioExt(targetUrl) : 'BEST',
          quality: isDirectAudioFile ? 'direct' : 'audio',
          type: 'audio',
          url: targetUrl,
          filename: `${pageTitle}.${extLower}`,
          selected: true,
        },
        {
          label: tr.convertMp3,
          tag: 'MP3',
          quality: 'audio',
          type: 'audio',
          url: isDirectAudioFile ? targetUrl : effectivePageUrl,
          filename: `${pageTitle}.mp3`,
        },
      ];
    } else {
      presets = [
        {
          label: tr.bestHd,
          tag: 'BEST',
          quality: 'best',
          type: 'video',
          url: targetUrl,
          selected: true,
        },
        {
          label: tr.audioMp3,
          tag: 'M4A',
          quality: 'audio',
          type: 'audio',
          url: targetUrl,
        },
      ];
    }

    const optionButtons = [];
    const setSelectedButton = (chosen) => {
      for (const b of optionButtons) {
        const active = b === chosen;
        b.classList.toggle('is-selected', active);
        const chk = b.querySelector('.scorpion-idm-opt-check');
        if (chk) chk.textContent = active ? '✓' : '';
      }
    };

    const makeOption = (opt) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.setAttribute('role', 'menuitem');
      btn.className = 'scorpion-idm-option' + (opt.selected ? ' is-selected' : '');
      btn.innerHTML = `
        <span class="scorpion-idm-opt-main">
          <span class="scorpion-idm-opt-check" aria-hidden="true">${opt.selected ? '&#10003;' : ''}</span>
          <span class="scorpion-idm-opt-label"></span>
        </span>
        <span class="scorpion-idm-option-tag"></span>
      `;
      btn.querySelector('.scorpion-idm-opt-label').textContent = opt.label;
      btn.querySelector('.scorpion-idm-option-tag').textContent = opt.tag || '';
      optionButtons.push(btn);
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        setSelectedButton(btn);
        triggerVideoDownload({
          url: opt.url,
          pageUrl: effectivePageUrl,
          referer: pageUrl,
          title: pageTitle,
          quality: opt.quality,
          type: opt.type || 'video',
          filename: opt.filename || '',
          candidates,
          strictTarget: !isMusicFallbackSite,
        }, session);
      });
      return btn;
    };
    const presetButtons = presets.map((opt) => {
      const b = makeOption(opt);
      dropdownEl.appendChild(b);
      return b;
    });

    // Every quality the video really offers, read by the app (yt-dlp), listed under "best"
    if (!(activeMode === 'audio' || isMusicPlatform || ScorpionMedia.isTelegram(pageUrl))) {
      const box = document.createElement('div');
      const status = document.createElement('div');
      status.style.cssText = 'font-size:11px;color:#989aa6;padding:6px 10px;';
      status.textContent = tr.loadingQualities;
      box.appendChild(status);
      dropdownEl.insertBefore(box, dropdownEl.children[1] || null);
      listQualities(targetUrl, pageUrl, candidates, true).then((res) => {
        if (!sessionIsCurrent(session) || renderedMenu !== menuGeneration || !box.isConnected) return;
        const list = (res && res.qualities) || [];
        if (!list.length) {
          status.textContent = tr.noQualities;
          return;
        }
        status.remove();
        let firstQualityBtn = null;
        list.forEach((q, idx) => {
          const size = q.size ? `~${q.size >= 1073741824 ? (q.size / 1073741824).toFixed(1) + ' GB' : Math.round(q.size / 1048576) + ' MB'}` : '';
          const qBtn = makeOption({
            label: t().qualityItem(q.label),
            tag: size || q.quality,
            quality: q.quality,
            type: 'video',
            url: targetUrl,
            selected: idx === 0,
          });
          if (idx === 0) firstQualityBtn = qBtn;
          box.appendChild(qBtn);
        });
        if (firstQualityBtn && presetButtons.length) {
          setSelectedButton(firstQualityBtn);
        }
      });
    }

    // Only list raw network streams when not on a DRM music site (where raw URLs require DRM keys)
    if (!isMusicPlatform && scopedStreams.length > 0) {
      const sep = document.createElement('div');
      sep.style.cssText =
        'border-top:1px solid rgba(255,255,255,0.08);margin:4px 0;padding-top:4px;font-size:10px;color:#989aa6;padding-inline:8px;';
      sep.textContent = tr.directHeader;
      dropdownEl.appendChild(sep);

      scopedStreams.slice(0, 4).forEach((st, idx) => {
        const tag = st.extTag || (st.isManifest ? 'HLS / M3U8' : st.isAudio ? 'MP3' : 'MP4');
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.setAttribute('role', 'menuitem');
        btn.className = 'scorpion-idm-option';
        btn.innerHTML = `
          <span class="scorpion-idm-opt-main">
            <span class="scorpion-idm-opt-check" aria-hidden="true"></span>
            <span class="scorpion-idm-opt-label"></span>
          </span>
          <span class="scorpion-idm-option-tag">${tag}</span>
        `;
        btn.querySelector('.scorpion-idm-opt-label').textContent = tr.directItem(idx + 1, st.isAudio);
        optionButtons.push(btn);
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

  // Anonymous prefetches share a short cache; authenticated lookups always consult the desktop
  // engine so same-tab session switches pick up updated cookie-scoped qualities immediately.
  const qualityCache = new Map();
  function listQualities(url, referer, candidates, allowCookies = false) {
    const baseKey = `${url}|${(candidates || []).join(',')}`;
    const sendLookup = (onDone) => {
      try {
        chrome.runtime.sendMessage(
          { action: 'SCORPION_LIST_QUALITIES', url, referer, candidates: candidates || [], strictTarget: true, allowCookies },
          (res) => {
            const valid = Boolean(!chrome.runtime.lastError && res && res.ok && Array.isArray(res.qualities) && res.qualities.length > 0);
            onDone(valid, chrome.runtime.lastError ? null : res);
          }
        );
      } catch (_) {
        onDone(false, null);
      }
    };
    if (allowCookies) {
      // An earlier in-flight request may already carry another account's cookies.
      // Each new menu must resolve its own current session, even on the same URL.
      return new Promise((resolve) => sendLookup((_valid, res) => resolve(res)));
    }
    const modeKey = `anon|${baseKey}`;
    if (!qualityCache.has(modeKey)) {
      if (qualityCache.size >= 32) {
        qualityCache.delete(qualityCache.keys().next().value);
      }
      qualityCache.set(
        modeKey,
        new Promise((resolve) => {
          queueMicrotask(() => sendLookup((valid, res) => {
            if (!valid) qualityCache.delete(modeKey);
            resolve(res);
          }));
        })
      );
    }
    return qualityCache.get(modeKey);
  }

  function triggerVideoDownload(payload, session = mediaSession()) {
    if (!sessionIsCurrent(session)) return false;
    if (computeDownloadTarget().ambiguous) return false;
    payload.expectedDuration = session.duration;
    setDropdownOpen(false);

    // Keep transfer progress off the video button and retain only fixed error codes.
    const reportError = (code) => {
      try {
        chrome.runtime.sendMessage({ action: 'SCORPION_REPORT_ERROR', code }, () => void chrome.runtime.lastError);
        if (chrome.storage && chrome.storage.session && chrome.storage.session.set) {
          chrome.storage.session.set({ scorpionDownloadError: { code, at: Date.now() } }).catch(() => {});
        }
      } catch (_) {}
    };

    const showConnectionHelp = () => {
      reportError('connection');
      if (!panelEl || !sessionIsCurrent(session)) return;
      if (!connectionNotice) {
        connectionNotice = document.createElement('div');
        connectionNotice.className = 'scorpion-idm-connection-notice';
        connectionNotice.setAttribute('role', 'status');
        panelEl.appendChild(connectionNotice);
      }
      connectionNotice.textContent = currentLang === 'ar'
        ? 'البرنامج غير متصل. افتح أيقونة الإضافة للتحميل أو المساعدة في الربط.'
        : 'Desktop app disconnected. Open the extension for the installer or connection help.';
      connectionNotice.hidden = false;
      clearTimeout(connectionNoticeTimer);
      connectionNoticeTimer = setTimeout(() => { connectionNotice.hidden = true; }, 6500);
    };
    const reportDownloadFailure = (code) => {
      chrome.runtime.sendMessage({ action: 'SCORPION_CHECK_STATUS' }, (status) => {
        if (chrome.runtime.lastError || status?.alive === false) showConnectionHelp();
        else reportError(code);
      });
    };

    if (ScorpionMedia.isTelegram(location.href)) {
      // Use only THIS player's source, never another document found in the page's request history.
      const isAudio = payload.type === 'audio' || activeMode === 'audio';
      const src = session.source;
      if (!src || !ScorpionMedia.isBrowserLocal(src) || /^blob:/i.test(src)) {
        reportError('telegramSource');
        return false;
      }
      if (payload.quality === 'audio' && activeMode !== 'audio') {
        reportError('telegramAudio');
        return false;
      }
      if (activeTransfers.has(src)) return true; // Already accepted; do not create a duplicate.
      const request = (operation, data) => new Promise((resolve, reject) => {
        if (operation === 'heartbeat') window.postMessage({
          action: 'SCORPION_KEEP_MEDIA_READER', readerId, url: src,
        }, location.origin);
        chrome.runtime.sendMessage({ action: 'SCORPION_BROWSER_TRANSFER', operation, payload: data }, (res) => {
          if (chrome.runtime.lastError || !res) reject(new Error('الاتصال بالبرنامج انقطع. أعد المحاولة.'));
          else resolve(res);
        });
      });
      activeTransfers.add(src);
      const readerId = crypto.randomUUID();
      const startTransfer = () => ScorpionTransfer.transfer(src, {
        filename: payload.filename || `${payload.title || (isAudio ? 'Telegram_Audio' : 'Telegram_Video')}.${isAudio ? 'ogg' : 'mp4'}`,
        pageUrl: location.href, expectedDuration: payload.expectedDuration, isAudio,
      }, request, fetch, () => {}, (url, offset, total, _fetcher, chunkSize) => readTelegramPageRange(url, offset, total, readerId, chunkSize))
      .catch(() => reportDownloadFailure('transfer'))
        .finally(() => {
          activeTransfers.delete(src);
          window.postMessage({ action: 'SCORPION_RELEASE_MEDIA_READER', readerId, url: src }, location.origin);
        });
      try {
        chrome.runtime.sendMessage({ action: 'SCORPION_CHECK_STATUS' }, (status) => {
          if (chrome.runtime.lastError || status?.alive === false) {
            activeTransfers.delete(src);
            showConnectionHelp();
          } else startTransfer();
        });
      } catch (_) {
        activeTransfers.delete(src);
        showConnectionHelp();
      }
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
            if (res?.error === 'drmProtected') reportError('drmProtected');
            else if (res?.error === 'connection' || chrome.runtime.lastError) showConnectionHelp();
            else reportError('captureFailed');
          }
        }
      );
    } catch (_) {
      showConnectionHelp();
    }
    return true;
  }

  function readTelegramPageRange(url, offset, total, readerId, chunkSize) {
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
      window.postMessage({ action: 'SCORPION_READ_MEDIA_RANGE', requestId, readerId, url, offset, total, chunkSize }, location.origin);
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
    const audio = isAudioMedia(media);
    const hasBox = hasVisibleRect(media);
    const rect = hasBox && typeof media.getBoundingClientRect === 'function' ? media.getBoundingClientRect() : null;
    const visibleTop = rect ? Math.max(8, rect.top + 10) : 8;
    const visibleBottom = rect ? Math.min(window.innerHeight - 8, rect.bottom) : window.innerHeight - 8;
    if (!audio && (!rect || visibleBottom - visibleTop < 38)) { hidePanel(); return; }

    createFloatingPanel();
    if (labelEl && labelEl.textContent !== currentMainLabel()) labelEl.textContent = currentMainLabel();

    const fsEl = document.fullscreenElement;
    const hostEl =
      fsEl && fsEl.tagName !== 'VIDEO' && fsEl.tagName !== 'AUDIO' && fsEl.tagName !== 'IFRAME' && !fsEl.shadowRoot
        ? fsEl
        : document.documentElement;
    if (panelEl.parentElement !== hostEl) {
      hostEl.appendChild(panelEl);
    }

    if (panelEl.style.display === 'none') {
      panelEl.style.visibility = 'hidden';
      panelEl.style.display = 'block';
    }
    const panelW = Math.max(290, panelEl.offsetWidth || 320);
    panelEl.style.visibility = '';

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
    let topPx;
    let leftPx;
    if (!hasBox) {
      topPx = Math.max(8, window.innerHeight - 54);
      leftPx = Math.max(8, window.innerWidth - panelW - 20);
    } else if (audio) {
      // Place above (or below) compact audio bars so native play/seek controls remain uncovered.
      topPx = rect.top >= 50
        ? Math.max(8, rect.top - 44)
        : Math.min(window.innerHeight - 46, rect.bottom + 6);
      leftPx = Math.max(8, Math.min(window.innerWidth - panelW - 8, rect.right - panelW));
    } else {
      topPx = Math.min(visibleTop, visibleBottom - 38);
      leftPx = Math.max(8, Math.min(window.innerWidth - panelW - 8, rect.right - panelW - 10));
    }
    panelEl.style.top = `${topPx}px`;
    panelEl.style.left = `${leftPx}px`;
    panelEl.style.bottom = 'auto';
    panelEl.style.right = 'auto';
    panelEl.style.display = 'block';
  }

  function activateMediaElement(media, reason = 'scan') {
    if (!isSelectableMedia(media)) return false;
    // Playback in another feed item is not a selection. Hover, scroll, or an explicit command is.
    if (['play', 'scan'].includes(reason) && media !== activeMedia && isSelectableMedia(activeMedia) && !isFloatingVirtual(activeMedia)) return false;
    if (dismissedForUrl && dismissedForUrl !== window.location.href) {
      dismissedForUrl = '';
    }
    if (isDismissed(media)) return false;
    const changed = media !== activeMedia || sourceOf(media) !== activeSource || activePage !== location.href;
    if (changed) {
      if (connectionNotice) connectionNotice.hidden = true;
      mediaGeneration++;
      menuGeneration++;
      if (dropdownEl) { setDropdownOpen(false); dropdownEl.innerHTML = ''; }
      if (panelEl) delete panelEl.__userDraggedPos;
      panelDragging = false;
      isHoveringPanel = false;
    }
    if (panelDragging && !changed) return false;
    const isAud = isAudioMedia(media);
    const mediaSrc = sourceOf(media);
    if (mediaSrc && !isFloatingVirtual(media)) {
      considerUrl(mediaSrc, isAud ? 'audio' : 'video');
    }
    activeMedia = media;
    activeSource = mediaSrc;
    activePage = location.href;
    selectionReason = reason;
    activeMode = isAud ? 'audio' : 'video';
    positionPanelOverMedia(media);
    if (reason === 'hover' || reason === 'play' || reason === 'explicit' || reason === 'viewport') {
      try {
        chrome.runtime.sendMessage({ action: 'SCORPION_MARK_ACTIVE_FRAME', reason }, () => void chrome.runtime.lastError);
      } catch (_) {}
    }
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
    media.addEventListener('encrypted', () => {
      media.__scorpionEncrypted = true;
      refreshMediaSelection();
    });
  }

  function scanForMedia() {
    if (!window.document) return;
    discoverShadowRoots();
    queryMedia().forEach(bindMediaElement);
    refreshMediaSelection();
  }

  function refreshMediaSelection(reason = 'scan') {
    if (!window.document) return;
    if (reason === 'viewport' && !panelDragging) {
      if (isHoveringPanel && isSelectableMedia(activeMedia)) return;
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
    if (next) activateMediaElement(next, reason === 'viewport' ? 'viewport' : 'scan');
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
      (change.type === 'attributes' && change.target.matches && change.target.matches('video, audio, source') ||
      [...change.addedNodes, ...change.removedNodes].some((node) => node.nodeType === 1 &&
        (node.matches('video, audio, source') || node.shadowRoot || node.querySelector('video, audio, source')))));
    if (!relevant || mediaScanPending) return;
    mediaScanPending = true;
    requestAnimationFrame(() => { mediaScanPending = false; scanForMedia(); });
  });
  observer.observe(document.documentElement, OBSERVE_OPTS);
  mediaObserver = observer;
  for (const root of shadowRoots) observer.observe(root, OBSERVE_OPTS);

  try {
    const titleEl = document.querySelector('title');
    if (titleEl) {
      new MutationObserver(() => {
        if (MUSIC_SITE_RE.test(window.location.hostname)) scheduleViewportRefresh();
      }).observe(titleEl, { childList: true, characterData: true, subtree: true });
    }
  } catch (_) {}

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
  const onSpaRouteChange = () => {
    resetRouteStreams();
    scheduleViewportRefresh();
  };
  window.addEventListener('hashchange', onSpaRouteChange);
  window.addEventListener('popstate', onSpaRouteChange);
  try {
    if (window.navigation && typeof window.navigation.addEventListener === 'function') {
      window.navigation.addEventListener('navigatesuccess', onSpaRouteChange);
    }
  } catch (_) {}
  document.addEventListener('fullscreenchange', scheduleViewportRefresh);
  document.addEventListener('pointermove', (event) => {
    if (!panelEl || !panelEl.contains(event.target)) pointerPosition = { x: event.clientX, y: event.clientY };
  }, { passive: true });
  document.addEventListener('pointerover', (event) => {
    if (panelEl && panelEl.contains(event.target)) return;
    pointerPosition = { x: event.clientX, y: event.clientY };
    // The event path crosses into shadow trees: register a player's shadow root as soon as the pointer is on it
    const path = event.composedPath ? event.composedPath() : [];
    const before = shadowRoots.size;
    for (const node of path) if (node instanceof ShadowRoot) addShadowRoot(node);
    if (shadowRoots.size !== before) scanForMedia();
    // Poster images and player controls often cover the <video>. Resolve only their nearest
    // single-player container and verify the pointer is inside that player's actual rectangle.
    let target = event.target;
    for (let depth = 0; target && target !== document.body && target.nodeType === 1 && depth < 10; depth++, target = target.parentElement) {
      const players = target.matches('video, audio') ? [target] : queryMedia(target);
      if (players.length > 1) break;
      if (!players.length) continue;
      const rawRect = players[0].getBoundingClientRect();
      const rect = rawRect.width > 0 && rawRect.height > 0 ? rawRect :
        (isHiddenAudio(players[0]) ? target.getBoundingClientRect() : rawRect);
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
