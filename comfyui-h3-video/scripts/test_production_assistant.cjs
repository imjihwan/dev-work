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
  const doc={nodes:new Map(),appControls:[],frames:[],createElement(tag){return new Node(tag,this);},getElementById(id){return this.nodes.get(id)||null;},querySelectorAll(selector){return selector==='iframe'?this.frames:this.appControls;},querySelector(){return null;}};
  doc.head=new Node('head',doc);doc.body=new Node('body',doc);
  function field(id,type,value,label){const node=new Node(type==='textarea'?'textarea':type==='select'?'select':'input',doc);node.id=id;node.type=type;node.value=value;node.labels=[{textContent:label||id}];doc.nodes.set(id,node);doc.appControls.push(node);return node;}
  const duration=field('duration','number','7','영상 길이'),final=field('final','textarea','summary: Synthetic block slides.','최종 프롬프트');
  const button=new Node('button',doc);button.id='go';button.textContent='대기열 추가';doc.appControls.push(button);doc.nodes.set(button.id,button);
  field('password','password','PRIVATE_SECRET');field('photos','file','PRIVATE_FILE_PATH');
  const requests=[],delays=[],progressText=[],storage=options.storage||new Map();let handler=(url,body)=>url.endsWith('/start')?{id:'fake-job'}:url.includes('/status')?{state:'done',production:{plan_id:'fake-plan',reply:'합성 답변',intent:'execute',reads:[],actions:[],auto_eligible:true}}:{ok:true};
  const shared=options.shared,origin=options.origin||'http://fake.invalid';
  const win={document:doc,innerWidth:options.width||900,matchMedia:()=>({matches:!!options.coarse}),location:{origin,href:origin+'/'},localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>{if(options.storageFail)throw Error("Storage unavailable");storage.set(key,value);},removeItem:key=>storage.delete(key)},setTimeout:(fn,delay)=>{delays.push(delay);progressText.push(doc.getElementById("h3ProductionThinkingText")?.textContent);fn();return 0;},Event:class{constructor(type){this.type=type;}},fetch:async(url,options)=>{url=url.split('?revision=')[0];const body=options?.body?JSON.parse(options.body):null;if(url==='/api/production-assistant/conversation')return shared?shared.fetch(url,body,handler):{ok:false,status:404,json:async()=>({error:'Legacy synthetic server'})};requests.push({url,body});return shared?shared.fetch(url,body,handler):{ok:true,json:async()=>handler(url,body)};}};win.top=win.self=win;doc.defaultView=win;
  let generationReads=0;
  win.H3ProductionBridge={fingerprint:()=>JSON.stringify({duration:duration.value,final:final.value}),imageRefs:()=>['PRIVATE_PHOTO_BYTES'],bindings:()=>{const value={current_settings:{f:{duration:duration.value},images:['PRIVATE_PHOTO_BYTES']},current_prompt:final.value};Object.defineProperty(value,'current_generation',{enumerable:true,get:()=>{generationReads++;throw Error('Unused photo generation binding must not be read');}});return value;},refresh(){}};
  const edit={kind:'set',target:'main:1',before:'7',value:'5',path:'',args:'{}',label:'길이를 5초로 수정'};
  const mounted=P.mount(win);
  const $=id=>doc.getElementById(id);
  function respond(actions,extra={}){const states=[...(extra.pendingStates||[])];handler=(url,body)=>url.endsWith('/start')?{id:'fake-job'}:url.includes('/status')?(states.length?states.shift():{state:'done',production:{plan_id:'fake-plan',reply:'합성 답변 <img src=x onerror=alert(1)>',intent:'execute',reads:[],actions,auto_eligible:true,...extra}}):url.endsWith('/claim')?{action:actions[body.index]}:{ok:true};}
  return {win,doc,$,duration,final,button,requests,storage,edit,respond,delays,progressText,mounted,getGenerationReads:()=>generationReads};
}
class SharedServer{
  constructor(){this.data={revision:0,session_id:'synthetic-session',messages:[],active:null};this.next=0;this.blocked=false;}
  reply(value,ok=true){return {ok,status:ok?200:409,json:async()=>structuredClone(value)};}
  fetch(url,body,handler){
    if(this.blocked)return this.reply({error:'Synthetic network unavailable'},false);
    if(url==='/api/production-assistant/conversation'){
      if(!body)return this.reply(this.data);
      if(body.revision!==this.data.revision)return this.reply({error:'다른 기기에서 대화가 갱신됐습니다.'},false);
      if(body.operation==='import'){
        if(this.data.revision||this.data.messages.length)return this.reply({error:'Already imported'},false);
        this.data.messages=body.messages.map(row=>({...row,id:'import-'+(++this.next)}));this.data.revision++;return this.reply(this.data);
      }
      if(body.operation==='clear'){
        if(this.data.active)return this.reply({error:'Busy'},false);
        this.data.messages=[];this.data.session_id+='-new';this.data.revision++;return this.reply(this.data);
      }
    }
    const value=handler(url,body);
    if(url.endsWith('/start')){
      if(body.chat_revision!==this.data.revision||this.data.active)return this.reply({error:'Conversation changed'},false);
      this.data.messages.push({id:'user-'+(++this.next),role:'user',text:body.message});this.data.active={id:value.id,phase:'model',round:1};this.data.revision++;
      return this.reply({...value,chat_revision:this.data.revision,chat_user_id:this.data.messages.at(-1).id});
    }
    if(url.includes('/status')&&value.state==='done'&&this.data.active){
      const row={id:'assistant-'+(++this.next),role:'assistant',text:value.production.reply};
      if(value.production.actions.length)row.plan={state:'확인 대기',steps:value.production.actions.map(action=>({label:action.label,changes:action.kind==='set'?[{before:action.before,after:action.value}]:[]}))};
      this.data.messages.push(row);this.data.active=null;this.data.revision++;
      return this.reply({...value,chat_revision:this.data.revision,chat_message_id:row.id});
    }
    return this.reply(value);
  }
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
  // Hidden duplicate action editors must never be targets: render copies the
  // active editor over them. Only the canonical active input is exposed.
  const editor=app(),mode=new Node('select',editor.doc),joined=new Node('textarea',editor.doc),shots=new Node('div',editor.doc),shot=new Node('div',editor.doc),shotText=new Node('textarea',editor.doc),shotTime=new Node('input',editor.doc);
  mode.id='actionMode';mode.value='single';joined.id='actionText';joined.value='Current joined action.';shots.id='shots';shots.appendChild(shot);shot.appendChild(shotTime);shot.appendChild(shotText);shotText.value='Shadow action.';shotTime.type='number';
  for(const node of [shotText,shotTime])node.closest=selector=>selector==='#shots'?shots:selector==='.shot'?shot:null;
  editor.doc.nodes.set('actionMode',mode);editor.doc.nodes.set('actionText',joined);editor.doc.appControls.push(mode,joined,shotText,shotTime);
  let editorSnapshot=P.collect(editor.win,{map:new WeakMap(),next:0});
  assert(editorSnapshot.controls.some(item=>item.id==='actionText'));assert(!editorSnapshot.controls.some(item=>item.id.startsWith('shot-')));assert.equal(editorSnapshot.contexts[0].action_mode,'single');
  mode.value='timeline';editorSnapshot=P.collect(editor.win,{map:new WeakMap(),next:0});
  assert(!editorSnapshot.controls.some(item=>item.id==='actionText'));assert(editorSnapshot.controls.some(item=>item.id==='shot-1-action'&&item.label.includes('동작')));assert(editorSnapshot.controls.some(item=>item.id==='shot-1-time'));
  let hiddenPage=app();hiddenPage.duration.hidden=true;
  let hiddenSnapshot=P.collect(hiddenPage.win,{map:new WeakMap(),next:0});
  let hiddenRecord=[...hiddenSnapshot.nodes.values()].find(record=>record.entry.id==='duration');
  let hiddenAction={...hiddenPage.edit,target:hiddenRecord.entry.ref};
  assert(hiddenRecord.entry.hidden);P.preflight([hiddenAction],hiddenSnapshot,[]);P.setControl(hiddenRecord,hiddenAction);
  assert.equal(hiddenPage.duration.value,'5');assert(hiddenPage.duration.hidden,'A writable background field need not be forcibly unhidden');

