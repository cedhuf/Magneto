/* The Following page: one block per provider, its cost shown before its list.
   The original defect was not that the import said nothing, it was that the
   budget was visible nowhere outside that message. */
const fs = require('fs');
const path = require('path');
const REPO = require('path').resolve(__dirname, '..');

const nodes = new Map();
function makeEl(tag) {
  const el = {
    tagName: tag, id: '', className: '', hidden: false, disabled: false,
    children: [], _text: '', _html: '', listeners: {},
    appendChild(c) { this.children.push(c); return c; },
    replaceChildren(...cs) { this.children = cs; },
    remove() {}, addEventListener(n, f) { this.listeners[n] = f; },
    setAttribute() {}, removeAttribute() {}, querySelectorAll: () => [],
    querySelector: () => null, click() {}, classList: {toggle() {}, add() {}, remove() {}},
    dataset: {}, style: {},
  };
  Object.defineProperty(el, 'textContent', {
    get() { return this._text; }, set(v) { this._text = String(v); this._html = String(v); }});
  Object.defineProperty(el, 'innerHTML', {get() { return this._html; }, set(v) { this._html = String(v); }});
  return el;
}
global.document = {
  createElement: makeEl,
  getElementById(id) {
    if (!nodes.has(id)) { const el = makeEl('div'); el.id = id; nodes.set(id, el); }
    return nodes.get(id);
  },
  addEventListener() {}, body: makeEl('body'), documentElement: makeEl('html'),
};
global.window = global;
global.localStorage = {getItem: () => null, setItem() {}, removeItem() {}};
global.setTimeout = f => { f(); return 0; };
global.clearTimeout = () => {};

const payload = {providers: [
  {platform: 'youtube', label: 'YouTube', noun: 'Channel', add: '/api/feed/subscriptions',
   imports: '/api/feed/import', accept: '.csv', file: 'subscriptions.csv of an export',
   hint: 'Paste a URL', followed: 86, limit: 100, slots: 172, round: 51600, every: 300, never: 71,
   items: [{channel_id: 'UC1', title: 'A channel', fetched: Date.now() / 1000 - 3 * 3600, failed: false},
           {channel_id: 'UC2', title: 'No tab', fetched: 0, failed: true}]},
  {platform: 'tiktok', label: 'TikTok', noun: 'Account', add: '/api/tiktok/accounts',
   imports: '/api/tiktok/import', accept: '.json', file: 'user_data_tiktok.json',
   hint: 'Paste a URL', followed: 0, limit: 100, slots: 0, round: 0, every: 120, never: 0, items: []},
]};
global.fetch = url => Promise.resolve({ok: true, json: () => Promise.resolve(
  url === '/api/following' ? payload : {})});

const html = fs.readFileSync(path.join(REPO, 'templates/following.html'), 'utf8');
const libs = [...html.matchAll(/<script src="\/static\/([^"]+)">/g)]
  .map(m => m[1]).filter(f => f !== 'theme.js')
  .map(f => fs.readFileSync(path.join(REPO, 'static', f), 'utf8')).join('\n');
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).filter(s => s.includes('function load'))[0];

const check = `
(async () => {
  await load();
  const out = document.getElementById('providers').innerHTML;

  // The budget is shown at all times, not only when an import is cut short.
  if (!out.includes('86 of 100')) throw new Error('the ceiling is not shown');
  if (!out.includes('172 slots')) throw new Error('the slots are not given');
  if (!out.includes('14 h 20')) throw new Error('the full round is not given: ' + fmtRound(51600));
  if (!out.includes('>71<')) throw new Error('the never-read ones are not counted');
  if (!out.includes('one lookup every 5 min')) throw new Error('the cadence is not given');
  if (!out.includes('one lookup every 2 min')) throw new Error('nor is the other one');
  console.log('  ok    ceiling, slots, round, cadence and never-read, at all times');

  if (!out.includes('YouTube') || !out.includes('TikTok'))
    throw new Error('a provider is missing');
  if (!out.includes('form-youtube') || !out.includes('form-tiktok'))
    throw new Error('a provider has no form');
  if (!out.includes('file-youtube') || !out.includes('file-tiktok'))
    throw new Error('a provider has no import');
  console.log('  ok    one complete block per provider');

  if (!out.includes('3h ago')) throw new Error('the last read is not given');
  if (!out.includes('channel-when failed')) throw new Error('the missing tab is not told apart');
  console.log('  ok    every row gives its last read, and its missing tab');

  // The TikTok export: we follow whom it follows, not who follows it.
  const sample = {'Profile And Settings': {
    Follower: {FansList: [{UserName: 'a_fan'}]},
    Following: {Following: [{UserName: 'nasa'}, {UserName: 'nasa'}, {UserName: ' jane.doe '}]},
  }};
  const read = followedAccounts(sample);
  if (read.includes('a_fan')) throw new Error('followers taken for follows');
  if (read.join() !== 'nasa,jane.doe') throw new Error('unexpected read: ' + read.join());
  console.log('  ok    the follows, deduplicated, never the followers');
})().catch(e => { console.log('  FAIL ' + e.message); process.exit(1); });
`;
eval(libs + '\n' + inline + '\n' + check);
