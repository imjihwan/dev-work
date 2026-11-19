// Gallery checks use fake DOM/video objects and mocked metadata; no browser or private files.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/gallery.html'),'utf8');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1],elements=new Map();let active=null;
class Classes{
  constructor(){this.values=new Set();}
  toggle(value,on){if(on??!this.values.has(value))this.values.add(value);else this.values.delete(value);}
  contains(value){return this.values.has(value);}
}
class Element{
  constructor(id=''){this.id=id;this.tagName='DIV';this.dataset={};this.style={overflow:'',setProperty(name,value){this[name]=String(value);}};this.classList=new Classes();this.children=[];this.parts=[];this.players=[];this.hidden=false;this.open=false;this.value='';this.checked=false;this.disabled=false;this.textContent='';this.attrs={};this.isConnected=true;this.events={};this.parentElement=null;this._html='';this.showCalls=0;this.closeCalls=0;}
  set innerHTML(value){
    this.players.forEach(player=>player.isConnected=false);this._html=value;this.players=[...value.matchAll(/<video\b/g)].map(()=>new Player());this.parts=[];
    for(const match of value.matchAll(/data-pick="([^"]+)"/g)){const input=new Element();input.dataset.pick=match[1];input.closest=()=>this;this.parts.push(input);}
    if(value.includes('<img ')){const image=new Element();image.tag='img';this.parts.push(image);}
  }
  get innerHTML(){return this._html;}
  insertBefore(node,before){if(node.parentElement){const previous=node.parentElement.children;previous.splice(previous.indexOf(node),1);}const index=before?this.children.indexOf(before):-1;this.children.splice(index<0?this.children.length:index,0,node);node.parentElement=this;node.isConnected=true;}
  remove(){if(this.parentElement){const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this),1);}this.isConnected=false;}
  querySelectorAll(selector){if(selector==='video')return this.players;if(selector==='[data-pick]')return this.children.flatMap(node=>node.parts.filter(part=>part.dataset.pick));return [];}
  querySelector(selector){return this.parts.find(part=>part.tag===selector)||null;}
  closest(selector){return selector.split(',').includes(this.tagName.toLowerCase())?this:null;}
  contains(node){return this===node||this.players.includes(node)||this.children.some(child=>child.contains(node));}
  getBoundingClientRect(){const index=this.parentElement?.children.indexOf(this)||0;return {top:index*240,bottom:index*240+220,left:0,right:640};}
  addEventListener(name,fn){this.events[name]=fn;}
  setAttribute(name,value){this.attrs[name]=String(value);}
  removeAttribute(name){delete this.attrs[name];}
  showModal(){this.open=true;this.showCalls++;}
  close(){this.open=false;this.closeCalls++;}
  replaceChildren(){this.players.forEach(player=>player.isConnected=false);this.players=[];this.children=[];this._html='';}
  focus(options){active=this;this.focusOptions=options;}
}
class Player extends Element{
  constructor(){super();this.tagName='VIDEO';this.currentTime=0;this.playCount=0;this.paused=true;this.loads=0;this.muted=false;this.volume=1;this.parentElement=new Element();this.card=new Element();for(const tag of ['.lora-info','.regeneration-control']){const part=new Element();part.tag=tag;this.card.parts.push(part);}}
  closest(selector){return selector==='.player'?this.card:super.closest(selector);}
  getBoundingClientRect(){return {top:0,bottom:220,left:0,right:640};}
  play(){this.playCount++;this.paused=false;return Promise.resolve();}
  pause(){this.paused=true;}
  removeAttribute(){}
  load(){this.loads++;}
}
const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
const filters=['all','favorites','trash'].map(mode=>{const node=new Element();node.dataset.mode=mode;return node;});
const doc={body:new Element('body'),hidden:false,getElementById:get,createElement:()=>new Element(),querySelectorAll:selector=>selector==='[data-mode]'?filters:[],addEventListener(){}};
Object.defineProperty(doc,'activeElement',{get:()=>active});
const calls=[],timers=[];
const window={innerWidth:1024,innerHeight:768,scrollY:0,scrollCalls:0,addEventListener(){},scrollBy(){this.scrollCalls++;},scrollTo(){this.scrollCalls++;}};
const context=vm.createContext({console,document:doc,window,URLSearchParams,location:{origin:'http://synthetic.local'},parent:{},
  setTimeout(fn){timers.push(fn);return timers.length;},clearTimeout(){},localStorage:{getItem:()=>null},
  fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({items:[],total:0,counts:{},revision:'empty'})};}});