  const mobile=app({width:390});const main=new Node('div',mobile.doc);main.id='singleApp';main.hidden=true;main.classList.toggle('view-hist',true);
  const makeColumn=new Node('div',mobile.doc);makeColumn.classList.toggle('make-col',true);main.appendChild(makeColumn);makeColumn.appendChild(mobile.button);
  const mainTab=new Node('button',mobile.doc);mainTab.onclick=()=>{main.hidden=false;};mobile.doc.nodes.set('singleTab',mainTab);
  const makeTab=new Node('button',mobile.doc);makeTab.onclick=()=>main.classList.toggle('view-hist',false);
  mobile.doc.querySelector=selector=>selector.includes('[data-view="make"]')?makeTab:null;
  mobile.win.getComputedStyle=node=>({display:node.classList?.contains('make-col')&&main.classList.contains('view-hist')?'none':'block'});
  const mobileSnapshot=P.collect(mobile.win,{map:new WeakMap(),next:0}),mobileRecord=[...mobileSnapshot.nodes.values()].find(record=>record.entry.id==='go');
  assert(mobileRecord.entry.hidden&&mobileRecord.entry.revealable);P.preflight([{...mobile.edit,kind:'click',target:mobileRecord.entry.ref}],mobileSnapshot,[]);P.clickControl(mobileRecord);
  assert(!main.hidden);assert(!main.classList.contains('view-hist'));assert.equal(mobile.button.clicks,1);

