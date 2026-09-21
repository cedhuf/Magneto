/* Every page loads the sheet that draws what it contains.

   The split has a cost: a class can be written in a file the page does not
   load, and nothing on screen says so. This test does.

   Its limit: it checks whether the name appears, not whether the rule really
   dresses the element. A rule that only hides the class under a state, like
   body.full .thing, is enough to reassure it. That is how it missed
   .feed-head on the home on 2026-09-05. */
const fs = require('fs');
const path = require('path');
const REPO = require('path').resolve(__dirname, '..');

const PAGES = {
  'index.html': ['base', 'cards'],
  'feed.html': ['base', 'cards', 'follow'],
  'following.html': ['base', 'follow'],
  'vertical.html': ['base', 'vertical'],
  'admin.html': ['base', 'cards', 'admin'],
};

// Markers with no style of their own: a state carried by another rule, or an
// anchor the JS fills.
const UNSTYLED = new Set(['icon', 'grid', 'list', 'active', 'on', 'armed', 'ready',
                            'danger', 'failed', 'full', 'muted', 'as-text', 'start', 'end',
                            'round-slot', 'modal-media-slot', 'q-odd']);

function defined(sheets) {
  const found = new Set();
  for (const sheet of sheets) {
    const css = fs.readFileSync(path.join(REPO, 'static', `${sheet}.css`), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '');
    for (const m of css.matchAll(/\.([a-zA-Z][\w-]*)/g)) found.add(m[1]);
  }
  return found;
}

let bad = 0;
for (const [page, sheets] of Object.entries(PAGES)) {
  const html = fs.readFileSync(path.join(REPO, 'templates', page), 'utf8');
  // The template, plus every module it loads: a class can be born in JS.
  let source = html;
  for (const m of html.matchAll(/<script src="\/static\/([^"]+)">/g)) {
    source += fs.readFileSync(path.join(REPO, 'static', m[1]), 'utf8');
  }
  // The header is included everywhere, and it carries its own classes.
  source += fs.readFileSync(path.join(REPO, 'templates/_header.html'), 'utf8');

  // Jinja and the JS templates write expressions in the attribute: they are
  // stripped, or every variable name would pass for a class.
  source = source.replace(/\$\{[^}]*\}/g, ' ').replace(/\{[{%][\s\S]*?[%}]\}/g, ' ');
  const used = new Set();
  for (const m of source.matchAll(/class="([^"]*)"/g)) {
    for (const c of m[1].split(/[\s${}?:'`+]+/)) {
      if (/^[a-zA-Z][\w-]*$/.test(c)) used.add(c);
    }
  }
  for (const m of source.matchAll(/classList\.\w+\('([\w-]+)'\)/g)) used.add(m[1]);

  const have = defined(sheets);
  const missing = [...used].filter(c => !have.has(c) && !UNSTYLED.has(c));
  if (missing.length) {
    console.log(`  FAIL ${page} uses without loading them: ${missing.join(', ')}`);
    bad++;
  }
  // And the reverse: a sheet loaded for nothing weighs on every visit.
  for (const sheet of sheets.filter(s => s !== 'base')) {
    const own = defined([sheet]);
    if (![...own].some(c => used.has(c))) {
      console.log(`  FAIL ${page} loads ${sheet}.css without using any of it`);
      bad++;
    }
  }
}
if (fs.existsSync(path.join(REPO, 'static/style.css'))) {
  console.log('  FAIL style.css is still there');
  bad++;
}
if (bad) process.exit(1);
console.log('  ok    every page loads what it draws, and nothing more');
