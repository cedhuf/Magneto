/* The feed was run by no test: that is how it drifted away from the home
   (title button, a modal of its own). It is rendered for real here. */
const fs = require('fs');
const path = require('path');
const REPO = require('path').resolve(__dirname, '..');

const nodes = new Map();
function makeEl(tag) {
  const el = {
    tagName: tag, id: '', className: '', hidden: false, disabled: false,
    children: [], _text: '', _html: '',
    appendChild(c) { this.children.push(c); return c; },
    remove() {}, addEventListener() {}, setAttribute() {}, removeAttribute() {},
    querySelector: () => makeEl('div'), querySelectorAll: () => [], load() {}, pause() {},
    click() {}, classList: {toggle() {}, add() {}, remove() {}}, dataset: {}, style: {},
  };
  Object.defineProperty(el, 'textContent', {
    get() { return this._text; }, set(v) { this._text = String(v); this._html = String(v); }});
  Object.defineProperty(el, 'innerHTML', {get() { return this._html; }, set(v) { this._html = String(v); }});
  Object.defineProperty(el, 'outerHTML', {get() { return this._html; }, set(v) { this._html = String(v); }});
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
global.setInterval = (f) => { Promise.resolve().then(f); return 0; };
global.setTimeout = (f) => { f(); return 0; };
global.clearInterval = () => {};

const feed = {
  channels: [{channel_id: 'UC1', title: 'A channel', videos: []}],
  videos: [
    {url: 'https://www.youtube.com/watch?v=a', title: 'A video', uploader: 'A channel',
     upload_date: '20260101', duration: 213, thumbnail: 'https://i.ytimg.com/x.jpg', ready: true, job_id: 'job1', pinned: false},
    {url: 'https://www.youtube.com/watch?v=b', title: 'Another', uploader: 'A channel',
     upload_date: '20251231', duration: 90, thumbnail: '', ready: false},
  ],
  settings: {videos: 3, quality: 720},
  limits: {videos_max: 5, qualities: [720, 1080]},
};
const calls = [];
global.fetch = (url, opts) => {
  calls.push([url, opts]);
  const body = url === '/api/feed' ? feed
    : url === '/api/download' ? {job_id: 'job123'}
    : url.startsWith('/api/status/') ? {status: 'done', filename: 'A video.mp4'}
    : {};
  return Promise.resolve({ok: true, json: () => Promise.resolve(body)});
};

const html = fs.readFileSync(path.join(REPO, 'templates/feed.html'), 'utf8');
/* The list comes from the template itself: a module added to the page is
   here without anyone having to think of it. That is what was missing when the
   feed drifted. */
const libs = [...html.matchAll(/<script src="\/static\/([^"]+)">/g)]
  .map(m => m[1]).filter(f => f !== 'theme.js')
  .map(f => fs.readFileSync(path.join(REPO, 'static', f), 'utf8')).join('\n');
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).filter(s => s.includes('function load'))[0];

const check = `
(async () => {
  await load();
  const out = document.getElementById('videos').innerHTML;
  if (!out.includes('card-title')) throw new Error('no card rendered');
  if (out.includes('as-text') || out.includes('<button class="card-title'))
    throw new Error('the title became clickable again');
  if (out.includes('On the server') || out.includes('Not downloaded yet'))
    throw new Error('poster label came back');
  console.log('  ok    ' + (out.match(/class="card /g) || []).length + ' cartes, titres non cliquables');

  // A feed video with a file of mine carries the same actions as on the home.
  const first = out.split('card-side')[1] || '';
  const second = out.split('card-side')[2] || '';
  if (!first.includes('card-icons')) throw new Error('no pin/delete on a downloaded video');
  if (!first.includes('togglePin(0)') || !first.includes('removeVideo(0)'))
    throw new Error('the actions are not wired');
  if (second.includes('card-icons')) throw new Error('actions on a video without a file');
  console.log('  ok    pin and delete appear with the file, not before');

  await playVideo(0);
  const modal = document.body.children.slice(-1)[0];
  const shell = modal ? modal.innerHTML : '';
  if (!shell.includes('/api/stream/job123')) throw new Error('the player does not play the server file');
  if (shell.includes('modal-poster')) throw new Error('poster came back');
  if (shell.includes('modal-actions')) throw new Error('actions came back in the modal');
  if (!shell.includes('A channel')) throw new Error('metadata missing');
  console.log('  ok    the modal is the home one: player, title, meta');
})().catch(e => { console.log('  FAIL ' + e.message); process.exit(1); });
`;
eval(libs + '\n' + inline + '\n' + check);
