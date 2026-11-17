// Read-only preview with fake inputs, fetch and timing. No browser, real text or media.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const start=html.indexOf('// Local translation preview (read-only)'),end=html.indexOf('// End local translation preview.');
assert(start>=0&&end>start);
class Element{
  constructor(tag='DIV',id=''){this.tagName=tag.toUpperCase();this.id=id;this.value='';this.children=[];this.isConnected=true;this.hidden=false;this.open=false;this.selectionStart=0;this.selectionEnd=0;this.textContent='';this.parentElement=null;}
  append(...nodes){for(const node of nodes){node.parentElement=this;this.children.push(node);}}
  insertAdjacentElement(where,node){assert.equal(where,'afterend');this.preview=node;node.parentElement=this.parentElement;}
  closest(selector){return selector==='.shot'&&this.inShot?this.parentElement:null;}
  remove(){this.isConnected=false;}
  set innerHTML(value){throw Error('Translation must never be inserted as HTML');}
}
const elements=new Map(),events={},storage=[],calls=[];
const get=id=>{if(!elements.has(id))elements.set(id,new Element('INPUT',id));return elements.get(id);};
const doc={activeElement:null,hidden:false,createElement:tag=>new Element(tag),addEventListener:(name,handler)=>events[name]=handler};
const context=vm.createContext({console,$:get,document:doc,AbortController,setTimeout:(fn,delay)=>setTimeout(fn,Math.min(delay,3)),clearTimeout,
  localStorage:{getItem:()=>null,setItem:(key,value)=>storage.push([key,value])},
  fetch:async(url,options)=>{calls.push({url,options,body:JSON.parse(options.body)});return{ok:true,status:200,json:async()=>({text:'합성 번역: '+JSON.parse(options.body).text})};}});
