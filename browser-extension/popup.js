document.addEventListener('DOMContentLoaded', () => {
  const statusBadge = document.getElementById('statusBadge');
  const langToggleBtn = document.getElementById('langToggleBtn');
  const lblIntercept = document.getElementById('lblIntercept');
  const lblVideoBtn = document.getElementById('lblVideoBtn');
  const interceptToggle = document.getElementById('interceptToggle');
  const videoBtnToggle = document.getElementById('videoBtnToggle');
  const grabCurrentPageBtn = document.getElementById('grabCurrentPageBtn');
  const errorCard = document.getElementById('downloadErrorCard');
  const errorMessage = document.getElementById('downloadErrorMessage');
  const dismissErrorBtn = document.getElementById('dismissErrorBtn');
  const privacyLink = document.getElementById('privacyLink');

  let currentLang = 'ar';
  let isAlive = false;
  let lastError = null;

  const I18N = {
    ar: {
      dir: 'rtl',
      online: 'متصل بالبرنامج 🟢',
      offline: 'افتح برنامج Scorpion 🔴',
      intercept: 'المسؤول الرئيسي لكل التحميلات:',
      videoBtn: 'إظهار زر التحميل فوق الفيديوهات:',
      grabBtn: '🎬 تحميل الفيديو المحدد الآن',
      noVideo: 'قف على الفيديو المطلوب أو مرّر الصفحة إليه، ثم استخدم الزر فوقه.',
      toggleBtn: 'EN',
      privacy: 'سياسة الخصوصية',
      dismissError: 'إخفاء الرسالة',
      errors: {
        connection: 'تعذر إرسال التنزيل. تأكد من تشغيل البرنامج، ثم حاول مرة أخرى.',
        telegramSource: 'افتح الفيديو المطلوب داخل تليجرام ثم أعد المحاولة. إذا لم يتوفر مصدر قابل للقراءة، استخدم تنزيل تليجرام الأصلي.',
        telegramAudio: 'نزّل فيديو تليجرام كاملًا أولًا؛ تنزيل الصوت وحده غير متاح لهذا المسار.',
        transfer: 'تعذر إكمال تنزيل تليجرام. راجع سبب الفشل في البرنامج، ثم أعد المحاولة من الفيديو.',
      },
    },
    en: {
      dir: 'ltr',
      online: 'Connected 🟢',
      offline: 'Open Scorpion App 🔴',
      intercept: 'Intercept all browser downloads:',
      videoBtn: 'Show floating download bar on videos:',
      grabBtn: '🎬 Download the selected video',
      noVideo: 'Point to the video or scroll to it, then use the button above it.',
      toggleBtn: 'عربي',
      privacy: 'Privacy policy',
      dismissError: 'Dismiss message',
      errors: {
        connection: 'Could not send the download. Open the desktop application and try again.',
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
    lblIntercept.textContent = tr.intercept;
    lblVideoBtn.textContent = tr.videoBtn;
    grabCurrentPageBtn.textContent = tr.grabBtn;
    langToggleBtn.textContent = tr.toggleBtn;
    privacyLink.textContent = tr.privacy;
    dismissErrorBtn.textContent = tr.dismissError;
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
      fetch(`http://127.0.0.1:19615/ping?set_lang=${encodeURIComponent(currentLang)}`, {
        headers: { 'X-Scorpion-Client': '1' },
      }).catch(() => {});
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
      chrome.tabs.sendMessage(tab.id, { action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA' }, (res) => {
        if (chrome.runtime.lastError || !res || !res.ok) {
          statusBadge.textContent = (I18N[currentLang] || I18N.ar).noVideo;
          statusBadge.className = 'status';
          return;
        }
        window.close();
      });
    });
  });
});
