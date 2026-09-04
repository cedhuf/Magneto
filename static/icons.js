/* Icons from Tabler Icons 3.46.0, MIT licensed: https://tabler.io/icons

   Vendored rather than loaded, so a page still reaches no third party, and only
   the handful actually used is carried. To add one, copy the path data of
   icons/<style>/<name>.svg from the same release. */

const ICONS = {
  play: {fill: true, paths: ['M6 4v16a1 1 0 0 0 1.524 .852l13 -8a1 1 0 0 0 0 -1.704l-13 -8a1 1 0 0 0 -1.524 .852z']},
  pin: {fill: false, paths: ['M15 4.5l-4 4l-4 1.5l-1.5 1.5l7 7l1.5 -1.5l1.5 -4l4 -4', 'M9 15l-4.5 4.5', 'M14.5 4l5.5 5.5']},
  pinned: {fill: true, paths: ['M15.113 3.21l.094 .083l5.5 5.5a1 1 0 0 1 -1.175 1.59l-3.172 3.171l-1.424 3.797a1 1 0 0 1 -.158 .277l-.07 .08l-1.5 1.5a1 1 0 0 1 -1.32 .082l-.095 -.083l-2.793 -2.792l-3.793 3.792a1 1 0 0 1 -1.497 -1.32l.083 -.094l3.792 -3.793l-2.792 -2.793a1 1 0 0 1 -.083 -1.32l.083 -.094l1.5 -1.5a1 1 0 0 1 .258 -.187l.098 -.042l3.796 -1.425l3.171 -3.17a1 1 0 0 1 1.497 -1.26z']},
  trash: {fill: false, paths: ['M4 7l16 0', 'M10 11l0 6', 'M14 11l0 6', 'M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12', 'M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3']},
  close: {fill: false, paths: ['M18 6l-12 12', 'M6 6l12 12']},
  photo: {fill: false, paths: ['M15 8h.01', 'M3 6a3 3 0 0 1 3 -3h12a3 3 0 0 1 3 3v12a3 3 0 0 1 -3 3h-12a3 3 0 0 1 -3 -3v-12', 'M3 16l5 -5c.928 -.893 2.072 -.893 3 0l5 5', 'M14 14l1 -1c.928 -.893 2.072 -.893 3 0l3 3']},
  music: {fill: false, paths: ['M3 17a3 3 0 1 0 6 0a3 3 0 0 0 -6 0', 'M13 17a3 3 0 1 0 6 0a3 3 0 0 0 -6 0', 'M9 17v-13h10v13', 'M9 8h10']},
  error: {fill: false, paths: ['M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0', 'M10 10l4 4m0 -4l-4 4']},
  refresh: {fill: false, paths: ['M20 11a8.1 8.1 0 0 0 -15.5 -2m-.5 -4v4h4', 'M4 13a8.1 8.1 0 0 0 15.5 2m.5 4v-4h-4']},
};

function icon(name) {
  const found = ICONS[name];
  if (!found) return '';
  const paint = found.fill
    ? 'fill="currentColor" stroke="none"'
    : 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
  return `<svg class="icon" viewBox="0 0 24 24" ${paint} aria-hidden="true">${
    found.paths.map(d => `<path d="${d}"/>`).join('')}</svg>`;
}
