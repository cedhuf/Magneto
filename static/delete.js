/* Deleting takes two clicks on the button itself rather than a system dialog.
   The confirmation stays where the action is, next to the row it will remove,
   and the browser dialog it replaces could not say which row that was. */


/* Two shapes, one behaviour: a labelled button in a list, an icon on a card.
   `action` is inlined as JavaScript, so it must not carry a double quote. */
function deleteButton(action, { icon: asIcon = false, label = 'Delete', confirm = 'Confirm' } = {}) {
  const shape = asIcon ? 'icon-btn danger' : 'row-btn';
  return `<button class="${shape} del-btn" data-confirm="${esc(confirm)}"
    title="${esc(label)}" aria-label="${esc(label)}"
    onclick="if (armDelete(this)) { ${action} }">${asIcon ? icon('trash') : esc(label)}</button>`;
}

let armedDelete = null;

function disarmDelete() {
  const button = armedDelete;
  if (!button) return;
  armedDelete = null;
  button.classList.remove('armed');
  if (button.dataset.label !== undefined) {
    button.textContent = button.dataset.label;
    delete button.dataset.label;
  }
  if (button.dataset.title !== undefined) {
    button.title = button.dataset.title;
    delete button.dataset.title;
  }
}

/* True on the click that must actually delete, false on the one that arms. */
function armDelete(button) {
  if (armedDelete === button) {
    disarmDelete();
    return true;
  }
  disarmDelete();
  armedDelete = button;
  button.classList.add('armed');
  // A labelled button says what the next click does; an icon has only its
  // colour to say it, so it says the rest in the tooltip.
  if (!button.querySelector('svg')) {
    button.dataset.label = button.textContent;
    button.textContent = button.dataset.confirm || 'Confirm';
  }
  button.dataset.title = button.title;
  button.title = 'Click again to delete';
  setTimeout(() => { if (armedDelete === button) disarmDelete(); }, 4000);
  return false;
}

// Anywhere else on the page, and the button forgets it was armed.
document.addEventListener('click', e => {
  if (armedDelete && !(e.target.closest && e.target.closest('.del-btn'))) disarmDelete();
});
