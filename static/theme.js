/* Theme: system, light, dark. "system" stores nothing and lets the
   stylesheet's media query decide. */
const THEMES = ['system', 'light', 'dark'];
const THEME_LABELS = { system: 'Auto', light: 'Light', dark: 'Dark' };

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
  btn.textContent = THEME_LABELS[theme];
  btn.title = `Theme: ${theme}. Click to change.`;
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
