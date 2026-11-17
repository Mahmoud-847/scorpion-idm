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

  let currentLang = 'ar';
  let isAlive = false;
  let lastStats = null;
  let lastError = null;

  const I18N = {
    ar: {
      dir: 'rtl',
      online: 'متصل ببرنامج سطح المكتب',
      offline: 'برنامج سطح المكتب غير متصل',
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
        drmProtected: 'هذا الفيديو محمي بتشفير DRM (مثل Netflix) ولا يدعم التنزيل الخارجي. استخدم ميزة التنزيل داخل تطبيق المنصة الرسمي.',
        noVideo: 'قف على الفيديو المطلوب أو مرّر الصفحة إليه، ثم استخدم الزر فوقه.',
        telegramSource: 'افتح الفيديو المطلوب داخل تليجرام ثم أعد المحاولة. إذا لم يتوفر مصدر قابل للقراءة، استخدم تنزيل تليجرام الأصلي.',
        telegramAudio: 'نزّل فيديو تليجرام كاملًا أولًا؛ تنزيل الصوت وحده غير متاح لهذا المسار.',
        transfer: 'تعذر إكمال تنزيل تليجرام. راجع سبب الفشل في البرنامج، ثم أعد المحاولة من الفيديو.',
      },
    },
    en: {
      dir: 'ltr',
      online: 'Desktop App Connected',
      offline: 'Desktop App Disconnected',
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
        drmProtected: 'This video is DRM-protected (e.g. Netflix) and cannot be downloaded externally. Use the platform’s official offline download feature.',
        noVideo: 'Point to the video or scroll to it, then use the button above it.',
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
    statusBadge.textContent = isAlive ? tr.online : tr.offline;
    statusBadge.className = isAlive ? 'status online' : 'status offline';
    if (statusMonitorIcon) {
      statusMonitorIcon.setAttribute('class', isAlive ? 'status-ico online' : 'status-ico offline');
    }
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

    const message = lastError && tr.errors[lastError.code];
    errorCard.hidden = !message;
    errorMessage.textContent = message || '';
  }

  chrome.storage.session.get(['scorpionDownloadError']).then((data) => {
    const error = data.scorpionDownloadError;
    if (error && Number.isFinite(error.at) && Date.now() - error.at >= 0 && Date.now() - error.at < 3600000) lastError = error;
    applyLang();
  }).catch(() => {});

  dismissErrorBtn.addEventListener('click', () => {
    lastError = null;
    chrome.storage.session.remove('scorpionDownloadError').catch(() => {});
    applyLang();
  });

  chrome.runtime.sendMessage({ action: 'SCORPION_CHECK_STATUS' }, (res) => {
    isAlive = Boolean(res && res.alive);
    lastStats = isAlive && res && res.stats && typeof res.stats === 'object' ? res.stats : null;
    if (res && res.config) {
      interceptToggle.checked = Boolean(res.config.interceptAllDownloads);
      videoBtnToggle.checked = Boolean(res.config.showVideoFloatingBtn);
      if (res.config.lang === 'en' || res.config.lang === 'ar') {
        currentLang = res.config.lang;
      }
    }
    applyLang();
  });

  function saveConfig(syncRemoteLang = false) {
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
          const code = res && res.error === 'drmProtected' ? 'drmProtected' : 'noVideo';
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
