// Fake DOM and count-only responses; no browser, tasks or media are accessed.
const assert=require('node:assert/strict'),P=require('../simple_ui/bulk-progress.js');
class Element{
  constructor(){this.hidden=false;this.textContent='';this.value=0;this.parts=new Map();}
  setAttribute(){}removeAttribute(name){if(name==='value')this.value=null;}
  querySelector(key){if(!this.parts.has(key))this.parts.set(key,new Element());return this.parts.get(key);}
  appendChild(){}prepend(node){this.host=node;}
}
const doc={hidden:false,head:new Element(),body:new Element(),createElement:()=>new Element(),querySelector:()=>null,addEventListener(){}};
let value={state:'idle'},requests=0;const delays=[];
const win={document:doc,clearTimeout(){},setTimeout(fn,delay){delays.push(delay);return 1;},fetch:async()=>{requests++;return {ok:true,json:async()=>value};}};
(async()=>{
  const ui=P.mount(win);await new Promise(setImmediate);const host=doc.body.host;
  assert(host.hidden);ui.prepare();assert(!host.hidden);assert(host.querySelector('[data-bulk-title]').textContent.includes('대상 확인'));
  await new Promise(setImmediate);assert(host.querySelector('[data-bulk-title]').textContent.includes('대상 확인'),'An old idle/completed record must not finish a new request');
  value={state:'running',all_pending:true,total:600,processed:120,succeeded:118,failed:2,percent:20,elapsed_seconds:300};
  await ui.poll();assert.equal(host.querySelector('progress').value,20);assert(host.querySelector('[data-bulk-counts]').textContent.includes('처리 120/600 · 성공 118 · 실패 2 · 05:00'));assert(delays.includes(1000));
  const other=P.mount(win);await new Promise(setImmediate);assert(!doc.body.host.hidden,'Another page restores the shared progress without resubmitting writes');
  value={...value,state:'done',processed:600,succeeded:598,failed:2,percent:100,finished_age_seconds:0};await ui.poll();assert(host.querySelector('[data-bulk-title]').textContent.includes('일부 미적용'));
  value={...value,state:'error',processed:121,succeeded:119,percent:20.2};await ui.poll();assert(host.querySelector('[data-bulk-title]').textContent.includes('중단'));
  doc.hidden=true;const before=requests;await ui.poll();assert.equal(requests,before);doc.hidden=false;
  value={...value,state:'done',finished_age_seconds:61};await ui.poll();assert(host.hidden);
  ui.prepare();ui.complete({all_pending:true,jobs:[],failed:[],target_count:0});assert.equal(host.querySelector('progress').value,100);
  console.log('Bulk progress passed: live counts, partial failures, shared restoration, hidden-page pause and no write requests.');
})().catch(error=>{console.error(error);process.exitCode=1;});
