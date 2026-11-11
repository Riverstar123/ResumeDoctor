'use strict';

(() => {
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  function apply() {
    let preference = 'light';
    try { preference = localStorage.getItem('rd:theme') || 'light'; } catch {}
    const dark = preference === 'dark' || (preference === 'system' && system.matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
    document.querySelector('meta[name="theme-color"]').content = dark ? '#07080f' : '#f7f7fb';
  }
  apply();
  system.addEventListener('change', apply);
  window.addEventListener('storage', (event) => {
    if (event.key === 'rd:theme' || event.key === null) apply();
  });
})();
