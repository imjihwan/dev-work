// Isolated sync checks: two fake windows share an in-memory fake server; never connects to the app.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(process.argv[2] || path.join(__dirname, '../simple_ui/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const section = (start, end) => script.slice(script.indexOf(start), script.indexOf(end, script.indexOf(start)));
const wait = ms => new Promise(ok => setTimeout(ok, ms));

// 서버 /api/ui-state 와 같은 규칙: 부분마다 rev, 창이 가진 rev 와 다르면 내용을 싣는다
const server = {form: null, images: null, form_rev: 0, images_rev: 0, posts: []};
function serverGet(url){
  const q = new URL(url, 'http://x').searchParams, out = {};
  for (const part of ['form', 'images']) {
    out[part + '_rev'] = server[part + '_rev'];
    if (Number(q.get(part)) !== server[part + '_rev']) out[part] = server[part];
  }
  return out;
}
function serverPost(body){
  server.posts.push(body.part);
  server[body.part] = JSON.parse(JSON.stringify(body.value));
  server[body.part + '_rev'] += 1;
  return {rev: server[body.part + '_rev']};
}

function makeWindow(initial){
  const elements = new Map();
  const $ = id => {
    if (!elements.has(id)) elements.set(id, {value:'', hidden:true, textContent:'', children:[]});
    return elements.get(id);
  };
  const setShots = shots => { $('shots').children = shots.map(([t, x]) => {
    const input = {value: String(t)}, area = {value: x};
    return {querySelector: s => s === 'input' ? input : area};
  }); };
  const listeners = {};
  const context = vm.createContext({$, console, setTimeout, clearTimeout, setInterval: () => 0, JSON, Object, Number, String,
    FIELDS: ['summary', 'duration'], images: [...initial.images], imgsReady: true, manualFinal: false, CAT: null,
    S: {mode: 'REF2VA', model: 'm', anchor: initial.anchor, loras: {}},
    editingJobId: null, bulkEditingIds: [],
    maxImgs: () => 9, setMode: () => {}, drawModelCard: () => {}, render: () => context.save(), drawThumbs: () => context.saveImgs(),
    apply: s => { for (const [k, v] of Object.entries(s.f || {})) $(k).value = v; setShots(s.shots || []); },
    document: {hidden: false, addEventListener: (type, fn) => { listeners[type] = fn; }},
    window: {addEventListener: () => {}},
    loadFromHist: async entry => { $('summary').value = entry.summary; $('duration').value = '15'; context.S.anchor = false; context.render(); return true; },
    fetch: async (url, options) => {
      if (options?.method === 'POST') { const body = JSON.parse(options.body); return {ok: true, json: async () => serverPost(body)}; }
      return {ok: true, json: async () => serverGet(url)};
    }});
  $('summary').value = initial.summary; $('duration').value = '7'; $('seed').value = ''; setShots([[0, 'scene']]);
  vm.runInContext(section('function captureSettings()', '$("settingsSave").onclick'), context);
  vm.runInContext('function save(){ pushSync("form"); } function saveImgs(){ pushSync("images"); }', context);
  context.run = code => vm.runInContext(code, context);
  return context;
}

(async () => {
  // 1) 처음 쓰는 서버: 먼저 연 창의 상태를 기준으로 올린다
  const A = makeWindow({summary: 'window A', anchor: true, images: ['data:image/png;base64,AAA']});
  await A.run('initSync()'); await wait(450);
  assert.deepEqual(server.posts.sort(), ['form', 'images']);
  assert.equal(server.form.f.summary, 'window A'); assert.equal(server.form.model.anchor, true);
  assert.deepEqual(server.images, ['data:image/png;base64,AAA']);

  // 2) 나중에 연 창은 자기 브라우저에 남은 예전 값이 아니라 서버 상태로 시작하고, 그 값을 다시 올리지 않는다
  server.posts.length = 0;
  const B = makeWindow({summary: 'stale B', anchor: false, images: []});
  await B.run('initSync()'); await wait(450);
  assert.equal(B.$('summary').value, 'window A'); assert.equal(B.S.anchor, true);
  assert.deepEqual([...B.images], ['data:image/png;base64,AAA']);
  assert.deepEqual(server.posts, [], 'Applying the shared state must not echo it back');

  // 3) B 에서 고치면 A 가 따라간다
  B.$('summary').value = 'edited in B'; B.run('save()'); await wait(450);
  assert.equal(server.form.f.summary, 'edited in B');
  await A.run('pullSync()');
  assert.equal(A.$('summary').value, 'edited in B');

  // 4) 이 창에서 고친 게 아직 안 올라갔으면 다른 창 값으로 덮지 않는다
  A.$('summary').value = 'typing in A'; A.run('save()');
  B.$('summary').value = 'edited in B again'; B.run('save()'); await wait(10);
  await A.run('pullSync()');
  assert.equal(A.$('summary').value, 'typing in A', 'A pending local edit wins over a pull');
  await wait(450);   // 둘 다 올라가면 나중에 고친 B 가 기준이고, A 도 그걸 따라간다
  assert.equal(server.form.f.summary, 'edited in B again');
  await A.run('pullSync()'); assert.equal(A.$('summary').value, 'edited in B again');
  A.$('summary').value = 'typing in A'; A.run('save()'); await wait(450);
  await B.run('pullSync()'); assert.equal(B.$('summary').value, 'typing in A');

  // 5) 대기항목 수정 모드: 불러온 항목(15초·고정 꺼짐)은 올리지 않고, 나오면 들어가기 전 화면으로 돌아간다
  server.posts.length = 0;
  const entered = await A.run(`loadForQueueEdit({summary:'queued item'}, () => { editingJobId = 'job1'; })`);
  assert.equal(entered, true); assert.equal(A.$('summary').value, 'queued item'); assert.equal(A.S.anchor, false);
  await wait(450);
  assert.deepEqual(server.posts, [], 'A queue item loaded for editing never reaches the shared state');
  assert.equal(server.form.f.duration, '7'); assert.equal(server.form.model.anchor, true);
  A.run('editingJobId = null; restoreBeforeEdit()'); await wait(10);
  assert.equal(A.$('summary').value, 'typing in A'); assert.equal(A.$('duration').value, '7'); assert.equal(A.S.anchor, true);
  await wait(450);
  assert.deepEqual(server.posts, [], 'Restoring the pre-edit screen does not create a new shared revision');

  console.log('UI sync passed: first window seeds the server, later windows adopt it without echo, edits propagate, local pending edits win, queue-edit loads stay local and are restored.');
})().catch(error => { console.error(error); process.exit(1); });
