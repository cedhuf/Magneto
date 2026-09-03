/* Theme: system, light, dark. "system" stores nothing and lets the
   stylesheet's media query decide. */
const THEMES = ['system', 'light', 'dark'];
const THEME_ICONS = {
  system: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
    <circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/></svg>`,
  light: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
    <circle cx="12" cy="12" r="4"/>
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`,
  dark: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round">
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>`,
};

function currentTheme() {
  try {
    return localStorage.getItem('theme') || 'system';
  } catch (e) {
    return 'system';
  }
}

function applyTheme(theme) {
  if (theme === 'system') {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = theme;
  }
  const btn = document.getElementById('theme-btn');
  btn.innerHTML = THEME_ICONS[theme];
  btn.title = `Theme: ${theme}`;
  btn.setAttribute('aria-label', `Theme: ${theme}. Click to change.`);
}

function cycleTheme() {
  const next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
  try {
    if (next === 'system') {
      localStorage.removeItem('theme');
    } else {
      localStorage.setItem('theme', next);
    }
  } catch (e) {}
  applyTheme(next);
}

applyTheme(currentTheme());
