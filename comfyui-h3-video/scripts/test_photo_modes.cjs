// Photo list across mode switches. Fake DOM and fake browser storage only; never connects to the app or reads photos.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict'), path = require('node:path');
const html = fs.readFileSync(process.argv[2] || path.join(__dirname, '../simple_ui/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const section = (start, end) => script.slice(script.indexOf(start), script.indexOf(end, script.indexOf(start)));
const elements = new Map();
const $ = id => { if (!elements.has(id)) elements.set(id, {hidden:false, checked:false, textContent:'', innerHTML:'', value:''}); return elements.get(id); };
const store = new Map(), pushed = [];
const context = vm.createContext({$, console, images:[], S:{mode:'REF2VA', anchor:true, oneTake:true, faceBoost:false}, CAT:null,
  document:{querySelectorAll:() => []}, drawThumbs(){ context.drawn = [...context.images]; }, drawModelCard(){},
  IDB:{get:async key => store.get(key), set:async (key, value) => { store.set(key, value); }}, pushSync:part => pushed.push(part)});
vm.runInContext(section('const isRef = ', '// ---------- 사진'), context);
vm.runInContext(section('let imgsReady = false;', 'let photoImportQueue'), context);
const mode = name => vm.runInContext(`setMode(${JSON.stringify(name)})`, context);
const list = () => [...context.images], hidden = () => [...(context.images.hidden || [])];

(async () => {
  // First/last-frame mode takes two photos. Looking at it (or picking a model set made for it) used to delete photos 3-9 for good.
  context.images.push('a', 'b', 'c', 'd', 'e');
  mode('FL2VA');
  assert.deepEqual(list(), ['a', 'b']); assert.deepEqual(hidden(), ['c', 'd', 'e'], 'the rest is kept aside, not deleted');
  mode('FL2VA'); assert.deepEqual(hidden(), ['c', 'd', 'e'], 'choosing the same mode again changes nothing');
  mode('REF2VA');
  assert.deepEqual(list(), ['a', 'b', 'c', 'd', 'e'], 'back in reference mode the photos return in their order'); assert.deepEqual(hidden(), []);
  // Changes made while in the two-photo mode are kept.
  mode('FL2VA'); context.images.splice(1, 1); context.images.push('x');
  mode('REF2VA'); assert.deepEqual(list(), ['a', 'x', 'c', 'd', 'e']);
  // Nine photos stay nine.
  context.images.length = 0; context.images.push(...'123456789');
  mode('FL2VA'); assert.equal(list().length, 2); assert.equal(hidden().length, 7);
  mode('REF2VA'); assert.deepEqual(list(), [...'123456789']);
  mode('FL2VA'); context.images.push('late'); mode('REF2VA');      // cannot happen through the page (two-photo limit), but never exceed nine
  assert.equal(list().length, 9);
  // A mode switch without extra photos is as before.
  context.images.length = 0; context.images.hidden = []; context.images.push('only');
  mode('FL2VA'); mode('REF2VA'); assert.deepEqual(list(), ['only']); assert.deepEqual(hidden(), []);

  // The photos kept aside survive a reload of the page (this browser only) and never enter the visible list that is saved and synchronised.
  context.images.length = 0; context.images.push('a', 'b', 'c', 'd');
  vm.runInContext('imgsReady = true;', context);
  mode('FL2VA'); vm.runInContext('saveImgs()', context); await new Promise(setImmediate);
  assert.deepEqual([...store.get('images')], ['a', 'b']); assert.deepEqual([...store.get('images_hidden')], ['c', 'd']); assert.deepEqual(pushed, ['images']);
  context.images.length = 0; context.images.hidden = [];
  await vm.runInContext('restoreImgs()', context);
  assert.deepEqual(list(), ['a', 'b']); assert.deepEqual(hidden(), ['c', 'd'], 'reloaded in the two-photo mode: still aside');
  mode('REF2VA'); assert.deepEqual(list(), ['a', 'b', 'c', 'd']);
  context.images.length = 0; context.images.hidden = [];
  await vm.runInContext('restoreImgs()', context);      // reloaded in reference mode with photos still marked aside: they are shown
  assert.deepEqual(list(), ['a', 'b', 'c', 'd']); assert.deepEqual(hidden(), []);
  store.delete('images_hidden'); context.images.length = 0;
  await vm.runInContext('restoreImgs()', context); assert.deepEqual(list(), ['a', 'b'], 'storage from before this change has no second list');

  // Replacing the whole photo list (history, saved settings, another window) drops what was kept aside; the hint says where the photos went.
  assert.equal((script.match(/images\.length = 0; images\.hidden = \[\];/g) || []).length, 2, 'history load and snapshot apply');
  assert(script.includes('images.hidden = value.slice(maxImgs());'), 'photos from another window beyond this mode\'s limit are kept aside too');
  assert(script.includes("if (!isRef() && images.hidden?.length) $(\"photoHint\").textContent +="));
  console.log('Photo mode checks passed: switching modes keeps photos 3-9 aside and restores them.');
})().catch(error => { console.error(error); process.exitCode = 1; });
