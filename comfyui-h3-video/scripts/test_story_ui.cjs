// Static/VM checks only: never opens the app or requests private project data.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/story.html'),'utf8');
let source=html.match(/<script>([\s\S]*)<\/script>/)[1];source=source.slice(0,source.lastIndexOf('init().catch'));
const elements=new Map();
class Element{
  constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.hidden=false;this.disabled=false;this.style={};this.innerHTML='';this.textContent='';this.parts=new Map();this.classList={toggle:()=>{}};}
  querySelector(selector){if(selector==='video')return this.children.find(child=>child.tagName==='video')||null;if(!this.parts.has(selector))this.parts.set(selector,new Element(selector));return this.parts.get(selector);}
  querySelectorAll(selector){return selector==='video'?this.children.filter(child=>child.tagName==='video'):[];}
  replaceChildren(...children){this.children=children;}
  appendChild(child){child.parentElement=this;this.children.push(child);}
  addEventListener(){}
  pause(){this.paused=true;}
}
const get=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const requests=[];let handler=()=>({});
const context=vm.createContext({console,structuredClone,URLSearchParams,Map,Set,JSON,Number,String,Object,Array,Date,
  document:{getElementById:get,createElement:tag=>new Element(tag),querySelector:selector=>get(selector),querySelectorAll:selector=>selector==='video'?[...elements.values()].flatMap(element=>element.children.filter(child=>child.tagName==='video')):[]},
  window:{parent:{},postMessage:()=>{},addEventListener(){}},location:{origin:'http://synthetic.invalid',search:''},
  fetch:async(url,options)=>{const body=options?.body?JSON.parse(options.body):null;requests.push({url,body});return{ok:true,json:async()=>handler(url,body)};},
  localStorage:{getItem:()=>null,setItem:()=>{}},setTimeout:()=>0,confirm:()=>true,navigator:{clipboard:{writeText:async()=>{}}}});
