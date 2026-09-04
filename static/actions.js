/* The two icons that act on an entry: keep it longer, or take it away. They
   appear on a download and on a feed video alike, once there is a file, so the
   pair is built here rather than once per page. */
function entryIcons({ pinned = false, onPin = '', onDelete }) {
  const pin = onPin
    ? `<button class="icon-btn${pinned ? ' on' : ''}" onclick="${onPin}"
        title="${pinned ? 'Pinned, click to unpin' : 'Keep this one longer'}"
        aria-label="Pin">${icon(pinned ? 'pinned' : 'pin')}</button>`
    : '';
  return `<div class="card-icons">${pin}${deleteButton(onDelete, {icon: true})}</div>`;
}
