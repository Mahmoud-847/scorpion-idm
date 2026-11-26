document.addEventListener('DOMContentLoaded', () => {
  const statusBadge = document.getElementById('statusBadge');
  const statusMonitorIcon = document.getElementById('statusMonitorIcon');
  const langToggleBtn = document.getElementById('langToggleBtn');
  const lblIntercept = document.getElementById('lblIntercept');
  const lblVideoBtn = document.getElementById('lblVideoBtn');
  const interceptToggle = document.getElementById('interceptToggle');
  const videoBtnToggle = document.getElementById('videoBtnToggle');
  const statsRow = document.getElementById('statsRow');
  const lblDownloadsCount = document.getElementById('lblDownloadsCount');
  const lblActiveCount = document.getElementById('lblActiveCount');
  const grabCurrentPageBtn = document.getElementById('grabCurrentPageBtn');
  const lblGrabBtn = document.getElementById('lblGrabBtn');
  const errorCard = document.getElementById('downloadErrorCard');
  const errorMessage = document.getElementById('downloadErrorMessage');
  const dismissErrorBtn = document.getElementById('dismissErrorBtn');
  const privacyLink = document.getElementById('privacyLink');
  const installCard = document.getElementById('installCard');
  const storeOpenCard = document.getElementById('storeOpenCard');
  const storePairForm = document.getElementById('storePairForm');
  const storePairCode = document.getElementById('storePairCode');
  const storePairSubmit = document.getElementById('storePairSubmit');
  const storePairError = document.getElementById('storePairError');
  const reviewCard = document.getElementById('reviewCard');
  const reviewInviteLink = document.getElementById('reviewInviteLink');
  const dismissReviewBtn = document.getElementById('dismissReviewBtn');

  let currentLang = /^ar(?:-|$)/i.test(navigator.language || '') ? 'ar' : 'en';
  let isAlive = null;
  let lastStats = null;
  let lastError = null;
  let statusPending = false;
  let storeApp = false;
  let pairingRequired = false;
  let pairingPending = false;
  let pairingError = '';
  let configEdited = false;
  let reviewSeen = null;
  let reviewOpen = false;

  const I18N = {
    ar: {
      dir: 'rtl',
      online: 'متصل ببرنامج سطح المكتب',
      offline: 'برنامج سطح المكتب غير متصل',
      checking: 'جاري التحقق من الاتصال…',
      installDescription: 'لو البرنامج مثبّت، شغّله لربط الإضافة. لو دي أول مرة، حمّل برنامج ويندوز.',
      installer: 'تحميل برنامج Scorpion IDM للويندوز',
      setupHelp: 'مساعدة في الربط',
      openStore: 'افتح سكوربيون',
      pairStatus: 'نسخة المتجر تحتاج الربط',
      pairHint: 'افتح «ربط المتصفحات» في سكوربيون وولّد رمزًا، ثم أدخله هنا.',
      pairButton: 'ربط الإضافة',
      pairInvalid: 'الرمز غير صحيح أو انتهت صلاحيته. ولّد رمزًا جديدًا وحاول تاني.',
      pairConnection: 'تعذر الربط. تأكد إن نسخة المتجر شغّالة وحاول تاني.',
      reviewDescription: 'اكتملت ثلاث تحميلات عبر الإضافة. رأيك يساعدنا نحسّنها.',
      reviewInvite: 'شارك رأيك في الإضافة',
      reviewLink: 'تقييم الإضافة',
      intercept: 'الالتقاط التلقائي للتحميلات',
      videoBtn: 'إظهار الزر العائم',
      grabBtn: 'تحميل فيديو الصفحة الحالية',
      downloadsLabel: (n) => `التحميلات: ${n}`,
      activeLabel: (n) => `النشطة: ${n}`,
      noVideo: 'قف على الفيديو المطلوب أو مرّر الصفحة إليه، ثم استخدم الزر فوقه.',
      privacy: 'سياسة الخصوصية',
      dismissError: 'إخفاء الرسالة',
      errors: {
        connection: 'تعذر إرسال التنزيل. تأكد من تشغيل البرنامج، ثم حاول مرة أخرى.',
        captureFailed: 'تعذر إرسال هذا التنزيل. راجع البرنامج ثم حاول مرة أخرى.',
        drmProtected: 'هذا الفيديو محمي بتشفير DRM (مثل Netflix) ولا يدعم التنزيل الخارجي. استخدم ميزة التنزيل داخل تطبيق المنصة الرسمي.',
        noVideo: 'قف على الفيديو المطلوب أو مرّر الصفحة إليه، ثم استخدم الزر فوقه.',
        unclearSource: 'تعذّر تحديد مصدر الفيديو. افتح صفحة الفيديو نفسه وأعد المحاولة.',
        telegramSource: 'افتح الفيديو المطلوب داخل تليجرام ثم أعد المحاولة. إذا لم يتوفر مصدر قابل للقراءة، استخدم تنزيل تليجرام الأصلي.',
        telegramAudio: 'نزّل فيديو تليجرام كاملًا أولًا؛ تنزيل الصوت وحده غير متاح لهذا المسار.',
        transfer: 'تعذر إكمال تنزيل تليجرام. راجع سبب الفشل في البرنامج، ثم أعد المحاولة من الفيديو.',
      },
    },
    en: {
      dir: 'ltr',
      online: 'Desktop App Connected',
      offline: 'Desktop App Disconnected',
      checking: 'Checking connection…',
      installDescription: 'Open the desktop app to connect. If you are new to Scorpion, download the Windows app.',
      installer: 'Download Scorpion IDM (Windows)',
      setupHelp: 'Connection help',
      openStore: 'Open Scorpion',
      pairStatus: 'Store app needs pairing',
      pairHint: 'Open Browser Integration in Scorpion, generate a code, and enter it here.',
      pairButton: 'Pair extension',
      pairInvalid: 'That code is invalid or expired. Generate a new code and try again.',
      pairConnection: 'Could not pair. Make sure the Store app is running and try again.',
      reviewDescription: 'You’ve completed three downloads through the extension. Your feedback helps us improve it.',
      reviewInvite: 'Share your feedback',
      reviewLink: 'Rate extension',
      intercept: 'Automatic Interception',
      videoBtn: 'Show Floating Button',
      grabBtn: 'Download Page Video',
      downloadsLabel: (n) => `Downloads: ${n}`,
      activeLabel: (n) => `Active: ${n}`,
      noVideo: 'Point to the video or scroll to it, then use the button above it.',
      privacy: 'Privacy policy',
      dismissError: 'Dismiss message',
      errors: {
        connection: 'Could not send the download. Open the desktop application and try again.',
        captureFailed: 'Could not send this download. Check the desktop app and try again.',
        drmProtected: 'This video is DRM-protected (e.g. Netflix) and cannot be downloaded externally. Use the platform’s official offline download feature.',
        noVideo: 'Point to the video or scroll to it, then use the button above it.',
        unclearSource: 'Could not identify the video source. Open the video’s own page and try again.',
        telegramSource: 'Open the selected video in Telegram and retry. If no readable source is available, use Telegram’s own download button.',
        telegramAudio: 'Download the complete Telegram video first; audio-only download is unavailable for this source.',
        transfer: 'The Telegram download could not finish. Check the reason in the desktop application, then retry from the video.',
      },
    },
  };

  function applyLang() {
    const tr = I18N[currentLang] || I18N.ar;
    document.documentElement.setAttribute('lang', currentLang);
    document.documentElement.setAttribute('dir', tr.dir);
    const state = isAlive === null ? '' : isAlive ? ' online' : ' offline';
    const statusText = pairingRequired ? tr.pairStatus : isAlive === null ? tr.checking : isAlive ? tr.online : tr.offline;
    if (statusBadge.textContent !== statusText) statusBadge.textContent = statusText;
    statusBadge.className = `status${state}`;
    if (statusMonitorIcon) {
      statusMonitorIcon.setAttribute('class', `status-ico${state}`);
    }
    installCard.hidden = isAlive !== false || storeApp;
    storeOpenCard.hidden = isAlive !== false || !storeApp || pairingRequired;
    storePairForm.hidden = isAlive !== false || !pairingRequired;
    storePairSubmit.disabled = pairingPending;
    storePairError.hidden = !pairingError;
    storePairError.textContent = pairingError ? tr[pairingError] : '';
    document.getElementById('openStoreApp').textContent = tr.openStore;
    document.getElementById('storePairHint').textContent = tr.pairHint;
    storePairSubmit.textContent = tr.pairButton;
    grabCurrentPageBtn.disabled = isAlive !== true;
    grabCurrentPageBtn.hidden = isAlive !== true;
    document.getElementById('installDescription').textContent = tr.installDescription;
    document.getElementById('installerLink').textContent = tr.installer;
    document.getElementById('setupHelpLink').textContent = tr.setupHelp;
    document.getElementById('reviewDescription').textContent = tr.reviewDescription;
    document.getElementById('reviewLink').textContent = tr.reviewLink;
    reviewInviteLink.textContent = tr.reviewInvite;
    dismissReviewBtn.textContent = tr.dismissError;
    reviewCard.hidden = !reviewOpen || !isAlive;
    lblIntercept.textContent = tr.intercept;
    lblVideoBtn.textContent = tr.videoBtn;
    if (lblGrabBtn) {
      lblGrabBtn.textContent = tr.grabBtn;
    } else {
      grabCurrentPageBtn.textContent = tr.grabBtn;
    }
    langToggleBtn.setAttribute('aria-checked', currentLang === 'ar' ? 'true' : 'false');
    langToggleBtn.setAttribute('title', currentLang === 'ar' ? 'Switch to English' : 'التحويل إلى العربية');
    privacyLink.textContent = tr.privacy;
    dismissErrorBtn.textContent = tr.dismissError;

    const hasValidStats =
      isAlive &&
      lastStats &&
      Number.isInteger(lastStats.totalCount) &&
      Number.isInteger(lastStats.activeCount);
    if (statsRow) {
      statsRow.hidden = !hasValidStats;
      if (hasValidStats) {
        lblDownloadsCount.textContent = tr.downloadsLabel(lastStats.totalCount);
        lblActiveCount.textContent = tr.activeLabel(lastStats.activeCount);
      }
    }

    const message = lastError && (lastError.code !== 'connection' || isAlive === false) && tr.errors[lastError.code];
    errorCard.hidden = !message;
    errorMessage.textContent = message || '';
  }

  function setStoredError(error) {
    const age = Date.now() - error?.at;
    lastError = age >= 0 && age < 3600000 ? error : null;
    applyLang();
  }
  chrome.storage.session.get(['scorpionDownloadError']).then((data) => {
    setStoredError(data.scorpionDownloadError);
  }).catch(() => {});
  chrome.storage.onChanged?.addListener((changes, area) => {
    if (area === 'session' && changes.scorpionDownloadError) {
      setStoredError(changes.scorpionDownloadError.newValue);
      if (lastError?.code === 'connection') refreshStatus();
    }
  });

  dismissErrorBtn.addEventListener('click', () => {
    lastError = null;
    chrome.storage.session.remove('scorpionDownloadError').catch(() => {});
    applyLang();
  });

  function maybeShowReview() {
    if (reviewSeen !== false || !isAlive || !(lastStats?.extensionCompletedCount >= 3)) return;
    reviewSeen = true;
    reviewOpen = true;
    chrome.storage.local.set({ scorpionReviewPromptSeen: true });
  }

  chrome.storage.local.get?.(['scorpionReviewPromptSeen'], (data) => {
    reviewSeen = Boolean(data?.scorpionReviewPromptSeen);
    maybeShowReview();
    applyLang();
  });
  function closeReview() { reviewOpen = false; applyLang(); }
  dismissReviewBtn.addEventListener('click', closeReview);
  reviewInviteLink.addEventListener('click', closeReview);

  function refreshStatus() {
    if (statusPending) return;
    statusPending = true;
    chrome.runtime.sendMessage({ action: 'SCORPION_CHECK_STATUS' }, (res) => {
      const failed = Boolean(chrome.runtime.lastError);
      statusPending = false;
      isAlive = !failed && res?.alive === true;
      storeApp = !failed && res?.storeApp === true;
      pairingRequired = !failed && res?.pairingRequired === true;
      if (isAlive) pairingError = '';
      lastStats = isAlive && res.stats && typeof res.stats === 'object' ? res.stats : null;
      if (!configEdited && res?.config) {
        interceptToggle.checked = Boolean(res.config.interceptAllDownloads);
        videoBtnToggle.checked = Boolean(res.config.showVideoFloatingBtn);
        if (res.config.lang === 'en' || res.config.lang === 'ar') currentLang = res.config.lang;
      }
      if (isAlive && lastError?.code === 'connection') {
        lastError = null;
        chrome.storage.session.remove('scorpionDownloadError').catch(() => {});
      }
      maybeShowReview();
      applyLang();
    });
  }
  storePairForm.addEventListener('submit', (event) => {
    event.preventDefault();
    if (pairingPending) return;
    pairingPending = true;
    pairingError = '';
    applyLang();
    chrome.runtime.sendMessage({ action: 'SCORPION_PAIR_STORE', code: storePairCode.value }, (response) => {
      const failed = Boolean(chrome.runtime.lastError);
      pairingPending = false;
      if (!failed && response?.ok) {
        storePairCode.value = '';
        refreshStatus();
      } else {
        pairingError = response?.error === 'invalid' ? 'pairInvalid' : 'pairConnection';
      }
      applyLang();
    });
  });
  applyLang();
  refreshStatus();
  window.setInterval(refreshStatus, 2500);

  function saveConfig(syncRemoteLang = false) {
    configEdited = true;
    chrome.storage.local.set({
      scorpionConfig: {
        interceptAllDownloads: interceptToggle.checked,
        showVideoFloatingBtn: videoBtnToggle.checked,
        minFileSizeKb: 100,
        lang: currentLang,
      },
    });
    if (syncRemoteLang) {
      try {
        chrome.runtime.sendMessage({ action: 'SCORPION_SET_APP_LANG', lang: currentLang }, () => void chrome.runtime.lastError);
      } catch (_) {}
    }
  }

  interceptToggle.addEventListener('change', () => saveConfig(false));
  videoBtnToggle.addEventListener('change', () => saveConfig(false));

  langToggleBtn.addEventListener('click', () => {
    currentLang = currentLang === 'ar' ? 'en' : 'ar';
    applyLang();
    saveConfig(true);
  });

  grabCurrentPageBtn.addEventListener('click', () => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      const tab = tabs && tabs[0];
      if (!tab || !tab.url) return;
      const handleGrabReply = (res) => {
        if (!res || !res.ok) {
          const code = Object.hasOwn(I18N[currentLang].errors, res?.error) ? res.error : 'noVideo';
          if (code === 'connection') refreshStatus();
          lastError = { code, at: Date.now() };
          chrome.storage.session.set({ scorpionDownloadError: lastError }).catch(() => {});
          applyLang();
          return;
        }
        window.close();
      };
      chrome.runtime.sendMessage({ action: 'SCORPION_GRAB_TAB_MEDIA', tabId: tab.id, tabUrl: tab.url }, (bgRes) => {
        if (!chrome.runtime.lastError && bgRes && bgRes.handled) {
          handleGrabReply(bgRes);
          return;
        }
        chrome.tabs.sendMessage(tab.id, { action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA' }, (res) => {
          handleGrabReply(chrome.runtime.lastError ? null : res);
        });
      });
    });
  });
});