vm.runInContext(html.slice(start,end),context);
const run=code=>vm.runInContext(code,context),sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const wait=async predicate=>{for(let i=0;i<200;i++){if(predicate())return;await sleep(5);}throw Error('Synthetic translation did not settle');};
const panel=field=>run('TRANSLATION.panels').get(field);
const complete=field=>{const p=panel(field);return p&&p.summary.textContent.match(/(\d+)\/(\d+)/)?.slice(1).every((value,_,values)=>value===values[0]);};
(async()=>{
  context.initTranslationPreview();assert.equal(get('translationToggle').checked,false);assert.equal(get('translationEngine').value,'quality');assert.equal(calls.length,0,'Disabled preview must not read or submit inputs');
  const field=get('style');field.tagName='TEXTAREA';field.value='First synthetic sentence.\n\nSecond stable synthetic sentence.\n\nThird stable synthetic sentence.';doc.activeElement=field;
  const original=field.value;
  context.setTranslationEnabled(true);await wait(()=>complete(field));
  assert.equal(field.value,original);assert.equal(calls.length,3);assert.equal(panel(field).box.open,true);
  assert(panel(field).body.textContent.includes('합성 번역'));assert(panel(field).body.className.includes('translation-preview-body'));
  context.scheduleTranslation(field,0);await sleep(15);assert.equal(calls.length,3,'Unchanged text must use memory cache');
  field.value=field.value.replace('First','Changed first');context.scheduleTranslation(field,0);await wait(()=>calls.length===4&&complete(field));
  assert.equal(calls.length,4,'Changing one paragraph must not retranslate unchanged paragraphs');
  field.value='Synthetic programmatic field update.';context.refreshTranslationPreview();await wait(()=>complete(field)&&panel(field).body.textContent.includes(field.value));
  const long=('Synthetic long sentence with <Picture 1> at 00:01.000 toward {{face_side}}. '.repeat(300));
  const chunks=Array.from(context.translationChunks(long));assert.equal(chunks.join(''),long);assert(chunks.every(piece=>piece.length<=900));
  for(const piece of chunks){assert.equal((piece.match(/<Picture/g)||[]).length,(piece.match(/<Picture 1>/g)||[]).length);assert.equal((piece.match(/\{\{/g)||[]).length,(piece.match(/\{\{face_side\}\}/g)||[]).length);}
  assert.equal(Array.from(context.translationChunks('x'.repeat(2500))).join(''),'x'.repeat(2500));
  assert.equal(Array.from(context.translationChunks('a'.repeat(885)+'<Picture 1>')).join(''),'a'.repeat(885)+'<Picture 1>');
  field.value=long;context.scheduleTranslation(field,0);await wait(()=>complete(field)&&panel(field).body.textContent.includes('{{face_side}}'));
  assert.equal(field.value,long);assert(calls.every(call=>call.url==='/api/translate'&&call.body.text.length<=480&&call.body.engine==='quality'));
  const beforeMode=calls.length;context.setTranslationEngine('fast');await wait(()=>calls.length>beforeMode&&complete(field));
  assert(calls.slice(beforeMode).every(call=>call.body.engine==='fast'&&call.body.text.length<=900));
  assert.equal(field.value,long,'Changing translation engine must not alter original text');
  const beforeQuality=calls.length;context.setTranslationEngine('quality');await wait(()=>calls.length>beforeQuality&&complete(field));

  // Selected text only, including inputs longer than the automatic whole-field bound.
  field.value='Prefix '.repeat(10000)+'Selected synthetic phrase.';field.selectionStart=field.value.length-26;field.selectionEnd=field.value.length;
  const selected=field.value.slice(field.selectionStart,field.selectionEnd),beforeSelection=calls.length;
  context.scheduleTranslation(field,0);await wait(()=>calls.length>beforeSelection&&complete(field));
  assert.equal(calls.at(-1).body.text,selected);assert(panel(field).summary.textContent.includes('선택 부분'));
  field.selectionStart=field.selectionEnd=0;const hugeCount=calls.length;context.scheduleTranslation(field,0);await sleep(15);
  assert.equal(calls.length,hugeCount);assert(panel(field).body.textContent.includes('64,000자'));

  // A late response must not overwrite newer input, even if fetch ignores abort.
  const releases=[];context.fetch=(url,options)=>{calls.push({url,options,body:JSON.parse(options.body)});return new Promise(resolve=>releases.push(resolve));};
  field.value='Synthetic stale response.';context.scheduleTranslation(field,0);await wait(()=>releases.length===1);
  const signal=calls.at(-1).options.signal;field.value='Synthetic fresh response.';context.scheduleTranslation(field,0);await wait(()=>releases.length===2);
  assert(signal.aborted);
  releases[1]({ok:true,status:200,json:async()=>({text:'최신 합성 번역'})});await wait(()=>panel(field).body.textContent==='최신 합성 번역');
  releases[0]({ok:true,status:200,json:async()=>({text:'지연된 합성 번역'})});await sleep(10);assert.equal(panel(field).body.textContent,'최신 합성 번역');
  assert.equal(field.value,'Synthetic fresh response.');

  let attempts=0;context.fetch=async()=>{attempts++;return attempts===1?{ok:false,status:409,json:async()=>({busy:true,error:'합성 CPU 대기'})}:{ok:true,status:200,json:async()=>({text:'대기 뒤 합성 번역'})};};
  field.value='Synthetic busy request.';context.scheduleTranslation(field,0);await wait(()=>panel(field).body.textContent==='대기 뒤 합성 번역');assert.equal(attempts,2);
  context.fetch=async()=>({ok:true,status:200,json:async()=>({text:'Untranslated synthetic text.',warning:'Synthetic fallback'})});
  field.value='Synthetic protected-label fallback.';context.scheduleTranslation(field,0);await wait(()=>panel(field).summary.textContent.includes('원문 유지'));
  assert(!run('TRANSLATION.cache').has(field.value),'Fallback must remain explicit and retryable');
  context.fetch=async()=>({ok:true,status:200,json:async()=>({text:'<img src=x onerror=synthetic>'})});
  field.value='Synthetic literal markup.';context.scheduleTranslation(field,0);await wait(()=>panel(field).body.textContent.includes('<img'));
  const beforeKorean=calls.length;field.value='이 문장은 한국어입니다.';context.scheduleTranslation(field,0);await sleep(15);assert.equal(calls.length,beforeKorean);
  context.setTranslationEnabled(false);assert(panel(field).box.hidden);assert.equal(get('translationToggle').checked,false);
  const shot=new Element(),time=new Element('INPUT'),motion=new Element('TEXTAREA'),remove=new Element('BUTTON');motion.inShot=true;motion.value='Synthetic shot action.';shot.append(time,motion,remove);
  context.setTranslationEnabled(true);context.scheduleTranslation(motion,0);await wait(()=>panel(motion)&&complete(motion));
  assert.equal(shot.children[2],remove,'The scene delete button must retain its original grid cell');assert.equal(shot.children[3],panel(motion).box);
  context.setTranslationEnabled(false);
  assert(storage.every(([key,value])=>(key==='h3simple.translationPreview.v1'&&['0','1'].includes(value))||(key==='h3simple.translationEngine.v1'&&['quality','fast'].includes(value))),'Only feature and engine choices may be persisted');
  console.log('Translation preview passed: opt-in, lossless long-text splitting, paragraph cache, selected text, unchanged source, stale-response cancellation, busy retry, explicit fallback and literal rendering.');
})().catch(error=>{console.error(error);process.exitCode=1;});
