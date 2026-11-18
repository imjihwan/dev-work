// Complete history-rendering checks using synthetic metadata and fake video players.
// No browser, live history, input photos or output files are accessed.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
const elements=new Map();let active=null;
class Player{
  constructor(){this.currentTime=0;this.paused=true;this.playCount=0;this.pauseCount=0;this.loadCount=0;this.parentElement={style:{setProperty(name,value){this[name]=String(value);}}};}
  play(){this.paused=false;this.playCount++;return Promise.resolve();}
  pause(){this.paused=true;this.pauseCount++;}
  removeAttribute(){}
  load(){this.loadCount++;}
  focus(options){active=this;this.focusOptions=options;}
}
class Element{
  constructor(id=''){this.id=id;this.hidden=true;this.disabled=false;this.checked=false;this.value='';this.textContent='';this.dataset={};this.events={};this.players=[];this.inputs=[];this.parts=new Map();this.style={overflow:'',setProperty(name,value){this[name]=String(value);}};this.firstElementChild={style:{}};this._html='';}
  set innerHTML(value){this._html=value;this.players=[...value.matchAll(/<video\b/g)].map(()=>new Player());this.inputs=[...value.matchAll(/data-compare="([^"]+)"/g)].map(match=>{const input=new Element();input.dataset.compare=match[1];input.parentElement=new Element();return input;});}
  get innerHTML(){return this._html;}
  querySelectorAll(selector){if(selector==='video'||selector==='.hpreview video')return this.players;if(selector==='[data-compare]')return this.inputs;return [];}
  querySelector(selector){if(selector==='video')return this.players[0]||null;if(selector.includes('.hpreview:not'))return null;if(!this.parts.has(selector))this.parts.set(selector,new Element());return this.parts.get(selector);}
  replaceChildren(){this.players=[];this.inputs=[];this._html='';}
  addEventListener(type,fn){this.events[type]=fn;}
  setAttribute(){}
  contains(target){return target===this;}
  focus(options){active=this;this.focusOptions=options;}
}
const get=id=>{assert.notEqual(id,'result','The removed automatic result panel must not be accessed');if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const doc={body:{style:{overflow:'auto'}},addEventListener(){},querySelectorAll:()=>get('videoCompareGrid').players};
Object.defineProperty(doc,'activeElement',{get:()=>active});
const context=vm.createContext({console,$:get,esc:escape,base:value=>String(value).split(/[\\/]/).pop(),document:doc,
  window:{innerWidth:1000,innerHeight:800,addEventListener(){}},setTimeout:()=>0,clearTimeout(){},requestAnimationFrame(){},
  CAT:{models:[],capabilities:{queue_edit:true,bulk_edit:true}},friendlyModel:m=>m.name,
  currentJobs:[],finished:job=>job.state==='done',vurl:()=>'/synthetic-video-not-requested.mp4',
  editingJobId:null,bulkEditingIds:[],bulkAllEditing:false,setQueueEdit(){},loadFromHist(){},setStatus(){},updateGoLabel(){},
  pollGen:0,pollT0:0,timer:null,queueSubmitting:false,localStorage:{removeItem(){}},restartCurrentJob(){}});
vm.runInContext(script.slice(script.indexOf('// Browser playback mute.'),script.indexOf('// End playback default handling.')),context);
vm.runInContext(script.slice(script.indexOf('function loraOverlayHtml('),script.indexOf('async function submitJobs(')),context);
vm.runInContext(script.slice(script.indexOf('const HIST ='),script.indexOf('// 그때 구성을 화면에 다시 채운다')),context);
const loras=Array.from({length:10},(_,i)=>({name:`folder/Very_long_synthetic_lora_name_${i}_full_suffix.safetensors`,strength:i===0?0:i/10}));
const entries=Array.from({length:4},(_,i)=>({id:`synthetic-${i}`,t:1,state:'done',mode:'REF2VA',model:'synthetic-model',steps:4,seed:100+i,width:640,height:384,duration:5,resolution:'draft',aspect:'16:9',loras,ui:{f:{summary:'Synthetic history entry'}},video:{filename:'synthetic.mp4'}}));
context.syntheticEntries=entries;
(async()=>{
  context.drawHist();assert(get('histList').innerHTML.includes('아직 기록이 없습니다.'));
  vm.runInContext('HIST.items=syntheticEntries;HIST.total=syntheticEntries.length;',context);
  context.drawHist();assert.equal(get('histList').inputs.length,4,'History rows must actually render');
  assert(get('histList').innerHTML.includes('Synthetic history entry'));assert.equal(get('videoCompare').hidden,true);assert.equal(get('videoCompareGrid').players.length,0);
  let inputs=get('histList').inputs;
  inputs[0].checked=true;get('histList').onchange({target:inputs[0]});
  assert.equal(get('compareVideos').disabled,false);assert.equal(inputs[2].disabled,false);
  assert.equal(get('videoCompare').hidden,true,'Selecting a video must not open playback automatically');
  get('compareAudio').value='0';active=get('compareVideos');get('compareVideos').onclick();await new Promise(setImmediate);
  assert.equal(get('videoCompareGrid').players.length,1);assert.equal(get('videoCompareGrid').players[0].paused,false);assert.equal(get('videoCompareGrid').style['--video-columns'],'1');
  const singleWidth=parseFloat(get('videoCompare').style['--playback-width']);assert(singleWidth>620&&singleWidth<=968);assert.equal(get('videoCompareGrid').style.gridTemplateColumns,'minmax(0,1fr)');assert.equal(get('videoCompareTools').hidden,true);assert.equal(get('videoCompareGrid').dataset.count,'1');assert(!get('histList').innerHTML.includes('<span>선택</span>'));
  const single=get('videoCompareGrid').players[0];single.videoWidth=384;single.videoHeight=512;single.onloadedmetadata();assert.equal(single.parentElement.style['--video-aspect'],'384/512');assert(parseFloat(get('videoCompare').style['--playback-width'])<singleWidth);assert.equal(entries[0].width,640,'Intrinsic media dimensions must not overwrite saved generation settings');
  get('closeCompare').onclick();assert.equal(get('videoCompare').hidden,true);
  for(const index of [1,2]){inputs[index].checked=true;get('histList').onchange({target:inputs[index]});}
  assert.equal(inputs[3].disabled,true);inputs[3].checked=true;get('histList').onchange({target:inputs[3]});assert.equal(inputs[3].checked,false,'A fourth selection must be rejected');
  assert(get('compareVideos').textContent.includes('3/3'));assert.equal(get('videoCompare').hidden,true);
  get('compareVideos').onclick();await new Promise(setImmediate);
  const players=get('videoCompareGrid').players;
  assert.equal(players.length,3);assert(players.every(video=>!video.paused));assert.equal(players[0].muted,false);assert.equal(players[1].muted,true);assert.equal(players[2].muted,true);assert.equal(get('videoCompareGrid').style['--video-columns'],'3');
  assert(parseFloat(get('videoCompare').style['--playback-width'])<=968);assert.equal(get('videoCompareTools').hidden,false);assert(!get('videoCompareGrid').innerHTML.includes('video-compare-caption'));assert(html.includes('max-height:none'));assert(!html.includes('height:var(--video-height'));
  context.window.innerWidth=360;context.layoutVideoPlayback(entries.slice(0,3));assert.equal(get('videoCompareGrid').style.gridTemplateColumns,'minmax(0,1fr)');assert(parseFloat(get('videoCompare').style['--playback-width'])<=344);context.window.innerWidth=1000;context.layoutVideoPlayback(entries.slice(0,3));
  assert.equal(get('videoCompare').hidden,false);assert.equal(doc.body.style.overflow,'hidden');
  context.fetch=async()=>({json:async()=>({state:'done',video:{filename:'new-synthetic.mp4'}})});context.saveJobs=()=>{};context.loadHist=()=>{};
  vm.runInContext(script.slice(script.indexOf('function poll(jobs,'),script.indexOf('const HIST =')),context);
  context.poll([{id:'new-synthetic-job',state:'queued'}],Date.now(),'synthetic submission');await new Promise(setImmediate);
  assert.equal(context.currentJobs[0].state,'done');assert.equal(get('videoCompareGrid').players[0],players[0],'Adding or finishing a job must not replace manual comparison playback');
  context.drawHist();assert.equal(get('videoCompareGrid').players[0],players[0],'History polling must not recreate comparison players');
  get('comparePause').onclick();assert(players.every(video=>video.paused));
  get('comparePlay').onclick();await new Promise(setImmediate);assert(players.every(video=>!video.paused));
  get('compareAudio').value='2';get('compareAudio').onchange();assert.equal(players[0].muted,true);assert.equal(players[1].muted,true);assert.equal(players[2].muted,false);
  get('compareAudio').value='none';get('compareAudio').onchange();assert(players.every(video=>video.muted));
  get('closeCompare').onclick();assert.equal(get('videoCompare').hidden,true);assert.equal(get('videoCompareGrid').players.length,0);assert(players.every(video=>video.paused&&video.loadCount===1));assert.equal(doc.body.style.overflow,'auto');assert.equal(active,get('compareVideos'));assert.equal(active.focusOptions.preventScroll,true);
  context.initDefaultPlaybackMute(context.applyPlaybackMuteDefault);context.setDefaultPlaybackMuted(true,true);
  context.openVideoComparison();await new Promise(setImmediate);
  const mutedPlayers=get('videoCompareGrid').players;assert(mutedPlayers.every(video=>video.muted&&video.defaultMuted));
  const playCounts=mutedPlayers.map(video=>video.playCount);mutedPlayers[0].currentTime=2;
  context.setDefaultPlaybackMuted(false,true);assert.equal(mutedPlayers[0].muted,false);assert(mutedPlayers.slice(1).every(video=>video.muted));
  assert.deepEqual(mutedPlayers.map(video=>video.playCount),playCounts);assert.equal(mutedPlayers[0].currentTime,2,'Preference must not restart playback');
  context.closeVideoComparison();context.openVideoComparison();await new Promise(setImmediate);assert.equal(get('videoCompareGrid').players[0].muted,false);
  context.closeVideoComparison();
  get('clearCompare').onclick();assert.equal(get('compareVideos').disabled,true);assert.equal(get('clearCompare').hidden,true);
  const overlay=context.loraOverlayHtml(loras);assert.equal((overlay.match(/class="lora-overlay-row"/g)||[]).length,10);
  for(let i=0;i<10;i++)assert(overlay.includes(`name_${i}_full_suffix`));assert(!overlay.includes('외 '));assert(overlay.includes('many'));
  assert(context.loraOverlayHtml([{name:'bad<img>.safetensors',strength:0}]).includes('bad&lt;img&gt;'));
  const card=context.videoStageHtml('<video></video>',entries[0]);assert(card.indexOf('</video></div>')<card.indexOf('class="video-lora-info"'),'LoRA information must be outside the video stage');
  assert(html.includes('text-overflow:ellipsis'));assert(!script.includes('drawRuns('));assert(!html.includes('id="result"'));
  assert(!script.includes('function showHistoryVideo('));assert(!get('histList').innerHTML.includes('data-play='));
  const thumbnail={dataset:{selectVideo:entries[1].id}};await get('histList').onclick({target:{closest:()=>thumbnail}});assert(get('compareVideos').textContent.includes('1/3'));
  await get('histList').onclick({target:{closest:()=>thumbnail}});assert(get('compareVideos').textContent.includes('0/3'));
  get('compareVideos').onclick();assert.equal(get('videoCompare').hidden,true);
  const playButton={dataset:{playSelected:entries[0].id}};
  await get('histList').onclick({target:{closest:()=>playButton}});await new Promise(setImmediate);assert.equal(get('videoCompareGrid').players.length,1,'The row play button must immediately open its video when nothing is selected');
  get('closeCompare').onclick();get('clearCompare').onclick();
  context.setVideoPlaybackSelection(entries[1].id,true);context.setVideoPlaybackSelection(entries[2].id,true);
  await get('histList').onclick({target:{closest:()=>playButton}});await new Promise(setImmediate);assert.equal(get('videoCompareGrid').players.length,1,'Playing an unchecked row must replace the old selection');assert(get('histList').inputs[0].checked);assert(!get('histList').inputs[1].checked);assert(!get('histList').inputs[2].checked);get('closeCompare').onclick();
  context.setVideoPlaybackSelection(entries[1].id,true);await get('histList').onclick({target:{closest:()=>playButton}});await new Promise(setImmediate);assert.equal(get('videoCompareGrid').players.length,2,'Playing a checked row must play the selected group');get('closeCompare').onclick();
  console.log('History UI checks passed: full list rendering, explicit playback of 1–3 selected videos, fourth-selection limit, thumbnail selection, stable players, audio/close controls and all ten LoRAs.');
})().catch(error=>{console.error(error);process.exitCode=1;});
