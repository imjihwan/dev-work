// Exercise the real general-mode scene handlers, prompt builder and submit payload.
// Synthetic text and mocked fetch only: no live jobs or personal media.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const source=html.match(/<script>([\s\S]*)<\/script>/)[1],nodes=new Map();
class Element{
  constructor(){this.value='';this.children=[];this.parts=new Map();this.events={};this.style={};this.hidden=false;this.classList={toggle(){}};}
  querySelector(selector){if(!this.parts.has(selector))this.parts.set(selector,new Element());return this.parts.get(selector);}
  querySelectorAll(){return [];}
  appendChild(child){child.parentElement=this;this.children.push(child);}
  remove(){this.parentElement.children=this.parentElement.children.filter(child=>child!==this);}
  addEventListener(type,fn){(this.events[type]||=[]).push(fn);}
}
const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
const fields=['subject','summary','style','keep','sound','music','aspect','resolution','duration','count'];
const requests=[];
let context;
context=vm.createContext({console,$:get,FIELDS:fields,images:['synthetic-reference'],manualFinal:false,CAT:null,
  S:{model:'synthetic-model',steps:4,sampler:'euler',scheduler:'simple',shift_video:5,shift_audio:5,oneTake:true,trig:false,loras:{}},
  isRef:()=>true,sendMode:()=> 'REF2VA',document:{createElement:()=>new Element()},
  drawGoInfo(){},drawSpeed(){},save(){},updateSequenceButton(){},updateGoLabel(){},setQueueEdit(){},loadHist(){},setStatus(){},
  queueSubmitting:false,editingJobId:null,bulkEditingIds:[],bulkAllEditing:false,currentJobs:[],pollT0:0,imgsReady:true,manualFinalBackup:null,
  runCount:()=>1,curModel:()=>null,histModelName:value=>value,esc:value=>String(value),finished:job=>job.state==='done',
  poll:jobs=>context.currentJobs=jobs,
  fetch:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return{ok:true,json:async()=>({jobs:[{id:'synthetic-new',seed:42,width:640,height:384,model:'synthetic-model',steps:4}],width:640,height:384,model:'synthetic-model',steps:4})};}});
