/* Following someone is one act with two nouns. The feed follows YouTube
   channels, the TikTok page follows accounts, and the list, the forced refresh
   and the removal are the same on both: only the wording and the endpoint that
   resolves a new URL differ, which is what FOLLOWED carries. The page provides
   load() and message(); this file provides the rest. */

function followRows(items) {
  return items.map(item => `<div class="channel-row">
    <span>${esc(item.title)}</span>
    <span class="channel-when${item.failed ? ' failed' : ''}">${
      item.failed ? 'no videos tab' : fmtAgo(item.fetched)}</span>
    <span class="channel-actions">
      <button class="row-btn" onclick="refreshFollowed('${esc(item.channel_id)}', this)">Refresh</button>
      ${deleteButton(`unfollow('${esc(item.channel_id)}')`, {label: 'Remove'})}
    </span>
  </div>`).join('');
}

/* Refreshing one on purpose skips the spacing that Refresh feed obeys: the user
   knows a video is out, and asking about every channel to reach that one is
   what made the button useless. */
async function refreshFollowed(id, button) {
  button.disabled = true; button.textContent = 'Refreshing…';
  try {
    const res = await fetch('/api/feed/refresh', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({channel_id: id, force: true}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Could not refresh');
    await load();
    message(`${FOLLOWED.noun} refreshed.`);
  } catch (err) {
    message(friendlyError(err.message), true);
    button.disabled = false; button.textContent = 'Refresh';
  }
}

async function unfollow(id) {
  await fetch(`/api/feed/subscriptions/${encodeURIComponent(id)}`, {method: 'DELETE'});
  await load();
}

function wireFollowForm() {
  const form = document.getElementById('addForm');
  const input = document.getElementById('followUrl');
  const button = document.getElementById('addSubmit');
  const noun = FOLLOWED.noun.toLowerCase();
  form.addEventListener('submit', async e => {
    e.preventDefault();
    button.disabled = true; button.textContent = 'Adding…';
    message(`Looking up ${noun}…`);
    try {
      const res = await fetch(FOLLOWED.add, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url: input.value}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Could not add ${noun}`);
      input.value = '';
      message(`${FOLLOWED.noun} added.`);
      await load();
    } catch (err) { message(friendlyError(err.message), true); }
    button.disabled = false; button.textContent = 'Add';
  });
}

/* Every followed account, one request each, so the wait is visible and no
   single call can outlive the worker timeout. Spacing is not skipped here the
   way it is for one deliberate click: this is a sweep, not an urgency. */
async function refreshAll(button, items, label) {
  button.disabled = true;
  let done = 0, skipped = 0, failed = 0;
  for (let i = 0; i < items.length; i++) {
    button.textContent = `Refreshing ${i + 1}/${items.length}\u2026`;
    try {
      const res = await fetch('/api/feed/refresh', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({channel_id: items[i].channel_id}),
      });
      const data = await res.json();
      if (!res.ok) failed++;
      else if (data.skipped) skipped++;
      else done++;
    } catch (e) { failed++; }
  }
  await load();
  // Skipped is the normal case, not a failure: the server refuses to ask again
  // about an account it looked up a moment ago.
  const parts = [];
  if (done) parts.push(`${done} refreshed`);
  if (skipped) parts.push(`${skipped} already fresh`);
  if (failed) parts.push(`${failed} failed`);
  message(parts.join(', ') || 'Nothing to refresh.', !!failed);
  button.disabled = false;
  button.textContent = label;
}