vm.runInContext(source,context);
vm.runInContext("catalog={default:{model:'test-model',steps:4,sampler:'euler',scheduler:'simple',shift_video:5,shift_audio:5},models:[],loras:[]};createCards();fill(defaults());",context);
const plain=value=>JSON.parse(JSON.stringify(value));
(async()=>{
  assert.equal(context.readDefinition().clips.length,4);
  const initial=plain(context.readDefinition());assert.equal(initial.common.aspect,'auto');assert.equal(initial.boundaries.length,5);
  get('scenario2').value='Synthetic third scenario';
  const draft={f:{summary:'Third action only.',sound:'Quiet room.',music:'N/A',style:'Forbidden replacement'},shots:[['0','The subject turns.']]};
  handler=url=>url.endsWith('/start')?{id:'synthetic-helper'}:{state:'done',draft};
  const protectedCommon=JSON.stringify(plain(context.readDefinition().common)),otherClips=plain(context.readDefinition().clips).filter((_,i)=>i!==2);
  await context.writePrompt(2,false);
  const request=requests.find(item=>item.url==='/api/prompt-helper/start').body;
  assert.equal(request.story_context.clip_index,2);assert.equal(request.story_context.scenarios.length,4);assert(!('images' in request));
  assert.equal(request.engine,'dutchit');assert.equal(request.anchor,false);assert.equal(request.reference_count,1);
  assert.equal(get('summary2').value,'','AI must not apply until the user confirms');
  get('storyHelperEngine').value='legacy';context.applyPrompt(2);assert.equal(get('summary2').value,'');
  get('storyHelperEngine').value='dutchit';
  context.applyPrompt(2);
  assert.equal(get('summary2').value,'Third action only.');assert.equal(JSON.stringify(plain(context.readDefinition().common)),protectedCommon);
  assert.deepEqual(plain(context.readDefinition().clips).filter((_,i)=>i!==2),otherClips);
  assert.equal(get('scenario2').value,'Synthetic third scenario');
  get('edit2').value='Change only the music.';
  handler=url=>url.endsWith('/start')?{id:'synthetic-helper-2'}:{state:'done',draft:{f:{music:'Piano.'},edit:true,changes:[{target:'music',index:0,before:'N/A',after:'Piano.'}]}};
  await context.writePrompt(2,true);get('scenario1').value='Changed while writing';context.applyPrompt(2);
  assert.equal(get('music2').value,'N/A');assert(get('notice').textContent.includes('다시 작성'));
  const beforeReview=JSON.stringify(plain(context.readDefinition()));
  handler=url=>url.endsWith('/start')?{id:'synthetic-review'}:{state:'done',draft:{review_only:true,f:{},review:{status:'revise',summary:'시간 배분 수정 권장',issues:[{at:'0–1초',issue:'동작이 너무 많습니다.',suggestion:'주동작만 남기세요.'}]}}};
  await context.writePrompt(2,false,true);
  assert.equal(requests.findLast(item=>item.url==='/api/prompt-helper/start').body.review_only,true);
  assert.equal(get('aiApply2').hidden,true);assert(get('aiPreview2').textContent.includes('수정 권장'));
  context.applyPrompt(2);assert.equal(JSON.stringify(plain(context.readDefinition())),beforeReview);
  vm.runInContext("project={id:'a'.repeat(32),definition:readDefinition(),renders:Array.from({length:4},()=>({state:'empty',approved:false,stale:false})),active:null,merged:null};dirty=false;",context);
  context.updateStatus();assert.equal(get('generate0').disabled,false);assert.equal(get('generate1').disabled,true);assert.equal(get('merge').disabled,true);
  vm.runInContext("project.renders[0]={state:'done',approved:false,stale:false,has_video:true};",context);context.updateStatus();assert.equal(get('generate1').disabled,true);assert.equal(get('approve0').disabled,false);
  vm.runInContext("project.renders[0].approved=true;",context);context.updateStatus();assert.equal(get('generate1').disabled,false);assert.equal(get('generate2').disabled,true);
  context.initDefaultPlaybackMute(context.applyPlaybackMuteDefault);context.setDefaultPlaybackMuted(true,true);
  const beforePlaybackPreference=JSON.stringify(plain(context.readDefinition()));
  context.showVideo(0,'preview0');const player=get('preview0').children[0];assert(player.muted&&player.defaultMuted);
  get('defaultMuteToggle').checked=false;get('defaultMuteToggle').onchange();assert.equal(player.muted,false);
  assert.equal(JSON.stringify(plain(context.readDefinition())),beforePlaybackPreference);
  context.updateStatus();context.updateStatus();assert.equal(get('preview0').children[0],player,'Polling must not recreate a playing video');
  assert.equal(player.playsInline,true);assert(player.src.includes('/api/story/video?'));assert(!player.src.includes('filename'));
  vm.runInContext("project.renders.forEach(run=>Object.assign(run,{state:'done',approved:true,stale:false}));",context);context.updateStatus();assert.equal(get('merge').disabled,false);
  vm.runInContext("project.renders[2].stale=true;",context);context.updateStatus();assert.equal(get('merge').disabled,true);assert.equal(get('generate3').disabled,true);
  const ids=[...html.matchAll(/id="([a-zA-Z0-9_-]+)"/g)].map(match=>match[1]);assert.equal(new Set(ids).size,ids.length);
  assert(html.includes('각 단계')||html.includes('각 편'));assert(html.includes('이 단계 확정'));
  // A saved sampler that is no longer in the catalog list (removed because it breaks on H3) must stay visible instead of being blanked.
  const keepSource=html.match(/function keepListed\(id,value\)\{[^\n]*\}\r?\n/)[0];
  const added=[];const select={options:[{value:'euler'}],add:option=>{added.push(option.value);select.options.push(option);}};
  const keep=vm.runInNewContext(`(${keepSource.trim().replace('function keepListed','function')})`,{$:()=>select,Option:function(text,value){this.value=value;},String});
  keep('sampler','euler');assert.deepEqual(added,[]);
  keep('sampler','euler_cfg_pp');keep('sampler','euler_cfg_pp');assert.deepEqual(added,['euler_cfg_pp']);
  keep('sampler','');keep('sampler',null);assert.deepEqual(added,['euler_cfg_pp']);
  assert(html.includes("keepListed(key,definition.common[key])")&&html.includes("keepListed(key,values[key])"));
  // Choosing another model moves steps/sampler/shift to that model's recommendation (no 8-step turbo settings on a 25-step model).
  const applySource=html.match(/function applyModelRecommended\(name\)\{[\s\S]*?\n\}\r?\n/)[0];
  const fields={steps:{value:'8'},sampler:{value:'euler'},scheduler:{value:'simple'},shift_video:{value:'10'},shift_audio:{value:'3'}};
  const apply=vm.runInNewContext(`(${applySource.trim().replace('function applyModelRecommended','function')})`,
    {$:id=>fields[id],keepListed:()=>{},String,catalog:{models:[{name:'regular',effective:{steps:25,sampler:'res_multistep',scheduler:'simple',shift_video:11,shift_audio:4}},{name:'bare'}]}});
  assert.equal(apply('regular'),true);
  assert.deepEqual(Object.fromEntries(Object.entries(fields).map(([key,field])=>[key,String(field.value)])),{steps:'25',sampler:'res_multistep',scheduler:'simple',shift_video:'11',shift_audio:'4'});
  assert.equal(apply('regular'),false,'nothing to change the second time');
  assert.equal(apply('bare'),false);assert.equal(apply('missing'),false);
  assert(html.includes("applyModelRecommended($('model').value)"));
  // Speed first (opt-in): offered only when this ComfyUI has the node, and an untouched project saves the same common settings as before
  // (a new key would make the server treat the common settings as changed and mark all four clips stale).
  const speedSource=html.slice(html.indexOf('function drawSpeedOptions()'),html.indexOf('function keepListed(id,value)'));
  const speedBox={innerHTML:'',value:''},speedHint={textContent:''};
  const speedContext=vm.createContext({$:id=>({speed:speedBox,speedHint})[id],catalog:{capabilities:{speed_modes:['sparse','sparse_cache']}}});
  vm.runInContext(speedSource,speedContext);
  assert.equal(speedContext.drawSpeedOptions(),true);
  assert.equal((speedBox.innerHTML.match(/<option/g)||[]).length,2,'default + sparse attention; the step cache is not offered for four-clip projects');
  assert(speedBox.innerHTML.includes('value="sparse"')&&!speedBox.innerHTML.includes('sparse_cache'));
  speedContext.drawSpeedHint();assert.match(speedHint.textContent,/결과를 바꾸지 않는/);
  speedBox.value='sparse';speedContext.drawSpeedHint();assert.match(speedHint.textContent,/다른 영상이 나옵니다.*네 편 모두 다시/);
  speedContext.catalog={capabilities:{speed_modes:[]}};
  assert.equal(speedContext.drawSpeedOptions(),false);assert(!speedBox.innerHTML.includes('value="sparse"'));
  speedContext.drawSpeedHint();assert.match(speedHint.textContent,/필요한 노드가 이 ComfyUI 에 없습니다/,'a saved choice the ComfyUI cannot run is explained, not silently dropped');
  speedBox.value='';speedContext.drawSpeedHint();assert.match(speedHint.textContent,/필요한 노드가 없습니다/);
  speedContext.catalog={capabilities:{speed_modes:['sparse','sparse_cache']}};speedBox.value='sparse_cache';speedContext.drawSpeedHint();
  assert.match(speedHint.textContent,/이어 만들기에서 쓸 수 없는 속도 우선 방식/,'a value this page does not offer is not described as the default');
  speedContext.catalog={};speedContext.drawSpeedOptions();speedContext.drawSpeedHint();
  assert(html.includes("'shift_video','shift_audio','speed'];")&&html.includes('<select id="speed">')&&html.includes("key==='sampler'||key==='scheduler'||key==='speed'"));
  get('speed').value='';assert(!('speed' in context.readDefinition().common),'an unchosen speed mode adds no key to the saved settings');
  get('speed').value='sparse';assert.equal(context.readDefinition().common.speed,'sparse');get('speed').value='';
  // Regenerating an earlier clip makes the server drop later approvals and the merged file: the page asks first, and only when something would be lost.
  const done={state:'done',approved:true,has_video:true},idle={state:'idle'};
  const setProject=value=>vm.runInContext(`project=${JSON.stringify(value)};`,context),warning=index=>vm.runInContext(`regenerationWarning(${index})`,context);
  setProject({id:'p',revision:1,renders:[done,done,idle,idle],merged:null});
  assert.equal(warning(1),'','nothing after clip 2 exists yet');assert.equal(warning(3),'');
  assert.equal(warning(0),'1번을 다시 만들면 2번 편을 다시 생성해야 합니다(지금 영상은 확정할 수 없게 됩니다). 계속할까요?');
  setProject({id:'p',revision:1,renders:[done,done,{state:'done',approved:false,has_video:true},done],merged:{state:'done'}});
  assert.equal(warning(0),'1번을 다시 만들면 2번·3번·4번 편을 다시 생성해야 하고 병합 영상도 다시 만들어야 합니다(지금 영상은 확정할 수 없게 됩니다). 계속할까요?');
  assert.equal(warning(3),'4번을 다시 만들면 병합 영상을 다시 만들어야 합니다. 계속할까요?');
  // 한 번 다시 만들어 이미 낡은 뒤 편은 더 잃을 것이 없으니 다시 묻지 않는다
  const stale={state:'done',approved:false,has_video:true,stale:true};
  setProject({id:'p',revision:2,renders:[done,stale,stale,stale],merged:null});assert.equal(warning(0),'','already-stale later clips are not listed again');
  setProject({id:'p',revision:1,renders:[done,done,{state:'done',approved:false,has_video:true},done],merged:{state:'done'}});
  const asked=[],before=requests.length;context.confirm=text=>{asked.push(text);return false;};
  get('generate0').onclick();await new Promise(setImmediate);
  assert.equal(asked.length,1);assert.equal(requests.length,before,'declining leaves the project untouched: nothing is sent');
  setProject({id:'p',revision:1,renders:[done,idle,idle,idle],merged:null});asked.length=0;
  assert.equal(warning(0),'');assert(html.includes("if(!warning||confirm(warning))action('/api/story/generate',i)"),'no question when nothing would be lost');
  context.confirm=()=>true;setProject(null);
  console.log('Story UI checks passed: four clips, scoped AI drafts/edits, stale-source rejection, approval gates, stable inline playback, regeneration warning.');
})().catch(error=>{console.error(error);process.exitCode=1;});
