/* Deleting takes two clicks on the button itself rather than a system dialog.
   The confirmation stays where the action is, next to the row it will remove,
   and the browser dialog it replaces could not say which row that was. */

/* Two shapes, one behaviour: a labelled button in a list, an icon on a card.
   `action` is inlined as JavaScript, so it must not carry a double quote. */
function deleteButton(action, { icon: asIcon = false, label = 'Delete', confirm = 'Confirm' } = {}) {
  const shape = asIcon ? 'icon-btn danger' : 'row-btn';
  // The whole interface is set in one monospace face, so the widest of the two
  // labels is a character count: the button is sized for it once and does not
  // resize under the pointer when the words change.
  const room = Math.max(label.length, confirm.length);
  const width = asIcon ? '' : ` style="min-width: calc(${room}ch + ${(room * 0.03).toFixed(2)}em)"`;
  return `<button class="${shape} del-btn" data-confirm="${esc(confirm)}"${width}
    title="${esc(label)}" aria-label="${esc(label)}"
    onclick="if (armDelete(this)) { ${action} }">${asIcon ? icon('trash') : esc(label)}</button>`;
}

let armedDelete = null;
// What the button showed before it was armed. One button is armed at a time, so
// one place to put it back from.
let armedBody = null;
let armedTitle = null;

function disarmDelete() {
  const button = armedDelete;
  if (!button) return;
  armedDelete = null;
  button.classList.remove('armed');
  button.innerHTML = armedBody;
  button.title = armedTitle;
}

/* True on the click that must actually delete, false on the one that arms. */
function armDelete(button) {
  if (armedDelete === button) {
    disarmDelete();
    return true;
  }
  disarmDelete();
  armedDelete = button;
  armedBody = button.innerHTML;
  armedTitle = button.title;
  button.classList.add('armed');
  // Both shapes say the same thing in their own way: the word for a labelled
  // button, the tick for an icon, and never a red square that says nothing.
  button.innerHTML = button.querySelector('svg')
    ? icon('check')
    : esc(button.dataset.confirm || 'Confirm');
  button.title = 'Click again to delete';
  setTimeout(() => { if (armedDelete === button) disarmDelete(); }, 4000);
  return false;
}

// Anywhere else on the page, and the button forgets it was armed.
document.addEventListener('click', e => {
  if (armedDelete && !(e.target.closest && e.target.closest('.del-btn'))) disarmDelete();
});