for(const [id,value] of Object.entries({summary:'A synthetic motion.',style:'Fixed camera.',keep:'Keep original appearance.',sound:'Quiet room tone.',music:'N/A',aspect:'auto',resolution:'draft',duration:'5',count:'1',seed:'42'}))get(id).value=value;
vm.runInContext(source.slice(source.indexOf('function addShot('),source.indexOf('// 3. 모델')),context);
vm.runInContext(source.slice(source.indexOf('function captureSettings('),source.indexOf('$("settingsSave").onclick')),context);
vm.runInContext(source.slice(source.indexOf('async function submitJobs('),source.indexOf('$("go").onclick')),context);
const directFinal=text=>{get('final').value=text;get('final').oninput();assert.equal(context.manualFinal,true);};
(async()=>{
  context.addShot(0,'Previous synthetic movement.');context.render();assert(get('final').value.includes('Previous synthetic movement.'));
  assert(get('final').value.includes('one uninterrupted camera take'));
  assert(!get('final').value.includes('viewpoint, position and framing established at the start of this video stable throughout'));
  assert(!get('final').value.includes('camera position and framing stay exactly the same as in <Picture 1>'));
  assert.equal(get('keep').value,'Keep original appearance.','The generated continuity rule must not overwrite saved retention text');
  const originalStyle=get('style').value;
  get('style').value='From 0.3 to 1.0 seconds, use a continuous zoom-out; then hold this framing.';
  get('keep').value='Keep original appearance. No cuts.';
  const movingTake=context.build();
  assert(movingTake.includes(get('style').value),'A requested initial zoom must remain intact');
  assert(movingTake.includes('Follow only the camera movement explicitly specified in the camera instructions.'));
  assert(movingTake.includes('one uninterrupted camera take'),'A short no-cuts rule must not suppress full continuity guidance');
  assert.equal(get('keep').value,'Keep original appearance. No cuts.');
  context.addShot(2,'Continue the same synthetic motion.');
  get('shots').children.at(-1).querySelector('input').value='2';
  assert(!/\[Shot [2-9]\]/.test(context.build()),'Timed beats in one take must not become cut markers');
  context.S.oneTake=false;
  assert(context.build().includes('[Shot 2] At 00:02.000'));
  assert(!context.build().includes('one uninterrupted camera take'),'Explicit multi-shot mode must remain available');
  context.S.oneTake=true;get('shots').children.pop();
  get('style').value=originalStyle;get('keep').value='Keep original appearance.';
  context.images.push('another-synthetic-reference');assert(context.build().includes('<Picture 2>'));assert(!context.build(1).includes('<Picture 2>'));context.images.pop();
  directFinal('A preserved custom final prompt.');context.render();assert.equal(get('final').value,'A preserved custom final prompt.');
  const first=get('shots').children[0];first.querySelector('textarea').value='Updated synthetic movement.';first.oninput();
  assert.equal(context.manualFinal,false);assert(get('final').value.includes('Updated synthetic movement.'));assert(!get('final').value.includes('Previous synthetic movement.'));assert(!get('final').value.includes('preserved custom'));
  assert.equal(get('resetFinal').hidden,true);
  context.addShot(2,'Second synthetic movement.');
  directFinal('Another custom prompt.');const second=get('shots').children[1];second.querySelector('input').value='3';second.oninput();
  assert(get('final').value.includes('00:03.000'));assert(get('final').value.toLowerCase().includes('second synthetic movement.'));
  directFinal('Custom before deletion.');second.querySelector('button').onclick();assert.equal(context.manualFinal,false);assert(!get('final').value.toLowerCase().includes('second synthetic movement.'));
  directFinal('Custom before adding a scene.');get('addShot').onclick();assert.equal(context.manualFinal,false);
  directFinal('Custom before editing the summary.');get('summary').value='Updated synthetic summary.';get('summary').events.input[0]();assert.equal(context.manualFinal,false);assert(get('final').value.includes('Updated synthetic summary.'));
  directFinal('Keep this manual prompt for a count-only change.');get('count').value='4';get('count').events.input[0]();assert.equal(get('final').value,'Keep this manual prompt for a count-only change.');
  first.querySelector('textarea').value='Movement submitted to the backend.';context.manualFinal=false;get('final').value='Stale generated preview.';
  await context.submitJobs();
  assert.equal(requests.length,1);assert.equal(requests[0].url,'/api/generate');assert(requests[0].body.prompt.includes('Movement submitted to the backend.'));assert(!requests[0].body.prompt.includes('Stale generated preview.'));
  assert.equal(requests[0].body.prompt,get('final').value);assert.equal(context.currentJobs[0].id,'synthetic-new');
  // A restored manual prompt must not hide changed form values if a browser/input
  // integration changes .value without delivering a bubbling input event.
  directFinal('Previous synthetic final prompt.');
  first.querySelector('textarea').value='New bulk synthetic action without an input event.';
  context.bulkEditingIds=['waiting-fixture'];context.bulkAllEditing=true;
  get('bulkFields').querySelectorAll=()=>[{value:'content'}];
  await context.submitJobs();
  assert(requests.at(-1).body.prompt.includes('New bulk synthetic action without an input event.'));
  assert(!requests.at(-1).body.prompt.includes('Previous synthetic final prompt.'));
  assert.equal(requests.at(-1).body.all_pending,true);
  // An explicit final edit made after the form change remains authoritative.
  first.querySelector('textarea').value='Another synthetic form action.';directFinal('Explicit synthetic final after form editing.');
  await context.submitJobs();assert.equal(requests.at(-1).body.prompt,'Explicit synthetic final after form editing.');
  context.bulkEditingIds=[];context.bulkAllEditing=false;
  first.querySelector('textarea').value='Movement submitted to the backend.';context.manualFinal=false;context.render();
  const commonStyle=JSON.parse(source.match(/^const REFERENCE_STYLE_CURRENT = (.*);$/m)[1]);
  context.REFERENCE_STYLE_CURRENT=commonStyle;
  assert(!context.build().includes('Replace the reference pelvis'),'Removed experimental pose rules must stay removed');
  get('style').value=commonStyle;context.S.anchor=true;get('subject').value='';
  for(const n of [1,3]){
    const prompt=context.build(n);
    assert(prompt.startsWith('subject_definitions: <Picture 1>'));
    assert(prompt.includes('background from <Picture 1>'));
    assert(!prompt.includes('Replace the reference pelvis and leg facing direction'));
    assert(prompt.includes('Movement submitted to the backend.'));
    assert.equal(prompt.includes('<Picture 2>'),n>1);
  }
  get('subject').value='A custom subject from <Picture 1>.';
  assert(context.build().startsWith('subject_definitions: A custom subject from <Picture 1>.'));
  const nine=context.build(9);
  for(let i=2;i<=9;i++)assert(nine.includes(`<Picture ${i}>`),'A custom Picture 1 description must not suppress extra face references');
  assert(nine.includes('one consistent facial identity'));
  assert(nine.includes(commonStyle),'Existing camera/lower-body instructions must remain intact');
  context.images.push(...Array.from({length:8},(_,i)=>`synthetic-face-${i}`));
  const manual='subject_definitions: Custom subject from <Picture 1>.\n\nsummary: Preserve exact summary.\n\nretention_analysis: Custom accessories.\n\ndetailed_description: At 1.5 seconds, retain this exact motion.\n\noverall_soundscape: Keep custom sound.';
  directFinal(manual);context.render();assert.equal(get('final').value,manual);assert(!get('refreshFaceRefs').hidden);
  get('refreshFaceRefs').onclick();const refreshed=get('final').value;
  assert(refreshed.includes('<Picture 9>'));assert.equal(context.stripFaceReferenceRules(refreshed),manual);assert.equal(context.manualFinal,true);
  get('refreshFaceRefs').onclick();assert.equal(get('final').value,refreshed);
  context.images.splice(1);context.render();assert(!get('refreshFaceRefs').hidden);get('refreshFaceRefs').onclick();assert.equal(get('final').value,manual);
  assert.equal(get('keep').value,'Keep original appearance.');
  context.images.push('synthetic-second');
  const originalFetch=context.fetch,beforeRequests=requests.length,statusMessages=[];
  context.setStatus=message=>statusMessages.push(message);
  context.fetch=async(url,options)=>url==='/api/health'?{ok:false}:originalFetch(url,options);
  context.S.faceBoost=true;  // 얼굴인식강화를 켰을 때만 크롭(=서버 버전 확인)이 필요하다
  await context.submitJobs(true);
  assert.equal(requests.length,beforeRequests,'An old server must not silently queue uncropped references');
  assert(statusMessages.some(message=>message.includes('Restart-H3-UI.ps1')));
  context.fetch=async(url,options)=>url==='/api/health'?{ok:true,json:async()=>({sequence_face_crop:true})}:originalFetch(url,options);
  await context.submitJobs(true);
  assert.equal(requests.length,beforeRequests+1);
  assert.equal(requests.at(-1).body.photo_sequence,true);
  // Priority button: mocked network, existing running work and queued work only.
  vm.runInContext(source.slice(source.indexOf('function updateSequenceButton(){'),source.indexOf('function updateGoLabel(){')),context);
  vm.runInContext(source.slice(source.indexOf('$("go").onclick ='),source.indexOf('let photoBatchStop=')),context);
  context.CAT={capabilities:{priority_queue:true,photo_sequence:true}};
  context.S.faceBoost=false;context.images.splice(1);get('count').value='3';context.runCount=()=>Number(get('count').value);
  context.manualFinal=false;get('shots').children[0].querySelector('textarea').value='Synthetic priority movement.';get('final').value='Stale synthetic priority preview.';
  context.currentJobs=[{id:'running',state:'running'},{id:'waiting',state:'queued'}];
  context.updateSequenceButton();assert.equal(get('priorityGo').disabled,false);
  let releasePriority;
  context.fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return await new Promise(resolve=>{releasePriority=resolve;});};
  const priorityRequestCount=requests.length,priorityPending=get('priorityGo').onclick();
  assert.equal(get('priorityGo').disabled,true);assert.equal(context.queueSubmitting,true);
  await get('priorityGo').onclick();assert.equal(requests.length,priorityRequestCount+1,'Repeated clicks must not queue duplicate priority requests');
  assert.equal(requests.at(-1).url,'/api/generate/priority');assert.equal(requests.at(-1).body.count,3);
  assert(requests.at(-1).body.prompt.includes('Synthetic priority movement.'));assert(!requests.at(-1).body.prompt.includes('Stale synthetic priority preview.'));
  releasePriority({ok:true,json:async()=>({jobs:[{id:'priority-a',seed:42},{id:'priority-b',seed:43},{id:'priority-c',seed:44}],width:640,height:384,steps:4,model:'synthetic-model'})});
  await priorityPending;
  assert.deepEqual(Array.from(context.currentJobs,j=>j.id),['running','priority-a','priority-b','priority-c','waiting']);
  assert(get('queueFeedback').textContent.includes('대기열 맨 앞'));assert.equal(get('priorityGo').disabled,false);
  context.editingJobId='waiting';context.updateSequenceButton();assert(get('priorityGo').hidden);assert(get('priorityGo').disabled);
  const beforePriorityEdit=requests.length;await context.submitJobs(false,true);assert.equal(requests.length,beforePriorityEdit);
  context.editingJobId=null;context.bulkEditingIds=['waiting'];await context.submitJobs(false,true);assert.equal(requests.length,beforePriorityEdit);
  context.bulkEditingIds=[];await context.submitJobs(true,true);assert.equal(requests.length,beforePriorityEdit);
  context.updateSequenceButton();assert.equal(get('priorityGo').hidden,false);
  context.fetch=async()=>{throw new Error('synthetic failure');};await get('priorityGo').onclick();assert.equal(context.queueSubmitting,false);assert.equal(get('priorityGo').disabled,false);
  context.fetch=async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return{ok:true,json:async()=>({jobs:[{id:'normal-after-priority',seed:45}],width:640,height:384,steps:4,model:'synthetic-model'})};};
  await get('go').onclick();assert.equal(requests.at(-1).url,'/api/generate','Normal add must remain a separate normal-priority action');
  console.log('General-mode prompt sync and priority add passed: fresh prompt, guarded priority route, repeat order, existing running job, double-click prevention, edit rejection and failure recovery.');
})().catch(error=>{console.error(error);process.exitCode=1;});
