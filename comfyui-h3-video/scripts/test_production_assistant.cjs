// Fake DOM, fake API and synthetic values only. Never opens a browser or real app.
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const P=require(process.argv[2]||path.join(__dirname,'../simple_ui/production_assistant.js'));
class Node{
  constructor(tag,doc){this.tagName=tag.toUpperCase();this.ownerDocument=doc;this.children=[];this.listeners={};this.style={};this.attributes={};this.value='';this.checked=false;this.disabled=false;this.readOnly=false;this.hidden=false;this.isConnected=true;this.options=[];this.labels=[];this.type=tag==='button'?'button':'';this._text='';this.id='';this.classList={values:new Set(),toggle:(key,on)=>{if(on)this.classList.values.add(key);else this.classList.values.delete(key);},contains:key=>this.classList.values.has(key)};}
  set innerHTML(html){this._html=html;for(const match of html.matchAll(/<(\w+)\b[^>]*\bid="([^"]+)"[^>]*>/g)){const node=new Node(match[1],this.ownerDocument);node.id=match[2];node.parentElement=this;this.ownerDocument.nodes.set(node.id,node);if(match[0].includes(' hidden'))node.hidden=true;}}
  get innerHTML(){return this._html||'';}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  set textContent(value){this._text=String(value);this.children=[];}
  appendChild(node){if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(child=>child!==node);this.children.push(node);node.parentElement=this;if(node.id)this.ownerDocument.nodes.set(node.id,node);return node;}
  replaceChildren(...nodes){for(const child of this.children)child.parentElement=null;this.children=[];this._text='';for(const node of nodes)this.appendChild(node);}
  setAttribute(key,value){this.attributes[key]=value;}
  getAttribute(key){return this.attributes[key]??null;}
  closest(){return this.id.startsWith('h3Production')?this:null;}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
  dispatchEvent(event){let stopped=false;const previous=event.stopImmediatePropagation;event.stopImmediatePropagation=()=>{stopped=true;previous?.();};this['on'+event.type]?.(event);for(const fn of this.listeners[event.type]||[]){if(stopped)break;fn(event);}}
  click(){if(!this.disabled){this.clicks=(this.clicks||0)+1;return this.onclick?.();}}
  querySelectorAll(){return this.ownerDocument.appControls;}
}
function app(options={}){
  const doc={nodes:new Map(),appControls:[],createElement(tag){return new Node(tag,this);},getElementById(id){return this.nodes.get(id)||null;},querySelectorAll(selector){return selector==='iframe'?[]:this.appControls;},querySelector(){return null;}};
  doc.head=new Node('head',doc);doc.body=new Node('body',doc);
  function field(id,type,value,label){const node=new Node(type==='textarea'?'textarea':type==='select'?'select':'input',doc);node.id=id;node.type=type;node.value=value;node.labels=[{textContent:label||id}];doc.nodes.set(id,node);doc.appControls.push(node);return node;}
  const duration=field('duration','number','7','영상 길이'),final=field('final','textarea','summary: Synthetic block slides.','최종 프롬프트');
  const button=new Node('button',doc);button.id='go';button.textContent='대기열 추가';doc.appControls.push(button);doc.nodes.set(button.id,button);
  field('password','password','PRIVATE_SECRET');field('photos','file','PRIVATE_FILE_PATH');
  const requests=[],storage=options.storage||new Map();let handler=(url,body)=>url.endsWith('/start')?{id:'fake-job'}:url.includes('/status')?{state:'done',production:{plan_id:'fake-plan',reply:'합성 답변',intent:'execute',reads:[],actions:[],auto_eligible:true}}:{ok:true};
  const win={document:doc,innerWidth:options.width||900,matchMedia:()=>({matches:!!options.coarse}),location:{origin:'http://fake.invalid',href:'http://fake.invalid/'},localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},setTimeout:fn=>{fn();return 0;},Event:class{constructor(type){this.type=type;}},fetch:async(url,options)=>{const body=options?.body?JSON.parse(options.body):null;requests.push({url,body});return {ok:true,json:async()=>handler(url,body)};}};win.top=win.self=win;doc.defaultView=win;
  let generationReads=0;
  win.H3ProductionBridge={fingerprint:()=>JSON.stringify({duration:duration.value,final:final.value}),imageRefs:()=>['PRIVATE_PHOTO_BYTES'],bindings:()=>{const value={current_settings:{f:{duration:duration.value},images:['PRIVATE_PHOTO_BYTES']},current_prompt:final.value};Object.defineProperty(value,'current_generation',{enumerable:true,get:()=>{generationReads++;throw Error('Unused photo generation binding must not be read');}});return value;},refresh(){}};
  const edit={kind:'set',target:'main:1',before:'7',value:'5',path:'',args:'{}',label:'길이를 5초로 수정'};
  P.mount(win);
  const $=id=>doc.getElementById(id);
  function respond(actions,extra={}){handler=(url,body)=>url.endsWith('/start')?{id:'fake-job'}:url.includes('/status')?{state:'done',production:{plan_id:'fake-plan',reply:'합성 답변 <img src=x onerror=alert(1)>',intent:'execute',reads:[],actions,auto_eligible:true,...extra}}:url.endsWith('/claim')?{action:actions[body.index]}:{ok:true};}
  return {win,doc,$,duration,final,button,requests,storage,edit,respond,getGenerationReads:()=>generationReads};
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
  a=app({width:1440});assert(!a.$('h3ProductionPanel').hidden,'Desktop opens as an embedded chat sidebar');assert(a.doc.body.classList.contains('h3pa-open'));
  a.$('h3ProductionClose').click();assert(a.$('h3ProductionPanel').hidden);assert(!a.doc.body.classList.contains('h3pa-open'));assert(!a.$('h3ProductionToggle').hidden);
  const preference=a.storage;a=app({width:1440,storage:preference});assert(a.$('h3ProductionPanel').hidden,'Fold preference survives a new page without persisting chat text');a.$('h3ProductionToggle').click();assert(!a.$('h3ProductionPanel').hidden);
  a.$('h3ProductionExpand').click();assert(a.doc.body.classList.contains('h3pa-full'));assert.equal(a.$('h3ProductionExpand').getAttribute('aria-pressed'),'true');a.$('h3ProductionExpand').click();assert(!a.doc.body.classList.contains('h3pa-full'));
  a=app({width:390,coarse:true});assert(a.$('h3ProductionPanel').hidden,'Mobile starts with the compact launcher');a.$('h3ProductionToggle').click();assert(!a.$('h3ProductionPanel').hidden);assert(a.$('h3ProductionKeyHint').textContent.includes('보내기 버튼'));
  a.$('h3ProductionExample1').click();assert(a.$('h3ProductionInput').value.includes('설명'));assert.equal(a.requests.length,0,'Example chips only fill the composer');
  a=app({width:1440});a.respond([a.edit]);a.$('h3ProductionInput').value='길이를 바꿔줘';await a.$('h3ProductionSend').click();
  const messages=a.$('h3ProductionLog').children.filter(node=>node.getAttribute('data-role'));assert.equal(messages[0].getAttribute('data-role'),'user');assert.equal(messages[1].getAttribute('data-role'),'assistant');assert.equal(a.$('h3ProductionPlan').parentElement,messages[1],'Active proposal is attached to its assistant reply');assert(a.$('h3ProductionPlanSteps').textContent.includes('기존: 7'));assert(a.$('h3ProductionPlanSteps').textContent.includes('변경: 5'));
  await a.$('h3ProductionExecute').click();assert.equal(a.$('h3ProductionPlanState').textContent,'앱에 전달됨');
  a.respond([],{intent:'explain'});a.$('h3ProductionInput').value='현재 상황 설명해줘';await a.$('h3ProductionSend').click();assert(messages[1].children.some(node=>node.className==='h3pa-plan'&&node.textContent.includes('앱에 전달됨')),'Previous proposals retain a read-only execution receipt');
  a=app({width:1440});a.respond([],{intent:'explain'});let prevented=0;const key={type:'keydown',key:'Enter',preventDefault:()=>prevented++};a.$('h3ProductionInput').value='합성 질문';a.$('h3ProductionInput').dispatchEvent({...key,isComposing:true});a.$('h3ProductionInput').dispatchEvent({...key,shiftKey:true});assert.equal(a.requests.length,0,'IME composition and Shift+Enter never submit');
  a.$('h3ProductionInput').dispatchEvent(key);await new Promise(resolve=>setImmediate(resolve));assert(a.requests.some(item=>item.url.endsWith('/start')));assert.equal(prevented,1);
  a=app({width:390,coarse:true});a.$('h3ProductionInput').value='합성 질문';a.$('h3ProductionInput').dispatchEvent(key);assert.equal(a.requests.length,0,'Mobile Enter keeps multiline drafting');
  a=app({width:1440});let unintendedDirty=0;a.$('h3ProductionInput').addEventListener('input',()=>unintendedDirty++);a.$('h3ProductionAuto').addEventListener('input',()=>unintendedDirty++);a.$('h3ProductionInput').value='텍스트';a.$('h3ProductionInput').dispatchEvent({type:'input'});a.$('h3ProductionAuto').dispatchEvent({type:'input'});assert.equal(unintendedDirty,0,'Chat input must not dirty the host editor or story project');
  a=app({width:1440});a.respond([],{intent:'explain'});a.$('h3ProductionInput').value='합성 질문';const waiting=a.$('h3ProductionSend').click();const chat=a.$('h3ProductionLog');chat.scrollHeight=2000;chat.clientHeight=300;chat.scrollTop=200;chat.dispatchEvent({type:'scroll'});await waiting;assert.equal(chat.scrollTop,200,'New replies preserve an older reading position');assert(!a.$('h3ProductionLatest').hidden);a.$('h3ProductionLatest').click();assert.equal(chat.scrollTop,2000);assert(a.$('h3ProductionLatest').hidden);
  assert(P.CHAT_STYLES.includes('min-width:1280px')&&P.CHAT_STYLES.includes('max-width:1279px')&&P.CHAT_STYLES.includes('min-height:0'),'Sidebar and full mobile chat have independent bounded scroll areas');
  console.log('Production assistant UI passed: full final prompt, review/auto modes, stale-source protection, literal replies, local-only bindings, follow-ups and non-replayed actions.');
})().catch(error=>{console.error(error);process.exitCode=1;});
