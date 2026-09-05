/* Following is one act with several nouns, so it has one page and one file.
   The reading pages read; this is where accounts are added, listed and dropped.
   The page provides load() and message(); everything else is here. */

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

/* Refreshing one on purpose skips the spacing that Refresh all obeys: the user
   knows a video is out, and asking about every account to reach that one is
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
    message('Refreshed.');
  } catch (err) {
    message(friendlyError(err.message), true);
    button.disabled = false; button.textContent = 'Refresh';
  }
}

async function unfollow(id) {
  await fetch(`/api/feed/subscriptions/${encodeURIComponent(id)}`, {method: 'DELETE'});
  await load();
}

/* Every followed account, one request each, so the wait is visible and no
   single call can outlive the worker timeout. Spacing is not skipped here the
   way it is for one deliberate click: this is a sweep, not an urgency. */
async function refreshAll(button, items) {
  button.disabled = true;
  let done = 0, skipped = 0, failed = 0;
  for (let i = 0; i < items.length; i++) {
    button.textContent = `Refreshing ${i + 1}/${items.length}…`;
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
  button.textContent = 'Refresh all';
}

/* A TikTok export is read here and never uploaded: it carries the account's
   phone number, address and email a couple of keys away from the list of
   accounts. Only the handles leave the browser. */
function followedAccounts(data) {
  const found = [];
  const walk = (node, key) => {
    if (Array.isArray(node)) {
      // Every list of {UserName} is a list of people, but the followers are one
      // of them too. The branch is named rather than the path, which TikTok
      // renames between exports.
      if (!/following/i.test(key)) return;
      for (const item of node) {
        if (item && typeof item.UserName === 'string') found.push(item.UserName.trim());
      }
    } else if (node && typeof node === 'object') {
      for (const [name, value] of Object.entries(node)) walk(value, name);
    }
  };
  walk(data, '');
  return [...new Set(found)].filter(Boolean);
}

const READERS = {
  youtube: async file => ({csv: await file.text()}),
  tiktok: async file => ({accounts: followedAccounts(JSON.parse(await file.text()))}),
};

function wireFollowing(provider) {
  const platform = provider.platform;
  const noun = provider.noun.toLowerCase();
  const at = suffix => document.getElementById(`${suffix}-${platform}`);

  at('form').addEventListener('submit', async e => {
    e.preventDefault();
    const button = at('submit');
    button.disabled = true; button.textContent = 'Adding…';
    message(`Looking up ${noun}…`);
    try {
      const res = await fetch(provider.add, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url: at('url').value}),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Could not add ${noun}`);
      at('url').value = '';
      message(`${provider.noun} added.`);
      await load();
    } catch (err) { message(friendlyError(err.message), true); }
    button.disabled = false; button.textContent = 'Add';
  });

  /* An import follows everybody at once and looks nobody up: the poller fills
     them one at a time, which is the whole point. */
  at('file').addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    message('Reading the file…');
    try {
      const res = await fetch(provider.imports, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(await READERS[platform](file)),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.error || 'Could not read this file');
      await load();
      const parts = [`${d.added} ${noun}${d.added === 1 ? '' : 's'} added`];
      if (d.already) parts.push(`${d.already} already followed`);
      if (d.skipped) parts.push(`${d.skipped} unreadable`);
      if (d.full) parts.push(`stopped at the ${d.limit} limit`);
      message(`${parts.join(', ')}. One comes round every ${Math.round(d.every / 60)} min.`);
    } catch (err) { message(friendlyError(err.message), true); }
    e.target.value = '';
  });

  at('refresh').addEventListener('click', e => refreshAll(e.target, provider.items));
}