  const host=app(),embedded=app();embedded.win.top=host.win;
  const frame={id:'storyFrame',hidden:true,contentWindow:embedded.win,contentDocument:embedded.doc};host.doc.frames.push(frame);
  const storyTab=new Node('button',host.doc);storyTab.onclick=()=>{frame.hidden=false;};host.doc.nodes.set('storyTab',storyTab);
  const crossSnapshot=P.collect(host.win,{map:new WeakMap(),next:0}),crossRecord=[...crossSnapshot.nodes.values()].find(record=>record.entry.page==='story'&&record.entry.id==='go');
  assert(crossRecord,'Already-loaded inactive tabs stay addressable');P.clickControl(crossRecord);assert(!frame.hidden);assert.equal(embedded.button.clicks,1);
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
  await a.$('h3ProductionNew').click();assert.equal(a.duration.value,'7');assert(a.$('h3ProductionPlan').hidden);
  // New prompt bindings are resolved after each preceding input edit, and again
  // on the next request. No first-request prompt is cached for whole-queue apply.
  const bulkPage=app();bulkPage.$('h3ProductionAuto').checked=true;
  for(const revised of ['First revised scene.','Second revised scene.','Third revised scene.']){
    const promptRef=P.collect(bulkPage.win,{map:new WeakMap(),next:0}).controls.find(item=>item.id==='final').ref;
    const edits=[{...bulkPage.edit,target:promptRef,before:bulkPage.final.value,value:revised},{...bulkPage.edit,kind:'api',target:'',before:'',value:'',path:'/api/production-assistant/patch-queue',args:JSON.stringify({all_pending:true,prompt:'$current_prompt'})}];
    bulkPage.respond(edits);bulkPage.$('h3ProductionInput').value='수정하고 전체 반영';await bulkPage.$('h3ProductionSend').click();
    const applied=bulkPage.requests.filter(item=>item.url.endsWith('/execute')).at(-1);
    assert.equal(bulkPage.final.value,revised);assert.deepEqual(applied.body.args,{all_pending:true,prompt:revised});
  }
  a=app();a.respond([{...a.edit,kind:'click',target:'main:3',before:'',value:'',label:'대기열 추가'}]);a.$('h3ProductionInput').value='대기열에 추가해줘';await a.$('h3ProductionSend').click();await a.$('h3ProductionExecute').click();assert.equal(a.button.clicks,1);
  a=app({width:1440});assert(!a.$('h3ProductionPanel').hidden,'Desktop opens as an embedded chat sidebar');assert(a.doc.body.classList.contains('h3pa-open'));
  a.$('h3ProductionClose').click();assert(a.$('h3ProductionPanel').hidden);assert(!a.doc.body.classList.contains('h3pa-open'));assert(!a.$('h3ProductionToggle').hidden);
  const preference=a.storage;a=app({width:1440,storage:preference});assert(a.$('h3ProductionPanel').hidden,'Fold preference survives a new page');a.$('h3ProductionToggle').click();assert(!a.$('h3ProductionPanel').hidden);
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
  a=app();assert.equal(a.$('h3ProductionEffort').value,'high','Quality remains the default');a.respond([]);a.$('h3ProductionInput').value='합성 질문';await a.$('h3ProductionSend').click();assert.equal(a.requests.find(item=>item.url.endsWith('/start')).body.effort,'high');
  a.$('h3ProductionEffort').value='xhigh';a.$('h3ProductionEffort').onchange({stopImmediatePropagation(){}});a=app({storage:a.storage});assert.equal(a.$('h3ProductionEffort').value,'xhigh');a.respond([],{pendingStates:[{state:'generating',phase:'read',round:2}]});a.$('h3ProductionInput').value='다음 합성 질문';await a.$('h3ProductionSend').click();assert.equal(a.requests.find(item=>item.url.endsWith('/start')).body.effort,'xhigh');assert(a.delays.includes(600));assert(a.progressText.some(text=>text.includes('필요한 정보 조회')&&text.includes('2차 응답')));assert.equal(a.duration.value,'7');
  a=app();a.respond([],{pendingStates:[{state:'generating',phase:'model',round:1,cli_limit_s:600,cli_elapsed_s:181}]});a.$('h3ProductionInput').value='합성 긴 대기';await a.$('h3ProductionSend').click();assert(a.progressText.some(text=>text.includes('제한 600초')),'The UI shows the actual per-call timeout budget');
  const chatKey='h3simple.productionAssistant.chat.v1';
  a=app();a.respond([a.edit]);a.$('h3ProductionInput').value='합성 길이 요청';await a.$('h3ProductionSend').click();
  a.$('h3ProductionInput').value='아직 보내지 않은 합성 초안';a.$('h3ProductionInput').dispatchEvent({type:'input'});
  const savedChat=JSON.parse(a.storage.get(chatKey));assert.equal(savedChat.messages.length,2);assert.equal(savedChat.draft,'아직 보내지 않은 합성 초안');
  assert(!JSON.stringify(savedChat).includes('PRIVATE'),'Local transcript never includes snapshots, photo bindings or passwords');assert(!JSON.stringify(savedChat).includes('fake-plan'),'Executable plan IDs must not be persisted');assert(!JSON.stringify(savedChat).includes('main:1'),'Live DOM targets must not be persisted');
  const restored=app({storage:a.storage});assert.equal(restored.requests.length,0,'Restoring chat makes no API calls');assert.equal(restored.$('h3ProductionInput').value,savedChat.draft);assert(restored.$('h3ProductionLog').textContent.includes('합성 길이 요청'));assert(restored.$('h3ProductionLog').textContent.includes('기존: 7'));assert(restored.$('h3ProductionLog').textContent.includes('읽기 전용'));assert(restored.$('h3ProductionExecute').hidden);assert(!restored.$('h3ProductionLog').innerHTML.includes('<img'));
  await restored.$('h3ProductionExecute').click();assert.equal(restored.requests.length,0,'Restored proposals cannot replay even by invoking their handler');
  restored.respond([],{intent:'explain'});restored.$('h3ProductionInput').value='이어서 설명해줘';await restored.$('h3ProductionSend').click();const resumed=restored.requests.find(item=>item.url.endsWith('/start')).body;assert(resumed.conversation.some(item=>item.text==='합성 길이 요청'));assert(resumed.conversation.some(item=>item.text.includes('길이를 5초로 수정')));assert(!resumed.proposal,'Only a fresh plan can become executable');
  await restored.$('h3ProductionNew').click();assert(!restored.storage.has(chatKey),'New chat removes persisted conversation and draft');assert.equal(restored.$('h3ProductionInput').value,'');assert.equal(restored.duration.value,'7');const empty=app({storage:restored.storage});assert(empty.$('h3ProductionWelcome').hidden===false);assert.equal(empty.requests.length,0);
  a=app();a.respond([a.edit]);a.$('h3ProductionInput').value='합성 변경';await a.$('h3ProductionSend').click();await a.$('h3ProductionExecute').click();const receipt=app({storage:a.storage});assert(receipt.$('h3ProductionLog').textContent.includes('앱에 전달됨'));await receipt.$('h3ProductionExecute').click();assert.equal(receipt.requests.length,0);
  const interrupted=new Map([[chatKey,JSON.stringify({version:1,messages:[{role:'user',text:'합성 요청'},{role:'assistant',text:'합성 제안',plan:{state:'실행 중',steps:[{label:'합성 변경',changes:[]}]}}],draft:'',inFlight:true})],['h3simple.productionAssistant.auto.v1','true']]);a=app({storage:interrupted});assert(a.$('h3ProductionLog').textContent.includes('상태 확인'));assert(a.$('h3ProductionStatus').textContent.includes('자동 재실행하지'));assert.equal(a.requests.length,0,'An interrupted request must not auto-resume execution');
  a=app({storage:new Map([[chatKey,'{broken']])});assert(a.$('h3ProductionStatus').textContent.includes('복원하지 못'));a.respond([]);a.$('h3ProductionInput').value='새 합성 요청';await a.$('h3ProductionSend').click();assert.equal(JSON.parse(a.storage.get(chatKey)).version,1,'New messages recover from corrupt saved data');
  a=app({storageFail:true});a.respond([]);a.$('h3ProductionInput').value='합성 질문';await a.$('h3ProductionSend').click();assert(a.$('h3ProductionLog').textContent.includes('합성 답변'));assert(a.$('h3ProductionStorage').textContent.includes('저장하지 못'),'Unavailable storage must not block chat or silently claim persistence');
  const longHistory=Array.from({length:120},(_,index)=>({role:index%2?'assistant':'user',text:'합성 '+index}));a=app({storage:new Map([[chatKey,JSON.stringify({version:1,messages:longHistory,draft:''})]])});assert.equal(a.$('h3ProductionLog').children.filter(node=>node.getAttribute('data-role')).length,100);a.respond([]);a.$('h3ProductionInput').value='후속 합성 질문';await a.$('h3ProductionSend').click();assert.equal(a.requests.find(item=>item.url.endsWith('/start')).body.conversation.length,12,'Restored context stays within backend conversation limits');assert(JSON.parse(a.storage.get(chatKey)).messages.length<=100);
  assert(P.CHAT_STYLES.includes('min-width:1280px')&&P.CHAT_STYLES.includes('max-width:1279px')&&P.CHAT_STYLES.includes('min-height:0'),'Sidebar and full mobile chat have independent bounded scroll areas');
  const server=new SharedServer();let desktop=app({shared:server,width:1440,origin:'http://192.0.2.10:8190'}),phone=app({shared:server,width:390,coarse:true,origin:'http://tailscale.example:8190'});await Promise.all([desktop.mounted.ready,phone.mounted.ready]);
  desktop.respond([desktop.edit]);desktop.$('h3ProductionInput').value='PC 합성 질문';await desktop.$('h3ProductionSend').click();assert(!desktop.$('h3ProductionExecute').hidden,'The originating page retains its reviewed execution button');
  phone.$('h3ProductionInput').value='휴대폰 미전송 초안';phone.$('h3ProductionInput').dispatchEvent({type:'input'});await phone.mounted.sync();assert(phone.$('h3ProductionLog').textContent.includes('PC 합성 질문'));assert(phone.$('h3ProductionLog').textContent.includes('기존: 7'));assert(phone.$('h3ProductionExecute').hidden,'Other devices restore proposals read-only');assert.equal(phone.$('h3ProductionInput').value,'휴대폰 미전송 초안');
  phone.respond([],{intent:'explain'});phone.$('h3ProductionInput').value='휴대폰 후속 질문';await phone.$('h3ProductionSend').click();assert(phone.requests.find(item=>item.url.endsWith('/start')).body.conversation.some(row=>row.text==='PC 합성 질문'));
  await desktop.$('h3ProductionExecute').click();assert(!desktop.requests.some(item=>item.url.endsWith('/claim')),'A new turn from another device invalidates the old executable card');assert.equal(desktop.duration.value,'7');assert(desktop.$('h3ProductionLog').textContent.includes('휴대폰 후속 질문'));
  desktop.$('h3ProductionInput').value='PC 별도 초안';desktop.$('h3ProductionInput').dispatchEvent({type:'input'});await phone.$('h3ProductionNew').click();await desktop.mounted.sync();assert(!desktop.$('h3ProductionLog').textContent.includes('PC 합성 질문'));assert.equal(desktop.$('h3ProductionInput').value,'PC 별도 초안','Remote reset keeps this device draft');
  const renewed=app({shared:server,storage:desktop.storage});await renewed.mounted.ready;assert.equal(renewed.$('h3ProductionInput').value,'PC 별도 초안');assert(!renewed.$('h3ProductionLog').textContent.includes('PC 합성 질문'),'A cleared server chat cannot be resurrected by old browser history');
  const importedServer=new SharedServer(),oldStorage=new Map([[chatKey,JSON.stringify({version:1,messages:[{role:'user',text:'기존 합성 대화'}],draft:'기존 초안'})]]);const migrated=app({shared:importedServer,storage:oldStorage});await migrated.mounted.ready;const other=app({shared:importedServer});await other.mounted.ready;assert(other.$('h3ProductionLog').textContent.includes('기존 합성 대화'));assert.equal(migrated.$('h3ProductionInput').value,'기존 초안');
  server.data.active={id:'another-device',phase:'model',round:1};server.data.revision++;await desktop.mounted.sync();assert(desktop.$('h3ProductionSend').disabled);assert(!desktop.$('h3ProductionThinking').hidden);server.data.messages.push({id:'background',role:'assistant',text:'다른 기기에서 완료한 합성 응답'});server.data.active=null;server.data.revision++;await desktop.mounted.sync();assert(desktop.$('h3ProductionLog').textContent.includes('완료한 합성 응답'));assert(!desktop.$('h3ProductionEffort').disabled);
  const beforeClear=server.data.messages.length;desktop.$('h3ProductionInput').value='오프라인 초안';server.blocked=true;await desktop.$('h3ProductionNew').click();assert.equal(server.data.messages.length,beforeClear);assert.equal(desktop.$('h3ProductionInput').value,'오프라인 초안');assert(desktop.$('h3ProductionStorage').textContent.includes('덮어쓰지'));server.blocked=false;
  a=app({width:390});await a.mounted.ready;a.respond([],{intent:'explain'});a.$('h3ProductionToggle').click();
  a.$('h3ProductionInput').value='합성 알림 질문';const notified=a.$('h3ProductionSend').click();a.$('h3ProductionClose').click();await notified;
  assert.equal(a.$('h3ProductionToggle').getAttribute('data-unread'),'true');assert(a.$('h3ProductionToggle').getAttribute('aria-label').includes('새 답변'));
  a.$('h3ProductionToggle').click();assert.equal(a.$('h3ProductionToggle').getAttribute('data-unread'),'false');
  a.$('h3ProductionPanel').dispatchEvent({type:'pointerenter'});a.$('h3ProductionInput').value='확인 중인 합성 질문';await a.$('h3ProductionSend').click();assert.equal(a.$('h3ProductionPanel').getAttribute('data-unread'),'false','Replies being read do not remain unread');
  a.$('h3ProductionPanel').dispatchEvent({type:'pointerleave'});a.doc.hidden=true;a.$('h3ProductionInput').value='백그라운드 합성 질문';await a.$('h3ProductionSend').click();assert.equal(a.$('h3ProductionPanel').getAttribute('data-unread'),'true');
  const unreadServer=new SharedServer();unreadServer.data.messages=[{id:'reply-one',role:'assistant',text:'합성 공유 답변'}];unreadServer.data.revision=1;
  let receiver=app({width:390,shared:unreadServer});await receiver.mounted.ready;assert.equal(receiver.$('h3ProductionToggle').getAttribute('data-unread'),'true');receiver.$('h3ProductionToggle').click();receiver.$('h3ProductionClose').click();
  const marker=JSON.parse(receiver.storage.get('h3simple.productionAssistant.read.v1'));assert.equal(marker.id,'reply-one');assert(!JSON.stringify(marker).includes('합성'),'Read markers contain IDs only, not conversation text');
  receiver=app({width:390,shared:unreadServer,storage:receiver.storage});await receiver.mounted.ready;assert.equal(receiver.$('h3ProductionToggle').getAttribute('data-unread'),'false','An acknowledged shared reply stays read after reload');
  unreadServer.data.messages.push({id:'reply-two',role:'assistant',text:'다른 기기에서 도착한 합성 답변'});unreadServer.data.revision++;await receiver.mounted.sync();assert.equal(receiver.$('h3ProductionToggle').getAttribute('data-unread'),'true','A new shared reply creates an unread dot');
  const resumedServer=new SharedServer();resumedServer.data.revision=1;resumedServer.data.active={id:'synthetic-existing-job',phase:'model',round:2,created:Date.now()/1000-181};
  const resumedPage=app({shared:resumedServer,width:390});await resumedPage.mounted.ready;
  assert(resumedPage.$('h3ProductionThinkingText').textContent.includes('Grok 응답 대기'));assert(resumedPage.$('h3ProductionThinkingText').textContent.includes('2차 응답'));assert(resumedPage.$('h3ProductionThinkingText').textContent.includes('초'));
  assert(!resumedPage.$('h3ProductionThinkingText').textContent.includes('다른 기기'));assert(!resumedPage.$('h3ProductionCancel').hidden);assert(resumedPage.$('h3ProductionSend').disabled);assert(resumedPage.$('h3ProductionStatus').textContent.includes('이어서 확인'));
  assert(!resumedPage.requests.some(item=>item.url.endsWith('/start')||item.url.endsWith('/claim')),'Refreshing follows the existing request without replay');
  Object.assign(resumedServer.data.active,{cli_stage:'thinking',cli_signals:42,cli_idle_s:2,cli_limit_s:600,thought:'PRIVATE_THOUGHT'});
  await resumedPage.mounted.sync();assert(resumedPage.$('h3ProductionThinkingText').textContent.includes('추론 중'));assert(resumedPage.$('h3ProductionThinkingText').textContent.includes('진행 신호 42회'));assert(resumedPage.$('h3ProductionThinkingText').textContent.includes('마지막 수신 2초 전'));
  assert(!resumedPage.$('h3ProductionThinkingText').textContent.includes('PRIVATE'));
  resumedServer.data.active.cli_stage='answer';await resumedPage.mounted.sync();assert(resumedPage.$('h3ProductionThinkingText').textContent.includes('답변 작성 중'));
  await resumedPage.$('h3ProductionCancel').click();assert.equal(resumedPage.requests.find(item=>item.url.endsWith('/cancel')).body.id,'synthetic-existing-job','Reloaded page cancellation targets only the known helper request');
  resumedServer.data.active=null;resumedServer.data.messages.push({id:'restored-completion',role:'assistant',text:'새로고침 후 완료된 합성 답변'});resumedServer.data.revision++;await resumedPage.mounted.sync();
  assert(resumedPage.$('h3ProductionThinking').hidden);assert(resumedPage.$('h3ProductionCancel').hidden);assert(!resumedPage.$('h3ProductionSend').disabled);assert(resumedPage.$('h3ProductionStatus').textContent.includes('처리가 끝났'));assert(resumedPage.$('h3ProductionLog').textContent.includes('완료된 합성 답변'));
  assert(!P.progressText({phase:'read',cli_stage:'thinking',cli_signals:42},12).includes('추론 중'),'App reads do not show an old model stage');
  assert(!P.progressText({phase:'model',cli_stage:'PRIVATE_THOUGHT',cli_signals:'PRIVATE'},12).includes('PRIVATE'));
  console.log('Production assistant UI passed: live stages, shared progress, resumed request progress/cancel/completion, unread notifications and non-replayed actions.');
})().catch(error=>{console.error(error);process.exitCode=1;});
