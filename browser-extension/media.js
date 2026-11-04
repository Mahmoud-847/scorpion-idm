/* Shared by the content script, service worker, and regression tests. */
(function (root) {
  'use strict';
  const isManifest = (url) => /\.(m3u8|mpd)(?:[?#]|$)/i.test(url);
  function isFragment(url) {
    if (isManifest(url)) return false;
    try {
      const u = new URL(url);
      return /\.(m4s|cmfv|cmfa|ts)(?:$)/i.test(u.pathname) ||
        /(?:^|[/_.-])(?:seg(?:ment)?|frag(?:ment)?|chunk|init)[-_.]?\d*(?:[_.-]|$)/i.test(u.pathname) ||
        ['bytestart', 'byteend'].some((key) => u.searchParams.has(key)) ||
        /^\d+-\d+$/.test(u.searchParams.get('range') || '');
    } catch (_) { return false; }
  }
  function isTelegram(url) {
    try { return new URL(url).hostname === 'web.telegram.org'; } catch (_) { return false; }
  }
  function isBrowserLocal(url) {
    return /^blob:/i.test(url || '') || (isTelegram(url) && /\/(?:progressive|stream|download)\//i.test(new URL(url).pathname));
  }
  function mediaDuration(media) {
    const duration = Number(media && media.duration);
    return Number.isFinite(duration) && duration > 0 ? duration : 0;
  }
  root.ScorpionMedia = { isManifest, isFragment, isTelegram, isBrowserLocal, mediaDuration };
  if (typeof module !== 'undefined') module.exports = root.ScorpionMedia;
})(globalThis);