vm.runInContext(script.slice(0,script.indexOf('// Bootstrap only')),context);
const run=code=>vm.runInContext(code,context),settle=()=>new Promise(setImmediate);
const loras=Array.from({length:10},(_,index)=>({name:`folder/synthetic_${index}_full_suffix.safetensors`,strength:index===0?0:index/10}));
const entries=Array.from({length:60},(_,index)=>({id:`synthetic-${index}`,created_at:1700000000-index,bytes:2048,width:384,height:512,duration:5,model:'folder/synthetic-model',loras,
  favorite:false,trashed:false,thumbnail:`/api/gallery/thumbnail?id=synthetic-${index}&v=fake`,thumbnail_state:'ready',video:{filename:'synthetic.mp4',subfolder:'video',type:'output'}}));
context.entries=entries;
assert(run('tileHtml(entries[0])').includes('생성에 사용한 첫 번째 원본 이미지'));
assert(run('tileHtml(entries[0])').includes('원본 사진 1'));
assert(run('tileHtml({...entries[0],thumbnail:null,thumbnail_state:"missing"})').includes('원본 이미지 정보 없음'));
assert(run('tileHtml({...entries[0],generation_seconds:3661.2})').includes('생성 1시간 1분 1초'));
assert.equal(run('generationTimeLabel(85.123)'),'생성 1분 25초');assert.equal(run('generationTimeLabel(.25)'),'생성 1초 미만');assert.equal(run('generationTimeLabel(undefined)'),'');
const mainTimingHtml=fs.readFileSync(path.join(__dirname,'../simple_ui/index.html'),'utf8'),mainTiming=vm.createContext({});
vm.runInContext(mainTimingHtml.match(/function generationTimeLabel\(seconds\)\{[\s\S]*?\n\}/)[0],mainTiming);
assert.equal(vm.runInContext('generationTimeLabel(85.123)',mainTiming),'01:25');assert.equal(vm.runInContext('generationTimeLabel(300)',mainTiming),'05:00');assert.equal(vm.runInContext('generationTimeLabel(3661.2)',mainTiming),'61:01');assert.equal(vm.runInContext('generationTimeLabel(.25)',mainTiming),'00:00');assert.equal(vm.runInContext('generationTimeLabel(null)',mainTiming),'');
assert(html.includes('object-fit:contain}.source-label'));
function mockPages(revision='one'){
  context.fetch=async(url,options)=>{calls.push({url,options});const q=new URL(url,'http://synthetic.local').searchParams;const offset=Number(q.get('offset')),limit=Number(q.get('limit'));return {ok:true,json:async()=>({items:q.get('known')===revision?[]:entries.slice(offset,offset+limit),total:entries.length,counts:{all:60,favorites:0,trash:0},revision,unchanged:q.get('known')===revision})};};
}
function touch(type,video,x,y,touches=null){
  const point={identifier:7,clientX:x,clientY:y};
  const event={target:video,touches:touches??(type==='touchend'?[]:[point]),changedTouches:[point],cancelable:true,prevented:false,preventDefault(){this.prevented=true;}};
  get('players').events[type](event);return event;
}
async function swipe(video,x1,y1,x2,y2){
  const start=touch('touchstart',video,x1,y1),move=touch('touchmove',video,x2,y2),end=touch('touchend',video,x2,y2);
  await settle();return {start,move,end};
}
(async()=>{
  mockPages();await context.loadGallery();
  assert.equal(get('grid').children.length,48);assert.equal(get('countAll').textContent,'60');assert.equal(get('viewer').open,false);
  assert(calls.every(call=>call.url.startsWith('/api/gallery?')),'Listing must never request video streams');
  assert(get('grid').children.every(node=>!node.innerHTML.includes('<video')),'The grid uses cached images rather than video elements');
  const firstCard=get('grid').children[0];await context.loadGallery(true);assert.equal(get('grid').children.length,60);assert.equal(get('grid').children[0],firstCard,'Infinite scroll preserves existing cards');
  const count=calls.length;await context.loadGallery(false,true);assert.equal(calls.length,count+1);assert.equal(get('grid').children[0],firstCard,'An unchanged refresh must not rebuild cards');
  const inputs=get('grid').querySelectorAll('[data-pick]');
  for(const index of [0,1,2]){inputs[index].checked=true;get('grid').onchange({target:inputs[index]});}
  assert(inputs[3].disabled);inputs[3].checked=true;get('grid').onchange({target:inputs[3]});assert.equal(inputs[3].checked,false);assert(get('playSelected').textContent.includes('3/3'));
  active=get('playSelected');get('playSelected').onclick();await settle();
  let players=get('players').players;assert.equal(players.length,3);assert(players.every(player=>player.playCount===1));assert.equal(players[0].muted,false);assert.equal(players[1].muted,true);assert.equal(get('viewer').open,true);
  await context.loadGallery(false,true);assert.equal(get('players').players[0],players[0],'Automatic refresh must not interrupt playback');
  context.window.innerWidth=375;context.layoutViewer();assert.equal(get('players').style.gridTemplateColumns,'minmax(0,1fr)');assert(parseFloat(get('viewer').style['--viewer-width'])<=359);
  context.window.innerWidth=1024;context.layoutViewer();assert.equal(get('players').style.gridTemplateColumns.split('minmax').length-1,3);assert(parseFloat(get('viewer').style['--viewer-width'])<=1008);
  get('audio').value='2';get('audio').onchange();assert(players[0].muted&&players[1].muted&&!players[2].muted);
  get('pause').onclick();assert(players.every(player=>player.paused));get('replay').onclick();await settle();assert(players.every(player=>!player.paused));
  get('closeViewer').onclick();assert(players.every(player=>player.paused&&player.loads===1));assert.equal(get('players').players.length,0);assert.equal(active,get('playSelected'));assert.equal(active.focusOptions.preventScroll,true);
  context.openViewer(entries[3].id);await settle();assert.equal(get('players').players.length,1,'An unchecked video must replace the previous playback selection');assert(get('viewerTools').hidden);assert.equal(run('G.selected.size'),1);
  const single=get('players').players[0];single.videoWidth=720;single.videoHeight=1280;single.onloadedmetadata();assert.equal(single.parentElement.style['--aspect'],'720/1280');
  const loraInfo=context.loraHtml(entries[0]);assert.equal((loraInfo.match(/class="lora-row"/g)||[]).length,10);assert(loraInfo.includes('synthetic_9_full_suffix'));assert(!loraInfo.includes('외 '));
  assert(context.loraHtml({loras:[{name:'bad<img>.safetensors',strength:0}]}).includes('bad&lt;img&gt;'));
  context.setLoras(true);assert(doc.body.classList.contains('show-loras'));context.closeViewer();

  context.setDefaultPlaybackMuted(true,true);context.openViewer(entries[4].id);await settle();
  const mutedPlayer=get('players').players[0];assert(mutedPlayer.muted&&mutedPlayer.defaultMuted);
  const mutedPlays=mutedPlayer.playCount;mutedPlayer.currentTime=1.5;
  context.setDefaultPlaybackMuted(false,true);assert.equal(mutedPlayer.muted,false);assert.equal(mutedPlayer.playCount,mutedPlays);assert.equal(mutedPlayer.currentTime,1.5);
  context.setDefaultPlaybackMuted(true,true);mutedPlayer.muted=false;
  await context.moveViewer(1);assert.equal(get('players').players[0],mutedPlayer);assert.equal(mutedPlayer.muted,false,'Swipe preserves a native-control audio override');
  context.closeViewer();context.setDefaultPlaybackMuted(false,true);
  // Single playback reuses the same element (Safari permission) and replaces its stream.
  context.openViewer(entries[10].id);await settle();
  const oldPlayer=get('players').players[0],oldError=oldPlayer.onerror,opener=run('PLAYER.opener');oldPlayer.muted=true;oldPlayer.volume=.35;oldPlayer.focus();
  const modalCounts=[get('viewer').showCalls,get('viewer').closeCalls],scrollCount=window.scrollCalls;
  const moved=await swipe(oldPlayer,300,70,140,76);
  assert.equal(run('PLAYER.entries[0].id'),entries[11].id);assert(moved.move.prevented&&moved.end.prevented);
  assert.equal(get('players').players[0],oldPlayer,'Swiping must preserve the media element and its playback permission');
  assert(oldPlayer.loads===1&&oldPlayer.isConnected&&!oldPlayer.paused);
  assert.equal(oldPlayer.playCount,2);assert.equal(oldPlayer.muted,true);assert.equal(oldPlayer.volume,.35);
  assert(oldPlayer.src.startsWith('/api/video?'));assert(oldPlayer.card.querySelector('.lora-info').innerHTML.includes('synthetic_9_full_suffix'));
  assert.equal(run('PLAYER.opener'),opener);assert.equal(run('G.selected.size'),1);assert(run('G.selected.has(entries[11].id)'));
  assert.deepEqual([get('viewer').showCalls,get('viewer').closeCalls],modalCounts,'Navigation must not close/reopen the dialog or jump focus');
  assert.equal(window.scrollCalls,scrollCount);assert.equal(doc.body.style.overflow,'hidden');assert.equal(active.focusOptions.preventScroll,true);
  assert(get('viewerPosition').textContent.startsWith('12 / 60'));assert(!get('viewerNav').hidden);
  let swallowed=false;get('players').events.click({preventDefault(){swallowed=true;},stopPropagation(){}});assert(swallowed,'A swipe must not also toggle playback with a synthetic click');
  await swipe(get('players').players[0],140,70,300,74);assert.equal(run('PLAYER.entries[0].id'),entries[10].id);
  oldError();assert.equal(get('viewerStatus').textContent,'','A stale media error must not replace the new player state');

  // Ready neighbors must play synchronously within the gesture, even during polling.
  const playCount=oldPlayer.playCount;let finishBackground;
  context.background=new Promise(resolve=>finishBackground=resolve);run('G.loading=true;G.request=background;');
  const immediateNavigation=context.moveViewer(1);
  assert.equal(oldPlayer.playCount,playCount+1,'A background refresh must not defer the play() call');
  run('G.loading=false;');finishBackground();await immediateNavigation;await context.moveViewer(-1);

  const gesturePlayer=get('players').players[0];
  const vertical=await swipe(gesturePlayer,220,50,230,145);assert(!vertical.move.prevented&&!vertical.end.prevented);
  const seek=await swipe(gesturePlayer,300,205,100,205);assert(!seek.move.prevented&&!seek.end.prevented,'Native seek-bar drags are not gallery swipes');
  const tap=await swipe(gesturePlayer,220,70,225,73);assert(!tap.move.prevented&&!tap.end.prevented);
  touch('touchstart',gesturePlayer,300,70);touch('touchmove',gesturePlayer,100,70,[{identifier:7,clientX:100,clientY:70},{identifier:8,clientX:200,clientY:80}]);touch('touchend',gesturePlayer,100,70);
  touch('touchstart',gesturePlayer,300,70);get('players').events.touchcancel();touch('touchend',gesturePlayer,100,70);
  assert.equal(run('PLAYER.entries[0].id'),entries[10].id,'Vertical scrolling, seeking, taps, pinch gestures and cancelled gestures leave the video unchanged');
  let keyPrevented=false;get('viewer').events.keydown({key:'ArrowRight',target:gesturePlayer,preventDefault(){keyPrevented=true;}});assert(!keyPrevented,'Arrow keys focused on a video remain native seek controls');
  await get('nextVideo').onclick();assert.equal(run('PLAYER.entries[0].id'),entries[11].id);
  get('viewer').events.keydown({key:'ArrowLeft',target:get('closeViewer'),preventDefault(){keyPrevented=true;}});await settle();assert(keyPrevented);assert.equal(run('PLAYER.entries[0].id'),entries[10].id);
  context.openViewer(entries[0].id);assert(get('previousVideo').disabled);await context.moveViewer(-1);assert.equal(run('PLAYER.entries[0].id'),entries[0].id);
  context.openViewer(entries[59].id);assert(get('nextVideo').disabled);await context.moveViewer(1);assert.equal(run('PLAYER.entries[0].id'),entries[59].id);
  run('G.selected=new Set([entries[1].id,entries[2].id]);');context.openViewer();assert(get('viewerNav').hidden);
  await swipe(get('players').players[0],300,70,100,72);await context.moveViewer(1);assert.equal(run('PLAYER.entries.length'),2,'Compare playback does not navigate away');context.closeViewer();

  // Navigation follows the filtered/sorted list, and locates the current ID after refreshes.
  run('G.mode="favorites";G.items=[entries[7],entries[3],entries[1]];G.total=3;G.selected.clear();');
  context.drawGallery();context.openViewer(entries[3].id);await context.moveViewer(1);assert.equal(run('PLAYER.entries[0].id'),entries[1].id);
  await context.moveViewer(-1);assert.equal(run('PLAYER.entries[0].id'),entries[3].id);context.closeViewer();
  run('G.mode="all";G.items=[...entries];G.total=60;G.selected.clear();');context.drawGallery();context.openViewer(entries[10].id);
  run('G.items.unshift({...entries[0],id:"synthetic-new"});G.total++;');context.updateViewerNavigation();await context.moveViewer(1);assert.equal(run('PLAYER.entries[0].id'),entries[11].id);context.closeViewer();

  // Crossing a loaded-page boundary fetches the next metadata page, even during a refresh.
  run('G.items=[];G.total=0;G.revision="";G.selected.clear();');mockPages('swipe-page');await context.loadGallery();
  assert.equal(run('G.items.length'),48);context.openViewer(entries[47].id);
  const pageFetch=context.fetch;let releaseRefresh;
  context.fetch=async(...args)=>{await new Promise(resolve=>releaseRefresh=resolve);return pageFetch(...args);};
  const refresh=context.loadGallery(false,true),navigation=context.moveViewer(1);
  assert(get('nextVideo').disabled&&get('previousVideo').disabled);context.fetch=pageFetch;releaseRefresh();await refresh;await navigation;
  assert.equal(run('PLAYER.entries[0].id'),entries[48].id);assert.equal(run('G.items.length'),60);assert(!get('nextVideo').disabled);
  assert(calls.some(call=>new URL(call.url,'http://synthetic.local').searchParams.get('offset')==='48'));
  context.closeViewer();

  // A changed revision is resynchronized before choosing the adjacent item.
  run('G.items=[];G.total=0;G.revision="";G.selected.clear();');mockPages('old-order');await context.loadGallery();context.openViewer(entries[47].id);
  const reordered=[...entries].reverse();let reorderedCalls=0;
  context.fetch=async url=>{reorderedCalls++;const q=new URL(url,'http://synthetic.local').searchParams,offset=Number(q.get('offset')),limit=Number(q.get('limit'));return {ok:true,json:async()=>({items:reordered.slice(offset,offset+limit),total:60,counts:{all:60},revision:'changed-order'})};};
  await context.moveViewer(1);assert(reorderedCalls>=2);assert.equal(run('PLAYER.entries[0].id'),entries[46].id,'Choose the next item from the refreshed order, not stale offsets');context.closeViewer();

  // A failed page fetch preserves the current stream and remains retryable.
  run('G.items=[];G.total=0;G.revision="";G.selected.clear();');mockPages('retry-page');await context.loadGallery();context.openViewer(entries[47].id);
  const retryPlayer=get('players').players[0];context.fetch=async()=>{throw new Error('synthetic network failure');};await context.moveViewer(1);
  assert.equal(get('players').players[0],retryPlayer);assert.equal(run('PLAYER.entries[0].id'),entries[47].id);assert(!get('nextVideo').disabled);assert(get('viewerStatus').textContent.includes('다시 시도'));
  mockPages('retry-page');await context.moveViewer(1);assert.equal(run('PLAYER.entries[0].id'),entries[48].id);context.closeViewer();

  // A late page response cannot reopen a closed viewer or overwrite a newly opened video.
  for(const reopen of [false,true]){
    run('G.items=[];G.total=0;G.revision="";G.selected.clear();');mockPages('cancel-page');await context.loadGallery();context.openViewer(entries[47].id);
    const fetchPage=context.fetch;let releasePage;
    context.fetch=async(...args)=>{await new Promise(resolve=>releasePage=resolve);return fetchPage(...args);};
    const pendingNavigation=context.moveViewer(1);assert(run('PLAYER.navigating'));context.closeViewer();
    if(reopen)context.openViewer(entries[5].id);
    context.fetch=fetchPage;releasePage();await pendingNavigation;await settle();
    assert.equal(get('viewer').open,reopen);assert.equal(run('PLAYER.navigating'),false);
    if(reopen){assert.equal(run('PLAYER.entries[0].id'),entries[5].id);context.closeViewer();}else assert.equal(get('players').players.length,0);
  }
  let posted;
  context.fetch=async(url,options)=>{calls.push({url,options});if(options.method==='POST'){posted=JSON.parse(options.body);return {ok:true,json:async()=>({ok:true})};}return {ok:true,json:async()=>({items:entries,total:60,counts:{all:60,favorites:1,trash:0},revision:'favorite'})};};
  await context.updateItems([entries[0].id],'favorite',true);assert.deepEqual(posted,{ids:[entries[0].id],action:'favorite',value:true});assert(calls.every(call=>!call.url.includes('/api/history')&&!call.url.includes('/api/cancel')));
  context.requestDelete([entries[0].id]);assert(get('deleteDialog').open);assert(get('deleteQuestion').textContent.includes('1개'));get('cancelDelete').onclick();assert(!get('deleteDialog').open);
  context.requestDelete([entries[0].id]);get('confirmDelete').onclick();await settle();assert.equal(posted.action,'trash');
  run('G.mode="trash";');context.requestDelete([entries[0].id]);await settle();assert.equal(posted.action,'restore');assert(!get('deleteDialog').open);
  // A response belonging to an earlier filter must never replace the new view.
  let release,requests=0;
  context.fetch=async()=>{requests++;if(requests===1)await new Promise(resolve=>release=resolve);return {ok:true,json:async()=>({items:requests===1?entries:[],total:0,counts:{},revision:'new-filter'})};};
  run('G.revision="";');const oldLoad=context.loadGallery(false,true);run('G.mode="favorites";');context.changeView();release();await oldLoad;await settle();assert.equal(get('grid').children.length,0);assert(requests>=2);
  assert(html.includes('grid-template-columns:repeat(2,minmax(0,1fr))'));assert(html.includes('min-height:44px'));assert(html.includes('playsinline'));assert(html.includes('원본 영상과 작업 이력은 보관'));
  // Regeneration stays inside the gallery and sends IDs only after confirmation.
  const regenerateEntries=entries.slice(0,3).map((entry,index)=>({...entry,source_id:`synthetic-job-${index}`}));
  context.regenerateEntries=regenerateEntries;
  run('G.items=regenerateEntries;G.total=3;G.mode="all";G.selected.clear();');context.drawGallery();
  assert(context.regenerationButton({...regenerateEntries[0],source_id:null}).includes('disabled'));
  const beforeSelectionCalls=calls.length;
  context.chooseRegeneration(regenerateEntries[0].id);
  assert.equal(run('REGEN.target.source_id'),'synthetic-job-0');assert(!get('regenerationBar').hidden);
  assert(get('grid').children.every(node=>node.innerHTML.includes('이 영상 설정 가져오기')));
  context.openViewer(regenerateEntries[1].id);
  const regenerateButton={dataset:{regenerate:regenerateEntries[1].id}};
  get('players').onclick({target:{closest:()=>regenerateButton}});
  assert(!get('viewer').open);assert(get('regenerationDialog').open);
  assert.equal(run('REGEN.source.source_id'),'synthetic-job-1');assert.equal(calls.length,beforeSelectionCalls);
  let finishRequest,regeneratePosts=[];
  context.fetch=async(url,options)=>{regeneratePosts.push({url,body:JSON.parse(options.body)});await new Promise(resolve=>finishRequest=resolve);return {ok:true,json:async()=>({id:'synthetic-regenerated'})};};
  const sending=context.submitRegeneration();await context.submitRegeneration();context.cancelRegeneration();
  assert.equal(regeneratePosts.length,1);assert(get('regenerationDialog').open);assert(get('confirmRegeneration').disabled);
  assert.deepEqual(Object.keys(regeneratePosts[0].body).sort(),['request_id','source_id','target_id']);
  assert.equal(regeneratePosts[0].body.target_id,'synthetic-job-0');assert.equal(regeneratePosts[0].body.source_id,'synthetic-job-1');
  assert.equal(regeneratePosts[0].url,'/api/gallery/regenerate');finishRequest();await sending;
  assert.equal(run('REGEN.target'),null);assert(get('regenerationBar').hidden);assert(!get('regenerationDialog').open);
  context.chooseRegeneration(regenerateEntries[0].id);context.chooseRegeneration(regenerateEntries[2].id);
  const retryToken=run('REGEN.requestId');let tries=0;
  context.fetch=async(url,options)=>{tries++;assert.equal(JSON.parse(options.body).request_id,retryToken);if(tries===1)throw new Error('Synthetic connection failure');return {ok:true,json:async()=>({id:'synthetic-regenerated',already_queued:true})};};
  await context.submitRegeneration();assert(get('regenerationError').textContent.includes('Synthetic'));assert(get('regenerationDialog').open);assert(!get('confirmRegeneration').disabled);
  await context.submitRegeneration();assert.equal(tries,2);assert.equal(run('REGEN.target'),null);
  context.chooseRegeneration(regenerateEntries[0].id);context.chooseRegeneration(regenerateEntries[1].id);
  get('changeRegenerationSource').onclick();assert.equal(run('REGEN.source'),null);assert(run('REGEN.target'));assert(!get('regenerationDialog').open);
  context.cancelRegeneration();assert.equal(run('REGEN.target'),null);
  // Show progress without task content and reveal a completed regeneration once.
  run('ACTIVITY.states.clear();ACTIVITY.waiting.clear();ACTIVITY.ready=null;G.focus=null;G.active=true;');
  let activity={running:true,pct:42,pending:4,jobs:[{id:'old-done',state:'done',completed_at:10},{id:'fresh-job',state:'running',completed_at:0}]};
  const completedEntry={...entries[0],id:'fresh-result',source_id:'fresh-job',regenerated:true};
  const activityRequests=[];
  context.fetch=async(url)=>{
    activityRequests.push(url);
    if(url==='/api/gallery/progress')return {ok:true,json:async()=>activity};
    assert(url.startsWith('/api/gallery?'));
    return {ok:true,json:async()=>({items:[completedEntry,...regenerateEntries],total:4,counts:{all:4},revision:'completed-focus'})};
  };
  const initialScroll=window.scrollCalls;
  await context.pollActivity();assert.equal(get('workProgress').value,42);assert(get('workProgressText').textContent.includes('42%'));assert.equal(get('workPending').textContent,'대기 4개');
  assert.equal(window.scrollCalls,initialScroll,'Old completed results must not trigger a jump on first load');
  run('G.mode="favorites";G.order="oldest";G.query="synthetic";');
  activity={running:true,pct:3,pending:3,jobs:[{id:'old-done',state:'done',completed_at:10},{id:'fresh-job',state:'done',completed_at:200}]};
  await context.pollActivity();await settle();await settle();
  assert.equal(run('G.mode'),'all');assert.equal(run('G.order'),'newest');assert.equal(run('G.query'),'');
  assert.equal(run('G.focus'),'fresh-job');assert.equal(run('G.items[0].id'),'fresh-result');
  assert.equal(window.scrollCalls,initialScroll+1);assert.equal(run('ACTIVITY.ready'),null);
  assert(get('grid').children[0].classList.contains('completed-focus'));assert(get('grid').children[0].innerHTML.includes('방금 재생성 완료'));
  assert(activityRequests.some(url=>url.includes('focus=fresh-job')));
  await context.pollActivity();assert.equal(window.scrollCalls,initialScroll+1,'Polling must not repeatedly move the viewport');
  // A viewer stays open; the completion is revealed after playback closes.
  context.openViewer(completedEntry.id);const whilePlaying=window.scrollCalls;
  context.rememberRegeneration('fresh-job');await context.pollActivity();assert.equal(window.scrollCalls,whilePlaying);assert(get('viewer').open);assert.equal(run('ACTIVITY.ready'),'fresh-job');
  assert(run('ACTIVITY.waiting.has("fresh-job")'),'Unseen completion remains restorable after refresh');
  context.closeViewer();context.showCompletedRegeneration();assert.equal(window.scrollCalls,whilePlaying+1);assert(!run('ACTIVITY.waiting.has("fresh-job")'));
  activity={running:false,pct:null,pending:0,jobs:[]};await context.pollActivity();assert(get('workProgressText').textContent.includes('없음'));assert.equal(get('workProgress').value,0);
  doc.hidden=true;const hiddenRequests=activityRequests.length;await context.pollActivity();assert.equal(activityRequests.length,hiddenRequests);doc.hidden=false;
  context.fetch=async()=>{throw new Error('Synthetic offline');};await context.pollActivity();assert(get('workProgressText').textContent.includes('연결 확인'));assert.equal(get('workPending').textContent,'');
  const mainHtml=fs.readFileSync(process.argv[3]||path.join(__dirname,'../simple_ui/index.html'),'utf8'),mainScript=mainHtml.match(/<script>([\s\S]*)<\/script>/)[1];
  const tabElements=new Map(),messages=[],previewTabStates=[];
  const tabGet=id=>{if(!tabElements.has(id)){const element=new Element(id);element.hidden=true;element.getAttribute=name=>element.attrs[name];element.contentWindow={postMessage:message=>messages.push({id,message})};tabElements.set(id,element);}return tabElements.get(id);};
  const tabContext=vm.createContext({$:tabGet,document:{body:new Element('tab-body')},window:{innerHeight:800,addEventListener(){}},location:{origin:'http://synthetic.local'},hideHistoryDetails(){},closeVideoComparison(){},syncHistoryPreviews(){previewTabStates.push(tabGet('singleApp').hidden);},isLoraOverlayEnabled:()=>true});
  vm.runInContext(mainScript.slice(mainScript.indexOf('function sizeGalleryFrame('),mainScript.indexOf('window.addEventListener("message",event=>')),tabContext);
  tabGet('galleryTab').onclick();assert(!tabGet('galleryFrame').hidden);assert(tabGet('singleApp').hidden&&tabGet('storyFrame').hidden);assert.equal(tabGet('galleryFrame').src,'/gallery');assert.equal(tabGet('galleryFrame').style.height,'792px');
  tabGet('galleryFrame').onload();assert(messages.some(({message})=>message.type==='lora-overlay-toggle'&&message.enabled));
  tabContext.setGalleryNavHidden(true);assert(tabContext.document.body.classList.contains('gallery-nav-hidden'));
  tabGet('galleryFrame').onload();assert(!tabContext.document.body.classList.contains('gallery-nav-hidden'),'Reloading the gallery must restore navigation');
  tabContext.setGalleryNavHidden(true);
  tabGet('singleTab').onclick();assert(!tabGet('singleApp').hidden);assert(tabGet('galleryFrame').hidden);assert.equal(messages.at(-1).message.active,false);
  assert(!tabContext.document.body.classList.contains('gallery-nav-hidden'),'Leaving the gallery must restore the main navigation');
  assert.deepEqual(previewTabStates,[true,false],'Tab switches must update the main-page preview resource lifecycle');
  // Metadata may arrive after playback opens. Refresh only the displayed LoRA info.
  context.closeViewer();
  const infoItems=entries.slice(0,3).map((item,index)=>({...item,id:'synthetic-lora-info-'+index,loras:index===2?loras:[]}));
  context.infoItems=infoItems;
  run('G.active=true;G.items=infoItems;G.total=3;G.revision="lora-before";G.selected=new Set(infoItems.map(item=>item.id));');
  context.openViewer();await settle();
  const infoPlayers=[...get('players').players];infoPlayers.forEach((player,index)=>{player.currentTime=1.25+index;player.volume=.3;});
  const playerState=infoPlayers.map(player=>({time:player.currentTime,loads:player.loads,plays:player.playCount,paused:player.paused,volume:player.volume,src:player.src,muted:player.muted}));
  const beforeInfoDialogs=[get('viewer').showCalls,get('viewer').closeCalls];
  const freshInfo=infoItems.map((item,index)=>{
    const next={...item};if(index===0)next.loras=loras;else if(index===1)delete next.loras;else next.loras=[];return next;
  }).reverse();
  context.fetch=async()=>({ok:true,json:async()=>({items:freshInfo,total:3,counts:{all:3},revision:'lora-after'})});
  await context.loadGallery(false,true);
  assert(infoPlayers[0].card.querySelector('.lora-info').innerHTML.includes('synthetic_9_full_suffix'),'A stale empty LoRA list must update when metadata arrives');
  assert.equal((infoPlayers[0].card.querySelector('.lora-info').innerHTML.match(/class="lora-row"/g)||[]).length,10);
  assert.equal(infoPlayers[1].card.querySelector('.lora-info').innerHTML,'LoRA 기록 없음','Missing records must not become an empty LoRA list');
  assert.equal(infoPlayers[2].card.querySelector('.lora-info').innerHTML,'LoRA 없음','An explicitly empty list must clear the old displayed LoRAs');
  infoPlayers.forEach((player,index)=>{
    assert.equal(get('players').players[index],player);
    assert.deepEqual({time:player.currentTime,loads:player.loads,plays:player.playCount,paused:player.paused,volume:player.volume,src:player.src,muted:player.muted},playerState[index],'Refreshing information must preserve playback, audio and Safari permission');
  });
  assert.deepEqual([get('viewer').showCalls,get('viewer').closeCalls],beforeInfoDialogs);
  context.closeViewer();
  console.log('Gallery UI checks passed: regeneration, swipe/playback/filter flows, mobile/iPad sizing and live LoRA metadata refresh without interrupting playback.');
})().catch(error=>{console.error(error);process.exitCode=1;});
