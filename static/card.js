/* One card, two densities. The downloader built its own markup and the feed
   built another for the same object, so a badge or a state had to be added
   twice. Layout is decided by the container, not by the card: the toggle adds
   one class and every card follows. */

function badgeMarkup(badges) {
  return (badges || [])
    .filter(b => b && b.text)
    .map(b => `<span class="thumb-badge ${b.place || ''}"${b.id ? ` id="${b.id}"` : ''}>${esc(b.text)}</span>`)
    .join('');
}

function thumbMarkup({ thumbnail, badges, play, alt = '' }) {
  const image = thumbnail
    ? `<img src="${esc(thumbnail)}" alt="${esc(alt)}">`
    : `<div class="no-thumb">${icon('photo')}</div>`;
  const button = play
    ? `<button class="thumb-play" onclick="${play}" aria-label="Play" title="Play">${icon('play')}</button>`
    : '';
  return `<div class="card-thumb">${image}${button}${badgeMarkup(badges)}</div>`;
}

/* Every section is optional, which is what lets one function serve a queue row
   and a feed tile without either growing a special case. */
function mediaCardMarkup({ id, thumbnail, alt, badges, play, title, meta,
                           note, chips, actions, className = '' }) {
  return `<div class="card ${className}"${id ? ` id="${id}"` : ''}>
    ${thumbMarkup({ thumbnail, badges, play, alt })}
    <div class="card-body">
      <div class="card-title">${esc(title)}</div>
      ${meta ? `<div class="card-meta">${meta}</div>` : ''}
      ${note ? `<div class="card-note-row">${note}</div>` : ''}
      ${chips ? `<div class="card-chips">${chips}</div>` : ''}
    </div>
    ${actions ? `<div class="card-side">${actions}</div>` : ''}
  </div>`;
}

/* The choice is per page and per browser: it is a viewing preference, not
   something the server has any business remembering. */
function initLayoutToggle(containerIds, storageKey, fallback) {
  const button = document.getElementById('layoutBtn');
  let layout = fallback;
  try {
    layout = localStorage.getItem(storageKey) || fallback;
  } catch (e) {}

  function apply() {
    containerIds.forEach(cid => {
      const el = document.getElementById(cid);
      if (el) el.classList.toggle('grid', layout === 'grid');
    });
    if (button) button.textContent = layout === 'grid' ? 'Rows' : 'Grid';
  }

  if (button) {
    button.addEventListener('click', () => {
      layout = layout === 'grid' ? 'rows' : 'grid';
      try {
        localStorage.setItem(storageKey, layout);
      } catch (e) {}
      apply();
    });
  }
  apply();
}
