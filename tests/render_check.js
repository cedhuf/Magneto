const base = {
  url: 'https://www.youtube.com/watch?v=x', title: 'A title', uploader: 'Channel',
  duration: 213, upload_date: '20260101', description: 'A description',
  thumbnail: 'https://i.ytimg.com/vi/x/hqdefault.jpg', jobId: 'abc1234567',
  formats: [{id: '137', label: '1080p', height: 1080, size: 1e8, compatible: true},
            {id: '136', label: '720p', height: 720, size: 5e7, compatible: true},
            {id: '400', label: '1440p', height: 1440, size: 2e8, compatible: false}],
  selectedFormatId: '137', filename: 'A title.mp4', deleteAt: Date.now() + 3600000,
};
const states = ['ready', 'downloading', 'done', 'error', 'gone', 'loading', 'info-error'];
let failures = 0;
states.forEach(function (status, i) {
  cardData[i] = Object.assign({}, base, {status: status, zone: 'work'});
  try {
    renderCard(i);
    const el = document.getElementById('card-' + i);
    const out = el.outerHTML || el.innerHTML;
    if (!out || out.indexOf('card') === -1) throw new Error('empty render');
    console.log('  ok    ' + status + ' -> ' + out.length + ' caracteres');
  } catch (e) {
    failures++;
    console.log('  FAIL ' + status + ' -> ' + e.message);
  }
});
// The functions the templates call through onclick must exist.
['dlCard', 'saveCard', 'playCard', 'pickFormat', 'showAllFormats', 'toggleDesc',
 'togglePin', 'removeCard', 'openPlayer', 'go', 'setFormat', 'showAllSites',
 'cycleTheme'].forEach(function (fn) {
  if (typeof eval(fn) !== 'function') { failures++; console.log('  FAIL ' + fn + ' absente'); }
});
if (failures) throw new Error(failures + ' probleme(s)');

// Every resolution chip carries a size.
cardData[99] = Object.assign({}, base, {status: 'ready', zone: 'work'});
renderCard(99);
const chips = document.getElementById('card-99').outerHTML;
const sizes = (chips.match(/q-size/g) || []).length;
if (sizes < 2) throw new Error('chips without a size: ' + sizes + ' q-size found');
console.log('  ok    ' + sizes + ' chips carry a size');

// The home and the feed open the same player, on the server's file.
openPlayer(Object.assign({}, base, {status: 'done', jobId: 'job123'}));
const shell = document.body.children.slice(-1)[0].innerHTML;
if (!shell.includes('/api/stream/job123')) throw new Error('lecteur home casse');
if (!shell.includes('Channel')) throw new Error('meta missing from the home player');
console.log('  ok    the home player opens the server file');

// The right-hand frame: the action on top, the icons below.
cardData[98] = Object.assign({}, base, {status: 'done', zone: 'history'});
renderCard(98);
const side = document.getElementById('card-98').outerHTML.split('card-side')[1] || '';
if (side.indexOf('card-dl-btn') > side.indexOf('card-icons'))
  throw new Error('the icons come before the action');
if (!side.includes('icon-tabler') && !side.includes('<svg class="icon"'))
  throw new Error('the icons do not come from the library');
console.log('  ok    right-hand frame: action on top, pin and delete below');
