/* One modal for both pages. The feed had its own, built in markup and closed by
   its own handlers, while the home page built another in JavaScript: two shells,
   two ways to close, one purpose. */

let openOverlay = null;

function closeModal() {
  if (!openOverlay) return;
  const media = openOverlay.querySelector('.modal-media');
  if (media && media.pause) {
    // Clearing the source stops the transfer; removing the node alone leaves
    // some engines downloading in the background.
    media.pause();
    media.removeAttribute('src');
    media.load();
  }
  openOverlay.remove();
  openOverlay = null;
  document.removeEventListener('keydown', onModalKey);
  document.body.style.overflow = '';
}

function onModalKey(e) {
  if (e.key === 'Escape') closeModal();
}

/* media, actions and description are optional HTML fragments, so the same
   shell serves a bare player and a full video sheet. */
function openModal({ title = '', meta = '', description = '', media = '', actions = '' }) {
  closeModal();
  const overlay = document.createElement('div');
  overlay.className = 'modal';
  overlay.innerHTML = `
    <div class="modal-box" role="dialog" aria-modal="true">
      <button class="modal-close" aria-label="Close" title="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
      <div class="modal-media-slot">${media}</div>
      <div class="modal-body">
        ${title ? `<h2 class="modal-title">${esc(title)}</h2>` : ''}
        ${meta ? `<div class="modal-meta">${esc(meta)}</div>` : ''}
        ${description ? `<p class="modal-desc">${esc(description)}</p>` : ''}
        ${actions ? `<div class="modal-actions">${actions}</div>` : ''}
      </div>
    </div>`;
  overlay.addEventListener('click', e => {
    if (e.target === overlay) closeModal();
  });
  overlay.querySelector('.modal-close').addEventListener('click', closeModal);
  document.addEventListener('keydown', onModalKey);
  document.body.style.overflow = 'hidden';
  document.body.appendChild(overlay);
  openOverlay = overlay;
  return overlay;
}

/* The app's own player, on the app's own file. Never a third-party embed: the
   point of downloading first is that nothing leaves the instance. */
function mediaMarkup(jobId, filename) {
  const tag = (filename || '').toLowerCase().endsWith('.mp3') ? 'audio' : 'video';
  return `<${tag} class="modal-media" src="/api/stream/${encodeURIComponent(jobId)}"
           controls autoplay playsinline></${tag}>`;
}

function posterMarkup(thumbnail, label) {
  return `<div class="modal-poster">
      ${thumbnail ? `<img src="${esc(thumbnail)}" alt="">` : ''}
      <div class="modal-poster-note">${esc(label)}</div>
    </div>`;
}
