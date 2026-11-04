document.addEventListener('DOMContentLoaded', () => {
  const statusBadge = document.getElementById('statusBadge');
  const langToggleBtn = document.getElementById('langToggleBtn');
  const lblIntercept = document.getElementById('lblIntercept');
  const lblVideoBtn = document.getElementById('lblVideoBtn');
  const interceptToggle = document.getElementById('interceptToggle');
  const videoBtnToggle = document.getElementById('videoBtnToggle');
  const grabCurrentPageBtn = document.getElementById('grabCurrentPageBtn');

  let currentLang = 'ar';
  let isAlive = false;

  const I18N = {
    ar: {
      dir: 'rtl',
      online: 'متصل بالبرنامج 🟢',
      offline: 'افتح برنامج Scorpion 🔴',
      intercept: 'المسؤول الرئيسي لكل التحميلات:',
      videoBtn: 'إظهار زر التحميل فوق الفيديوهات:',
      grabBtn: '🎬 سحب فيديو الصفحة الحالية الآن',
      toggleBtn: 'EN',
    },
    en: {
      dir: 'ltr',
      online: 'Connected 🟢',
      offline: 'Open Scorpion App 🔴',
      intercept: 'Intercept all browser downloads:',
      videoBtn: 'Show floating download bar on videos:',
      grabBtn: '🎬 Grab Current Page Video Now',
      toggleBtn: 'عربي',
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
  }

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
      if (new URL(tab.url).hostname === 'web.telegram.org') {
        chrome.tabs.sendMessage(tab.id, { action: 'SCORPION_DOWNLOAD_CURRENT_MEDIA' }, () => {
          if (chrome.runtime.lastError) return;
          window.close();
        });
        return;
      }
      chrome.runtime.sendMessage(
        {
          action: 'SCORPION_DOWNLOAD_VIDEO',
          payload: {
            url: tab.url,
            pageUrl: tab.url,
            title: tab.title || 'Video_Download',
            quality: 'best',
            type: 'video',
          },
        },
        () => window.close()
      );
    });
  });
});
