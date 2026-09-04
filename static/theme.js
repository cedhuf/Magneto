/* Theme: system, light, dark. "system" stores nothing and lets the stylesheet's
   media query decide. The label itself is drawn by CSS from the same attribute,
   so nothing here runs before the button reads correctly. */
const THEMES = ['system', 'light', 'dark'];

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
  if (btn) btn.title = `Theme: ${theme}. Click to change.`;
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
