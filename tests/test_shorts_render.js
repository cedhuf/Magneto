/* The shorts page, rendered for real: one short at a time, the keyboard, and
   preloading a single next one. */
const fs = require('fs');
const path = require('path');
const REPO = require('path').resolve(__dirname, '..');

const nodes = new Map();
function makeEl(tag) {
  const el = {
    tagName: tag, id: '', className: '', hidden: false, disabled: false,
    children: [], _text: '', _html: '',
    appendChild(c) { this.children.push(c); this._html += '<' + c.tagName + '>'; return c; },
    replaceChildren(...cs) { this.children = cs; },
    scrollTo() {}, clientHeight: 600,
    querySelector(sel) { return this._html.includes('<' + sel) ? makeEl(sel) : null; },
    remove() {}, removeAttribute() {},
    listeners: {},
    addEventListener(name, fn) { (this.listeners[name] = this.listeners[name] || []).push(fn); },
    fire(name, e) { (this.listeners[name] || []).forEach(fn => fn(e || {})); },
    attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    querySelectorAll: () => [], load() {}, pause() {},
    click() {}, dataset: {}, style: {},
    classes: new Set(),
    get classList() {
      const on = this.classes;
      return {
        add: c => on.add(c), remove: c => on.delete(c), contains: c => on.has(c),
        toggle: c => (on.has(c) ? (on.delete(c), false) : (on.add(c), true)),
      };
    },
    // A video refused by Safari: play() returns a rejected promise, not an
    // error. And unlocking is per element: once someone has asked for sound on
    // this one, it does not ask again.
    _muted: false, unlocked: false, paused: true,
    play() {
      if (REFUSE && !this.unlocked && !this._muted) return Promise.reject(new Error('blocked'));
      this.paused = false;
      return Promise.resolve();
    },
  };
  Object.defineProperty(el, 'muted', {
    get() { return this._muted; },
    set(v) { if (!v) this.unlocked = true; this._muted = v; }});
  Object.defineProperty(el, 'textContent', {
    get() { return this._text; }, set(v) { this._text = String(v); this._html = String(v); }});
  Object.defineProperty(el, 'innerHTML', {get() { return this._html; }, set(v) { this._html = String(v); }});
  Object.defineProperty(el, 'outerHTML', {get() { return this._html; }, set(v) { this._html = String(v); }});
  return el;
}
const events = {};
function listenersFor(name) { return events[name]; }
global.document = {
  createElement: makeEl,
  getElementById(id) {
    if (!nodes.has(id)) { const el = makeEl('div'); el.id = id; nodes.set(id, el); }
    return nodes.get(id);
  },
  addEventListener(name, fn) { events[name] = fn; },
  body: makeEl('body'), documentElement: makeEl('html'),
};
global.window = global;
const store = new Map();
global.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k),
};
global.setInterval = (f) => { Promise.resolve().then(f); return 0; };
// Deferred, like a real one: a setTimeout that ran at once would reset the
// wheel counter to zero between two notches.
global.setTimeout = () => 0;
global.clearTimeout = () => {};
global.clearInterval = () => {};
// The same file plays both surfaces: TOUCH=1 replays everything without hover.
const TOUCH = !!process.env.TOUCH;
// REFUSE=1 replays everything with a browser that refuses sound.
const REFUSE = !!process.env.REFUSE;
let watched = [];
global.IntersectionObserver = class {
  constructor(fn) { this.fn = fn; watched = []; }
  observe(el) { watched.push(el); }
  disconnect() { watched = []; }
  // A scroll by hand: the slide enters the frame, the page follows.
  reach(i) { this.fn([{target: watched[i], isIntersecting: true}]); }
};
global.__observer = () => watched;
global.matchMedia = () => ({matches: TOUCH});

const payload = {
  quality: 720,
  clips: [
    {id: 's0', url: 'https://www.youtube.com/shorts/s0', title: 'First', uploader: 'Channel', thumbnail: 't0', upload_date: '20260903', job_id: null, platform: 'youtube'},
    {id: 's1', url: 'https://www.youtube.com/shorts/s1', title: 'Second', uploader: 'NASA', thumbnail: 't1', upload_date: '20260902', job_id: null, platform: 'tiktok'},
    {id: 's2', url: 'https://www.youtube.com/shorts/s2', title: 'Third', uploader: 'Channel', thumbnail: 't2', job_id: null, platform: 'youtube'},
  ],
};
const downloads = [];
let jobs = 0;
const marked = [];
global.fetch = (url, opts) => {
  if (url === '/api/seen') { marked.push(JSON.parse(opts.body).url); return json({ok: true}); }
  if (url === '/api/download') { downloads.push(JSON.parse(opts.body)); return json({job_id: 'job' + (++jobs)}); }
  if (url === '/api/shorts') return json(payload);
  if (url.startsWith('/api/status/')) return json({status: 'done', filename: 's.mp4'});
  return json({});
};
function json(body) { return Promise.resolve({ok: true, json: () => Promise.resolve(body)}); }

const html = fs.readFileSync(path.join(REPO, 'templates/vertical.html'), 'utf8');
/* The list comes from the template itself: a module added to the page is
   loaded here without anyone having to think of it. That is what was missing
   when the feed drifted. */
const libs = [...html.matchAll(/<script src="\/static\/([^"]+)">/g)]
  .map(m => m[1]).filter(f => f !== 'theme.js')
  .map(f => fs.readFileSync(path.join(REPO, 'static', f), 'utf8')).join('\n');
let inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(s => s[1]).filter(s => s.includes('function load'))[0];
// The template is rendered by Jinja: we provide what the render would inject.
// A value added to the template and forgotten here breaks at once, instead of
// producing an invalid script ten lines further down.
const RENDERED = {source: '/api/shorts', manage: false, empty_note: 'Follow some channels.'};
inline = inline.replace(/\{\{\s*(\w+)\s*\|\s*tojson\s*\}\}/g, (_, name) => {
  if (!(name in RENDERED)) throw new Error('template value not provided: ' + name);
  return JSON.stringify(RENDERED[name]);
});

const check = `
(async () => {
  await load();
  await new Promise(r => setImmediate(r));
  await new Promise(r => setImmediate(r));

  if (downloads.length !== 2) throw new Error('preload: ' + downloads.length + ' downloads instead of 2');
  if (downloads.some(d => d.kind !== 'short')) throw new Error('a short leaves without its kind');
  if (downloads[0].url !== payload.clips[0].url || downloads[1].url !== payload.clips[1].url)
    throw new Error('these are not the current one and the next');
  console.log('  ok    the current one and a single one ahead, marked as shorts');

  const out = document.getElementById('frame').innerHTML + document.getElementById('reel').innerHTML;
  // A single video tag for the whole reel, moved from slide to slide:
  // Safari unlocks sound per element, not per page.
  const shown = document.getElementById('reel').children[at].children[0];
  if (!shown || shown.children[0].getAttribute('src') !== '/api/stream/job1')
    throw new Error('the player does not play the server file');
  const media = document.getElementById('reel').children[at].innerHTML;
  if (document.getElementById('reel').children.length !== payload.clips.length)
    throw new Error('the reel does not carry one slide per clip');
  if (document.getElementById('reel').children.some((s, i) => i !== at && s._html.includes('<video')))
    throw new Error('an off-screen slide carries a video');
  // Without hover, the native controls stay up for several seconds on every
  // clip: they are cut and a line shows where playback is.
  if (TOUCH && shown.children[0].controls) throw new Error('native controls on a touch surface');
  if (TOUCH && shown.children.length !== 2) throw new Error('no progress line');
  if (!TOUCH && !shown.children[0].controls) throw new Error('no controls left on a mouse screen');
  if (!TOUCH && shown.children.length !== 1) throw new Error('progress line duplicating the controls');
  if (media.includes('youtube.com')) throw new Error('a youtube embed in the page');
  // Nothing to delete here: a watched clip leaves the reel and the file goes
  // at the sweep. The button only duplicated what happens on its own.
  if (out.includes('del-btn')) throw new Error('delete came back on the reel');
  if (!shown.children[0].loop) throw new Error('the clip does not loop');
  if (!document.getElementById('date').textContent.includes('2026'))
    throw new Error('the publication date is not shown');
  if (document.getElementById('title').textContent !== 'First') throw new Error('wrong title');
  if (!document.getElementById('meta').innerHTML.includes('<svg')) throw new Error('the source is not given');
  if (document.getElementById('empty').hidden !== true) throw new Error('the empty state shows with shorts');
  console.log('  ok    looping playback, no delete, with its date');

  // Safari refusal: the reel moves on anyway, muted, and says so.
  await new Promise(r => setImmediate(r));
  const offer = document.getElementById('sound');
  if (REFUSE && offer.hidden) throw new Error('the refused video stays frozen, offering nothing');
  if (!REFUSE && !offer.hidden) throw new Error('sound is offered while it plays');
  if (REFUSE) {
    unmute();
    if (offer.hidden !== true) throw new Error('the offer stays after the tap');
    console.log('  ok    refused by the browser: mutes, offers sound, gives it back on tap');
  } else {
    console.log('  ok    playback starts on its own when the browser allows it');
  }

  // The clip being left is marked, never the one being watched: that is what
  // puts the player back on it after a reload.
  if (marked.length) throw new Error('a clip was marked without being left');
  step(1);
  if (!marked.includes(payload.clips[0].url)) throw new Error('the clip left is not marked');
  if (marked.includes(payload.clips[1].url)) throw new Error('the current clip was marked');
  console.log('  ok    seen when left, never when reached');
  if (document.getElementById('title').textContent !== 'Second') throw new Error('going down does not move');
  step(-1); step(-1);
  if (document.getElementById('title').textContent !== 'First') throw new Error('going up overshoots');
  console.log('  ok    down, up, and never out of the list');

  if (/Save|Download</.test(document.body._html || '')) throw new Error('a download button is left over');
  console.log('  ok    no download button on the page');

  // Scrolling is the browser's: the page learns where it stopped.
  const eye = watcher;
  eye.reach(1);
  if (at !== 1) throw new Error('a scroll by hand does not update the page');
  if (document.getElementById('title').textContent !== 'Second') throw new Error('the caption does not follow');
  eye.reach(0);
  if (at !== 0) throw new Error('scrolling back up does not update the page');
  console.log('  ok    the reel leads, the page follows');

  // Fullscreen: a class, with the native API on top when it exists.
  // iOS has no element fullscreen, so the class alone must be enough.
  toggleFull();
  if (!document.body.classList.contains('full')) throw new Error('fullscreen does not turn on');
  toggleFull();
  if (document.body.classList.contains('full')) throw new Error('fullscreen cannot be left');
  console.log('  ok    fullscreen turns on and off without the native API');

  if (inline.includes("addEventListener('wheel'")) throw new Error('a wheel counter came back');
  console.log('  ok    no gesture is measured by the page');

  if (REFUSE) {
    // Once sound is given back, the element stays unlocked: the next clip
    // starts with sound without another tap. That is the point of one element.
    step(1);
    await new Promise(r => setImmediate(r));
    if (!document.getElementById('sound').hidden)
      throw new Error('sound has to be tapped again on every clip');
    console.log('  ok    sound given back once holds for the whole reel');
  }
})().catch(e => { console.log('  FAIL ' + e.message); process.exit(1); });
`;
eval(libs + '\n' + inline + '\n' + check);
