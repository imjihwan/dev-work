// Synthetic DOM and pause state only. Never connects to the app or reads media.
const assert=require('node:assert/strict'),P=require('../simple_ui/queue-pause.js');
class Element{constructor(){this.children=[];this.textContent='';this.disabled=false;this.style={};this.attributes={};}appendChild(node){this.children.push(node);}setAttribute(key,value){this.attributes[key]=value;}}
const host=new Element(),doc={hidden:false,getElementById:()=>host,createElement:()=>new Element(),addEventListener(){}};
let state={supported:true,paused:false,state:'running'},release=null;const requests=[];
const win={document:doc,clearTimeout(){},setTimeout(){},fetch:async(url,options)=>{requests.push(options||{});if(options?.method==='POST'){await new Promise(resolve=>release=resolve);state={supported:true,paused:JSON.parse(options.body).paused,state:'finishing'};}return {ok:true,json:async()=>state};}};
(async()=>{
 const ui=P.mount(win);await new Promise(setImmediate);assert.equal(ui.button.textContent,'작업 일시정지');
 const pending=ui.button.onclick();assert(ui.button.disabled);await ui.button.onclick();assert.equal(requests.filter(r=>r.method==='POST').length,1);
 release();await pending;assert.equal(ui.button.textContent,'작업 재개');assert(ui.status.textContent.includes('현재 작업 완료 후'));
 state={supported:true,paused:true,state:'paused'};await ui.poll();assert(ui.status.textContent.includes('일시정지됨'));
 const resume=ui.button.onclick();release();await resume;assert.deepEqual(JSON.parse(requests.at(-1).body),{paused:false});
 state={supported:false,state:'unsupported'};await ui.poll();assert(ui.button.disabled);assert(ui.status.textContent.includes('ComfyUI 재시작'));
 console.log('Queue pause UI passed: explicit state, duplicate taps, finish-current status and unsupported activation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
