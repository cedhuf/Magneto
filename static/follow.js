/* Following someone is one act with two nouns. The feed follows YouTube
   channels, the TikTok page follows accounts, and the list, the forced refresh
   and the removal are the same on both: only the wording and the endpoint that
   resolves a new URL differ, which is what FOLLOWED carries. The page provides
   load() and message(); this file provides the rest. */

function followRows(items) {
  return items.map(item => `<div class="channel-row">
    <span>${esc(item.title)}</span>
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
