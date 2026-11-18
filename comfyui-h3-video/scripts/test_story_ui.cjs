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
  console.log('Story UI checks passed: four clips, scoped AI drafts/edits, stale-source rejection, approval gates, stable inline playback.');
})().catch(error=>{console.error(error);process.exitCode=1;});
