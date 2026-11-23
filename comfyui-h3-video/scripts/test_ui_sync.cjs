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
  if (Number.isInteger(body.base) && body.base !== server[body.part + '_rev'])
    return {status: 409, body: {conflict: true, rev: server[body.part + '_rev'], value: server[body.part]}};
  server.posts.push(body.part);
  server[body.part] = JSON.parse(JSON.stringify(body.value));
  server[body.part + '_rev'] += 1;
  return {status: 200, body: {rev: server[body.part + '_rev']}};
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
      if (options?.method === 'POST') { const out = serverPost(JSON.parse(options.body)); return {ok: out.status === 200, status: out.status, json: async () => out.body}; }
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
  await wait(1000);   // 둘 다 올라가면 나중에 고친 B 가 기준이고(거절된 B 는 합쳐서 다시 올림), A 도 그걸 따라간다
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

  // 6) 뒤에 숨어 있던 창(B)은 예전 상태인 채로 길이만 고쳐 올린다 → 서버가 거절하고, B는 A의 요약 위에 자기 길이만 얹어 다시 올린다
  A.$('summary').value = 'newest from A'; A.run('save()'); await wait(450);
  assert.equal(server.form.f.summary, 'newest from A');
  B.$('duration').value = '9'; B.run('save()'); await wait(900);
  assert.equal(server.form.f.summary, 'newest from A', 'A stale window must not overwrite a newer field');
  assert.equal(server.form.f.duration, '9', 'the stale window keeps its own change');
  assert.equal(B.$('summary').value, 'newest from A', 'the stale window shows the merged state');

  // A delayed conflict response must preserve input typed after the request began.
  const D=makeWindow({summary:'base',anchor:true,images:[]});await D.run('initSync()');
  A.$('summary').value='remote changed';A.run('save()');await wait(450);
  let releaseConflict,held=false;
  D.fetch=async(url,options)=>{
    if(options?.method==='POST'){
      const out=serverPost(JSON.parse(options.body));
      if(!held){held=true;await new Promise(ok=>releaseConflict=ok);}
      return {ok:out.status===200,status:out.status,json:async()=>out.body};
    }
    return {ok:true,json:async()=>serverGet(url)};
  };
  D.$('duration').value='11';D.run('save()');await wait(450);assert(held);
  D.$('summary').value='input typed during POST';D.run('save()');releaseConflict();await wait(900);
  assert.equal(D.$('summary').value,'input typed during POST');
  assert.equal(server.form.f.summary,'input typed during POST');assert.equal(server.form.f.duration,'11');

  // Even if the debounce expires, one part may have only one POST in flight.
  let releaseSuccess,calls=0,active=0,maxActive=0;
  D.fetch=async(url,options)=>{
    if(options?.method==='POST'){
      calls++;active++;maxActive=Math.max(maxActive,active);
      const out=serverPost(JSON.parse(options.body));
      if(calls===1)await new Promise(ok=>releaseSuccess=ok);
      active--;return {ok:out.status===200,status:out.status,json:async()=>out.body};
    }
    return {ok:true,json:async()=>serverGet(url)};
  };
  D.$('summary').value='first in-flight value';D.run('save()');await wait(450);
  D.$('summary').value='latest in-flight value';D.run('save()');await wait(450);
  assert.equal(calls,1);releaseSuccess();await wait(500);
  assert.equal(calls,2);assert.equal(maxActive,1);assert.equal(server.form.f.summary,'latest in-flight value');

  // A response arriving in the queue editor updates the saved pre-edit screen only.
  const F=makeWindow({summary:'initial',anchor:true,images:[]});await F.run('initSync()');
  A.$('summary').value='remote while editor opens';A.run('save()');await wait(900);
  let releaseEditorResponse,editorHeld=false;
  F.fetch=async(url,options)=>{
    if(options?.method==='POST'){
      const out=serverPost(JSON.parse(options.body));
      if(!editorHeld){editorHeld=true;await new Promise(ok=>releaseEditorResponse=ok);}
      return {ok:out.status===200,status:out.status,json:async()=>out.body};
    }
    return {ok:true,json:async()=>serverGet(url)};
  };
  F.$('duration').value='13';F.run('save()');await wait(450);
  await F.run("loadForQueueEdit({summary:'queue-only form'},()=>{editingJobId='queue-only'})");
  releaseEditorResponse();await wait(20);
  assert.equal(F.$('summary').value,'queue-only form');assert.equal(F.$('duration').value,'15');
  F.run('editingJobId=null;restoreBeforeEdit()');await wait(900);
  assert.equal(F.$('summary').value,'remote while editor opens');assert.equal(F.$('duration').value,'13');
  assert.equal(server.form.f.summary,'remote while editor opens');assert.equal(server.form.f.duration,'13');

  // Only the newest edit-load owns the snapshot; a superseded failure cannot restore it.
  const E=makeWindow({summary:'pre-edit screen',anchor:true,images:[]});const pending={};
  E.loadFromHist=entry=>new Promise(ok=>pending[entry.id]=ok);
  const oldEdit=E.run("loadForQueueEdit({id:'old'},()=>{editingJobId='old'})");
  const newEdit=E.run("loadForQueueEdit({id:'new'},()=>{editingJobId='new'})");
  E.$('summary').value='new edit form';pending.new(true);await newEdit;pending.old(false);await oldEdit;
  assert.equal(E.editingJobId,'new');assert.equal(E.$('summary').value,'new edit form');
  E.run('editingJobId=null;restoreBeforeEdit()');assert.equal(E.$('summary').value,'pre-edit screen');

  // Exiting edit mode must invalidate a history read that has not applied its images yet.
  E.run('let loadSeq=0');let finishRead;
  E.loadFromHist=()=>{const token=E.run('++loadSeq');return new Promise(ok=>finishRead=()=>{
    if(token!==E.run('loadSeq'))return ok(false);E.$('summary').value='cancelled late read';ok(true);
  });};
  const cancelled=E.run("loadForQueueEdit({id:'cancelled'},()=>{editingJobId='cancelled'})");
  E.run('restoreBeforeEdit()');finishRead();await cancelled;
  assert.equal(E.editingJobId,null);assert.equal(E.$('summary').value,'pre-edit screen');

  // 한 번에 하나만 받는다: 느린 응답(사진이 실린 수 MB) 중에 온 요청은 겹쳐 보내지 않고, 끝난 뒤 한 번만 다시 받는다
  const G=makeWindow({summary:'g',anchor:true,images:[]});await G.run('initSync()');
  let gets=0,activeGets=0,maxGets=0,releaseGet;const getUrls=[];
  G.fetch=async(url,options)=>{
    if(options?.method==='POST'){const out=serverPost(JSON.parse(options.body));return {ok:out.status===200,status:out.status,json:async()=>out.body};}
    gets++;activeGets++;maxGets=Math.max(maxGets,activeGets);getUrls.push(url);
    const body=serverGet(url);
    if(gets===1)await new Promise(ok=>releaseGet=ok);
    activeGets--;return {ok:true,json:async()=>body};
  };
  const firstPull=G.run('pullSync()');G.run('pullSync()');G.run('pullSync()');G.run('pullSync(true)');await wait(10);
  assert.equal(gets,1,'Pulls must not overlap');
  releaseGet();await firstPull;await wait(20);
  assert.equal(gets,2,'Requests made meanwhile collapse into one follow-up');assert.equal(maxGets,1);
  assert(getUrls[1].includes('form=-1')&&getUrls[1].includes('images=-1'),'A queued full pull stays a full pull');
  await G.run('pullSync()');assert.equal(gets,3,'Later pulls work normally');

  // 전체 받기(수정 모드를 나올 때)는 받을 수 있을 때까지 기억한다: 응답이 올 때 이 창이 바빠도 사라지지 않는다
  const K=makeWindow({summary:'k',anchor:true,images:[]});await K.run('initSync()');
  const kUrls=[];let releaseK,kHeld=false;
  K.fetch=async(url,options)=>{
    if(options?.method==='POST'){const out=serverPost(JSON.parse(options.body));return {ok:out.status===200,status:out.status,json:async()=>out.body};}
    kUrls.push(url);const body=serverGet(url);
    if(!kHeld){kHeld=true;await new Promise(ok=>releaseK=ok);}
    return {ok:true,json:async()=>body};
  };
  const kFirst=K.run('pullSync()');await wait(5);
  K.run('pullSync(true)');K.run('SYNC.dirty.images=true');     // 받는 중에 전체 받기 요청, 응답이 올 때는 이 창이 바쁨
  releaseK();await kFirst;await wait(10);
  assert.equal(kUrls.length,1,'A busy window does not start the follow-up yet');
  K.run('SYNC.dirty.images=false');await K.run('pullSync()');
  assert(kUrls[1].includes('form=-1')&&kUrls[1].includes('images=-1'),'The remembered full refresh runs once the window is free');
  await K.run('pullSync()');assert(!kUrls[2].includes('form=-1'),'and it runs only once');

  // 낡은 응답: 요청을 보낸 뒤 이 창이 올린 내용을, 늦게 도착한 예전 내용으로 되돌리지 않는다
  const H=makeWindow({summary:'h',anchor:true,images:[]});await H.run('initSync()');
  A.$('summary').value='remote before H edits';A.run('save()');await wait(450);
  let releaseStale,stalled=false;
  H.fetch=async(url,options)=>{
    if(options?.method==='POST'){const out=serverPost(JSON.parse(options.body));return {ok:out.status===200,status:out.status,json:async()=>out.body};}
    const body=serverGet(url);                         // 응답 내용은 이 창이 올리기 전 시점의 것
    if(!stalled){stalled=true;await new Promise(ok=>releaseStale=ok);}
    return {ok:true,json:async()=>body};
  };
  const stalePull=H.run('pullSync()');await wait(10);assert(stalled);
  H.$('duration').value='12';H.run('save()');await wait(1300);     // 충돌 → 최신 위에 이 창의 길이만 얹어 다시 올림
  assert.equal(server.form.f.duration,'12');assert.equal(server.form.f.summary,'remote before H edits');
  const pushedRev=H.run('SYNC.rev.form');assert.equal(pushedRev,server.form_rev);
  releaseStale();await stalePull;await wait(20);
  assert.equal(H.$('duration').value,'12','A late answer must not revert an edit this window already pushed');
  assert.equal(H.run('SYNC.rev.form'),pushedRev,'A late answer must not move the revision backwards');
  assert.equal(H.$('summary').value,'remote before H edits');

  console.log('UI sync passed: shared state, stale-field merge, delayed-response input preservation, serialized writes, single in-flight pulls, stale-answer rejection and edit-load ownership/cancellation.');
})().catch(error => { console.error(error); process.exit(1); });
