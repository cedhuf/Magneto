/* Really renders the cards, with a minimal DOM. A refactor twice left code
   that was syntactically valid and threw a ReferenceError on the first
   render: neither node --check nor a read-through sees that, only running it. */
const fs = require('fs');
const path = require('path');
const REPO = require('path').resolve(__dirname, '..');

const nodes = new Map();
function makeEl(tag) {
  const el = {
    tagName: tag, id: '', className: '', hidden: false, children: [], parentElement: null,
    _text: '', _html: '',
    appendChild(c) { c.parentElement = this; this.children.push(c); return c; },
    prepend(c) { c.parentElement = this; this.children.unshift(c); return c; },
    remove() {}, addEventListener() {}, setAttribute() {}, removeAttribute() {},
    querySelector: () => makeEl('div'), querySelectorAll: () => [], load() {}, pause() {},
    classList: {toggle() {}, add() {}, remove() {}}, dataset: {}, style: {},
  };
  Object.defineProperty(el, 'textContent', {
    get() { return this._text; },
    set(v) { this._text = String(v); this._html = String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;'); },
  });
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
global.fetch = () => new Promise(() => {});
global.setInterval = () => 0;
global.setTimeout = () => 0;
global.location = {search: ''};

const libs = ['icons.js', 'format.js', 'card.js', 'modal.js', 'theme.js', 'delete.js', 'actions.js']
  .map(f => fs.readFileSync(path.join(REPO, 'static', f), 'utf8')).join('\n');
const html = fs.readFileSync(path.join(REPO, 'templates/index.html'), 'utf8');
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(m => m[1]).filter(s => s.includes('renderCard'))[0];
const check = fs.readFileSync(path.join(__dirname, 'render_check.js'), 'utf8');

// A single eval: what an eval declares does not leave its scope.
eval(libs + '\n' + inline + '\n' + check);
console.log('the 7 card states render, and the 13 functions called exist');
