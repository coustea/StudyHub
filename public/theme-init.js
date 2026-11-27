// 首屏渲染前定好主题，避免深色模式闪白。
// 放在独立文件里而不是内联，才能兼容 CSP 的 script-src 'self'。
(function () {
  try {
    var stored = localStorage.getItem('notes_theme');
    var mode = stored === 'light' || stored === 'dark' || stored === 'system' ? stored : 'dark';
    var dark = mode === 'dark' || (mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.dataset.themeMode = mode;
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  } catch (error) {
    document.documentElement.dataset.theme = 'dark';
  }
})();
