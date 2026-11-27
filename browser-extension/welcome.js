const messages = {
  en: {
    heading: 'Connect your extension', stepDownload: 'Download the Windows app',
    downloadHint: 'Get the app from Microsoft Store or download the installer, then open Scorpion Download Manager.', downloadStore: 'Get it from Microsoft Store', downloadInstaller: 'Download the installer (.exe)',
    stepConnect: 'Confirm the connection',
    connectionHint: 'This page checks for the desktop app while it is open. If the app is running and still cannot connect, open Connect Browser in the app.',
    tryDownload: 'Try your first download', checking: 'Checking connection…',
    offline: 'Waiting for the desktop app', online: 'Desktop app connected',
    accepted: 'Check the desktop app for the Scorpion Quick Start file.', failed: 'Could not start the test. Check the connection and try again.',
  },
  ar: {
    heading: 'اربط إضافة المتصفح', stepDownload: 'حمّل برنامج ويندوز',
    downloadHint: 'حمّل البرنامج من Microsoft Store أو حمّل ملف التسطيب، وبعد التثبيت افتح البرنامج.', downloadStore: 'تحميل من Microsoft Store', downloadInstaller: 'تحميل ملف التسطيب (exe)',
    stepConnect: 'تأكد من الاتصال',
    connectionHint: 'الصفحة بتتحقق من حالة الاتصال وهي مفتوحة. لو البرنامج شغّال ولسه مفيش اتصال، افتح «ربط المتصفح» من البرنامج.',
    tryDownload: 'جرّب أول تحميل', checking: 'جاري التحقق من الاتصال…',
    offline: 'في انتظار تشغيل البرنامج', online: 'متصل ببرنامج سطح المكتب',
    accepted: 'راجع برنامج سطح المكتب لمتابعة تحميل ملف دليل البدء.', failed: 'تعذر بدء الاختبار. تأكد من الاتصال وحاول مرة أخرى.',
  },
};

const statusEl = document.getElementById('connectionStatus');
const sampleBtn = document.getElementById('tryDownload');
const sampleStatus = document.getElementById('sampleStatus');
let lang = /^ar(?:-|$)/i.test(navigator.language || '') ? 'ar' : 'en';
let pending = false;
let alive = null;
let sampleResult = '';

function render() {
  const tr = messages[lang];
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.title = tr.heading + ' | Scorpion Download Manager';
  for (const id of ['heading', 'stepDownload', 'downloadHint', 'downloadStore', 'downloadInstaller', 'stepConnect', 'connectionHint', 'tryDownload']) {
    const el = document.getElementById(id);
    if (el.textContent !== tr[id]) el.textContent = tr[id];
  }
  const status = tr[alive === null ? 'checking' : alive ? 'online' : 'offline'];
  if (statusEl.textContent !== status) statusEl.textContent = status;
  statusEl.classList.toggle('online', alive === true);
  sampleBtn.hidden = alive !== true;
  sampleStatus.hidden = !sampleResult;
  if (sampleResult) sampleStatus.textContent = tr[sampleResult];
}

function refresh() {
  if (pending) return;
  pending = true;
  chrome.runtime.sendMessage({ action: 'SCORPION_CHECK_STATUS' }, (result) => {
    pending = false;
    alive = !chrome.runtime.lastError && result?.alive === true;
    if (result?.config?.lang === 'ar' || result?.config?.lang === 'en') lang = result.config.lang;
    render();
  });
}

sampleBtn.addEventListener('click', () => {
  sampleBtn.disabled = true;
  chrome.runtime.sendMessage({ action: 'SCORPION_TRY_SAMPLE' }, (result) => {
    const accepted = !chrome.runtime.lastError && result?.ok === true;
    sampleResult = accepted ? 'accepted' : 'failed';
    sampleBtn.disabled = accepted;
    render();
  });
});

render();
refresh();
window.setInterval(refresh, 2500);
