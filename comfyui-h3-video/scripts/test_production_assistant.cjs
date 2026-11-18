// Fake DOM, fake API and synthetic values only. Never opens a browser or real app.
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const P=require(process.argv[2]||path.join(__dirname,'../simple_ui/production_assistant.js'));
class Node{
  constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.listeners={};this.style={};this.attributes={};this.value='';this.checked=false;this.disabled=false;this.readOnly=false;this.hidden=false;this.isConnected=true;this.options=[];this.labels=[];this.type=tag==='button'?'button':'';this.textContent='';this.id='';}
  set innerHTML(html){this._html=html;for(const match of html.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){const node=new Node(match[1],this.ownerDocument);node.id=match[2];node.parentElement=this;this.ownerDocument.nodes.set(node.id,node);if(match[0].includes(' hidden'))node.hidden=true;}}
  get innerHTML(){return this._html||'';}
  appendChild(node){this.children.push(node);node.parentElement=this;if(node.id)this.ownerDocument.nodes.set(node.id,node);return node;}
  replaceChildren(){this.children=[];}
  setAttribute(key,value){this.attributes[key]=value;}
  getAttribute(key){return this.attributes[key]??null;}
  closest(){return this.id.startsWith('h3Production')?this:null;}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
  dispatchEvent(event){this['on'+event.type]?.(event);for(const fn of this.listeners[event.type]||[])fn(event);}
  click(){if(!this.disabled){this.clicks=(this.clicks||0)+1;return this.onclick?.();}}
  querySelectorAll(){return this.ownerDocument.appControls;}
}
function app(){
  const doc={nodes:new Map(),appControls:[],createElement(tag){return new Node(tag,this);},getElementById(id){return this.nodes.get(id)||null;},querySelectorAll(selector){return selector==='iframe'?[]:this.appControls;},querySelector(){return null;}};
  doc.head=new Node('head',doc);doc.body=new Node('body',doc);
  function field(id,type,value,label){const node=new Node(type==='textarea'?'textarea':type==='select'?'select':'input',doc);node.id=id;node.type=type;node.value=value;node.labels=[{textContent:label||id}];doc.nodes.set(id,node);doc.appControls.push(node);return node;}
  const duration=field('duration','number','7','영상 길이'),final=field('final','textarea','summary: Synthetic block slides.','최종 프롬프트');
  const button=new Node('button',doc);button.id='go';button.textContent='대기열 추가';doc.appControls.push(button);doc.nodes.set(button.id,button);
  field('password','password','PRIVATE_SECRET');field('photos','file','PRIVATE_FILE_PATH');
  const requests=[],storage=new Map();let handler=(url,body)=>url.endsWith('/start')?{id:'fake-job'}:url.includes('/status')?{state:'done',production:{plan_id:'fake-plan',reply:'합성 답변',intent:'execute',reads:[],actions:[],auto_eligible:true}}:{ok:true};
  const win={document:doc,location:{origin:'http://fake.invalid',href:'http://fake.invalid/'},localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},setTimeout:fn=>{fn();return 0;},Event:class{constructor(type){this.type=type;}},fetch:async(url,options)=>{const body=options?.body?JSON.parse(options.body):null;requests.push({url,body});return {ok:true,json:async()=>handler(url,body)};}};win.top=win.self=win;doc.defaultView=win;
  let generationReads=0;
  win.H3ProductionBridge={fingerprint:()=>JSON.stringify({duration:duration.value,final:final.value}),imageRefs:()=>['PRIVATE_PHOTO_BYTES'],bindings:()=>{const value={current_settings:{f:{duration:duration.value},images:['PRIVATE_PHOTO_BYTES']},current_prompt:final.value};Object.defineProperty(value,'current_generation',{enumerable:true,get:()=>{generationReads++;throw Error('Unused photo generation binding must not be read');}});return value;},refresh(){}};
  const edit={kind:'set',target:'main:1',before:'7',value:'5',path:'',args:'{}',label:'길이를 5초로 수정'};
  P.mount(win);
  const $=id=>doc.getElementById(id);
  function respond(actions,extra={}){handler=(url,body)=>url.endsWith('/start')?{id:'fake-job'}:url.includes('/status')?{state:'done',production:{plan_id:'fake-plan',reply:'합성 답변 <img src=x onerror=alert(1)>',intent:'execute',reads:[],actions,auto_eligible:true,...extra}}:url.endsWith('/claim')?{action:actions[body.index]}:{ok:true};}
  return {win,doc,$,duration,final,button,requests,edit,respond,getGenerationReads:()=>generationReads};
}
(async()=>{
  assert.equal(P.replaceOne('  Before.\nKeep this.  ','Before','After'),'  After.\nKeep this.  ');
  assert.throws(()=>P.replaceOne('same same','same','other'));assert.throws(()=>P.replaceOne('not empty','','other'));
  for(const name of ['index.html','story.html','gallery.html']){
    const html=fs.readFileSync(path.join(__dirname,'../simple_ui',name),'utf8');
    const loader=html.match(/<script src="\/production-assistant.js" defer>([\s\S]*?)<\/script>/);
    assert(loader&&loader[1].trim()==='', 'External loader must not swallow inline app bindings');
    const inline=html.match(/<script>([\s\S]*)<\/script>/)[1];assert(inline.includes('window.H3ProductionBridge='),'Native app bindings must run in the inline app context');
  }
  let a=app(),snapshot=P.collect(a.win,{map:new WeakMap(),next:0});
  assert(snapshot.controls.some(item=>item.id==='final'),'Final prompt remains available even inside collapsed UI');
  assert(!JSON.stringify(snapshot.controls).includes('PRIVATE'),'Passwords, photo bytes and file-picker names never go into model context');
  assert.equal(snapshot.controls.find(item=>item.type==='file').value,'');
  const slider=new Node('input',a.doc);slider.type='range';slider.value='0.5';slider.title='강도';slider.setAttribute('min','0');slider.setAttribute('max','2');slider.setAttribute('step','0.05');slider.closest=selector=>selector.includes('[data-l]')?{getAttribute:key=>key==='data-l'?'SyntheticLoRA.safetensors':null}:null;a.doc.appControls.push(slider);
  const lora=P.collect(a.win,{map:new WeakMap(),next:0}).controls.find(item=>item.item_id==='SyntheticLoRA.safetensors');assert(lora&&lora.type==='number');assert.equal(lora.step,'0.05');assert.equal(lora.max,'2');

  assert.throws(()=>P.bindArgs('$current_missing',{}));
  a.respond([a.edit]);a.$('h3ProductionInput').value='길이만 5초로 바꿔줘';await a.$('h3ProductionSend').click();
  assert.equal(a.duration.value,'7','Review mode does not change the page');assert(!a.$('h3ProductionExecute').hidden);assert(!a.requests.some(item=>item.url.endsWith('/claim')));
  assert(!JSON.stringify(a.requests.find(item=>item.url.endsWith('/start')).body).includes('PRIVATE'));
  await a.$('h3ProductionExecute').click();assert.equal(a.duration.value,'5');
  await a.$('h3ProductionExecute').click();assert.equal(a.requests.filter(item=>item.url.endsWith('/claim')).length,1,'A plan cannot replay');
  assert(a.$('h3ProductionLog').children.some(item=>item.textContent.includes('<img')));assert(!a.$('h3ProductionLog').innerHTML.includes('<img'),'Provider text is literal, not HTML');
  a=app();a.respond([a.edit]);a.$('h3ProductionInput').value='길이를 5초로 바꿔줘';await a.$('h3ProductionSend').click();a.duration.value='6';await a.$('h3ProductionExecute').click();
  assert.equal(a.duration.value,'6');assert(!a.requests.some(item=>item.url.endsWith('/claim')),'Stale input blocks execution before claiming');
  a=app();a.respond([a.edit]);a.$('h3ProductionAuto').checked=true;a.$('h3ProductionInput').value='길이를 5초로 바꿔줘';await a.$('h3ProductionSend').click();assert.equal(a.duration.value,'5');
  a=app();a.respond([a.edit],{auto_eligible:false,intent:'propose'});a.$('h3ProductionAuto').checked=true;a.$('h3ProductionInput').value='어떻게 바꾸면 좋을까?';await a.$('h3ProductionSend').click();assert.equal(a.duration.value,'7','Advice never auto-executes');
  a=app();const save={...a.edit,kind:'api',target:'',before:'',value:'',path:'/api/settings/save',args:'{"name":"Synthetic","data":"$current_settings"}',label:'현재 설정 묶음 저장'};a.respond([save]);a.$('h3ProductionInput').value='설정 묶음을 저장해줘';await a.$('h3ProductionSend').click();await a.$('h3ProductionExecute').click();
  const executed=a.requests.find(item=>item.url.endsWith('/execute'));assert.equal(executed.body.args.data.images[0],'PRIVATE_PHOTO_BYTES','Media remains local to the existing save API');assert.equal(a.getGenerationReads(),0,'Unused generation binding stays lazy');
  assert(!JSON.stringify(a.requests.find(item=>item.url.endsWith('/start')).body).includes('PRIVATE_PHOTO_BYTES'));
  a=app();a.respond([a.edit]);a.$('h3ProductionInput').value='길이를 바꿔줘';await a.$('h3ProductionSend').click();a.respond([],{intent:'explain'});a.$('h3ProductionInput').value='이 수정안을 더 보완해줘';await a.$('h3ProductionSend').click();assert(a.requests.filter(item=>item.url.endsWith('/start')).at(-1).body.proposal.actions.length===1,'Follow-up carries the latest unapplied proposal');
  a.$('h3ProductionNew').click();assert.equal(a.duration.value,'7');assert(a.$('h3ProductionPlan').hidden);
  a=app();a.respond([{...a.edit,kind:'click',target:'main:3',before:'',value:'',label:'대기열 추가'}]);a.$('h3ProductionInput').value='대기열에 추가해줘';await a.$('h3ProductionSend').click();await a.$('h3ProductionExecute').click();assert.equal(a.button.clicks,1);
  console.log('Production assistant UI passed: full final prompt, review/auto modes, stale-source protection, literal replies, local-only bindings, follow-ups and non-replayed actions.');
})().catch(error=>{console.error(error);process.exitCode=1;});
