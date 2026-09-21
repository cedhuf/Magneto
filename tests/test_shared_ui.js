/* Following an account happens in one place. This test fails the day a
   reading page starts doing it itself again: that is exactly how the feed and
   the home had drifted apart. */
const fs = require('fs');
const REPO = require('path').resolve(__dirname, '..');
const readers = ['templates/feed.html', 'templates/vertical.html', 'templates/index.html']
  .map(p => [p, fs.readFileSync(`${REPO}/${p}`, 'utf8')]);
const following = fs.readFileSync(`${REPO}/templates/following.html`, 'utf8');

let bad = 0;
const owned = {
  'jobs.js': ['function waitForFile'],
  'follow.js': ['function followRows', 'function refreshFollowed', 'function unfollow',
                'function refreshAll', 'function followedAccounts', 'function wireFollowing'],
};
for (const [file, marks] of Object.entries(owned)) {
  const src = fs.readFileSync(`${REPO}/static/${file}`, 'utf8');
  for (const mark of marks) {
    if (!src.includes(mark)) { console.log(`  FAIL ${mark} missing from ${file}`); bad++; }
    for (const [name, html] of readers) {
      if (html.includes(mark)) { console.log(`  FAIL ${name} redefines ${mark}`); bad++; }
    }
  }
}
// Waiting for a file is shared by both pages that read.
for (const [name, html] of readers.filter(([n]) => n !== 'templates/index.html')) {
  if (!html.includes('/static/jobs.js')) { console.log(`  FAIL ${name} does not load jobs.js`); bad++; }
}
// Following belongs to a single page.
if (!following.includes('/static/follow.js')) { console.log('  FAIL following does not load follow.js'); bad++; }
for (const [name, html] of readers) {
  if (html.includes('/static/follow.js')) { console.log(`  FAIL ${name} loads follow.js`); bad++; }
  for (const trace of ['/api/feed/subscriptions', '/api/tiktok/accounts',
                       '/api/feed/import', '/api/tiktok/import', '/api/feed/refresh']) {
    if (html.includes(trace)) { console.log(`  FAIL ${name} still calls ${trace}`); bad++; }
  }
  if (/type="file"/.test(html)) { console.log(`  FAIL ${name} still carries an import`); bad++; }
}
if (bad) process.exit(1);
console.log('  ok    one wait for a file, and one place to follow');
