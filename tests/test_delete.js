/* The delete button: two clicks, one mechanism for both forms. With the
   system dialog gone, it is the only guard rail left. */
const fs = require('fs');
const REPO = require('path').resolve(__dirname, '..');

const listeners = {capture: [], bubble: []};
global.document = {
  addEventListener(_, fn, capture) { listeners[capture ? 'capture' : 'bubble'].push(fn); },
  // esc() goes through a text node to escape: we provide the same service.
  createElement: () => ({textContent: '', get innerHTML() {
    return String(this.textContent).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }}),
};
global.window = global;
let timers = [];
global.setTimeout = (fn) => { timers.push(fn); return timers.length; };

function button(html) {
  const classes = new Set((html.match(/class="([^"]*)"/) || [null, ''])[1].split(' '));
  const inner = (html.match(/>([\s\S]*)<\/button>/) || [null, ''])[1];
  const el = {
    dataset: {}, title: (html.match(/title="([^"]*)"/) || [null, ''])[1],
    innerHTML: inner,
    classList: {add: c => classes.add(c), remove: c => classes.delete(c)},
    querySelector: sel => (sel === 'svg' && el.innerHTML.includes('<svg') ? {} : null),
    closest: () => el,
  };
  const confirmAttr = html.match(/data-confirm="([^"]*)"/);
  if (confirmAttr) el.dataset.confirm = confirmAttr[1];
  el.armed = () => classes.has('armed');
  return el;
}

eval(fs.readFileSync(REPO + '/static/icons.js', 'utf8') + '\n'
   + fs.readFileSync(REPO + '/static/format.js', 'utf8') + '\n'
   + fs.readFileSync(REPO + '/static/delete.js', 'utf8'));

const text = deleteButton("removeChannel('UC1')", {label: 'Remove'});
const iconForm = deleteButton('removeCard(3)', {icon: true});
if (!text.includes('row-btn') || text.includes('<svg')) throw new Error('text form broken');
if (!iconForm.includes('icon-btn') || !iconForm.includes('<svg')) throw new Error('icon form broken');
if (!text.includes('if (armDelete(this)) { removeChannel(\'UC1\') }')) throw new Error('action not wired');
console.log('  ok    two forms, a single inlined action');

const b = button(text);
if (armDelete(b) !== false) throw new Error('the first click deletes');
if (!b.armed()) throw new Error('the first click does not colour');
if (b.innerHTML !== 'Confirm') throw new Error('the label does not say what the next click does: ' + b.innerHTML);
if (armDelete(b) !== true) throw new Error('the second click does not delete');
if (b.armed()) throw new Error('the button stays armed after deleting');
if (b.innerHTML !== 'Remove') throw new Error('label not restored: ' + b.innerHTML);
console.log('  ok    text form: arm, say, delete, come back');

const i = button(iconForm);
const trash = i.innerHTML;
armDelete(i);
if (!i.armed()) throw new Error('the icon does not arm');
if (i.innerHTML === trash) throw new Error('the icon does not change: a mute red square');
if (i.innerHTML !== icon('check')) throw new Error('this is not the check mark: ' + i.innerHTML);
if (i.title !== 'Click again to delete') throw new Error('nothing says what is about to happen');
armDelete(i);
if (i.innerHTML !== trash) throw new Error('the trash does not come back after deleting');
console.log('  ok    icon form: the check mark replaces the trash, then back');

// The width is set on the longer of the two labels.
if (!text.includes('min-width')) throw new Error('the text form can change width');
if (iconForm.includes('min-width')) throw new Error('the icon does not need widening');
console.log('  ok    text form: one width, two labels');

/* A real click, in the browser's order: capture, then the inline onclick,
   then the bubbling. The target is a node inside the button, like an icon's
   <svg>: arming replaces the content, so that node is detached afterwards and
   no longer finds its button. That is what disarmed the button on its own
   first click, and made deleting by icon impossible. */
function click(button) {
  const before = button.innerHTML;
  const target = {closest: () => (button.innerHTML === before ? button : null)};
  listeners.capture.forEach(fn => fn({target}));
  const deletes = armDelete(button);
  listeners.bubble.forEach(fn => fn({target}));
  return deletes;
}

const real = button(iconForm);
if (click(real) !== false) throw new Error('the first click deletes');
if (!real.armed()) throw new Error('the button disarms on its own first click');
if (click(real) !== true) throw new Error('the second click does not delete');
console.log('  ok    two real clicks on an icon do delete');

// Another button, a click elsewhere, or the delay: the button disarms.
const a = button(text), c = button(text);
armDelete(a); armDelete(c);
if (a.armed()) throw new Error('two buttons armed at once');
armDelete(a);
listeners.capture.concat(listeners.bubble).forEach(fn => fn({target: {closest: () => null}}));
if (a.armed()) throw new Error('a click elsewhere leaves the button armed');
armDelete(a);
timers.pop()();
if (a.armed()) throw new Error('the button stays armed forever');
console.log('  ok    disarmed by another button, a click elsewhere, or the delay');
