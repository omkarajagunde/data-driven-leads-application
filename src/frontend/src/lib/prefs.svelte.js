// The two site-wide switches: dark or light, and gamified or classic.
// They live on <html> as data-theme and data-mode (index.html sets them before the first paint)
// and are remembered in this browser.
const CHOICES = { theme: ['dark', 'light'], mode: ['game', 'classic'] };

function read(key) {
  const fromPage = document.documentElement.dataset[key];
  return CHOICES[key].includes(fromPage) ? fromPage : CHOICES[key][0];
}

export const prefs = $state({ theme: read('theme'), mode: read('mode') });

export function setPref(key, value) {
  if (!CHOICES[key]?.includes(value)) return;
  prefs[key] = value;
  document.documentElement.dataset[key] = value;
  try { localStorage.setItem(`subak.${key}`, value); } catch { /* private window: the choice lasts this visit */ }
}
