const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const page=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const code=page.slice(page.indexOf('const REFERENCE_STYLE_CURRENT ='),page.indexOf('function load(){'));
const context={S:{}};vm.createContext(context);
vm.runInContext(code+'\nglobalThis.style=REFERENCE_STYLE_CURRENT;globalThis.prefix=OPENING_POSE_PREFIX;',context);
const run=s=>vm.runInContext(s,context);
function sample(){return {f:{style:context.style,keep:'Synthetic identity.',summary:'Synthetic sequence.'},shots:[['0','Raise a synthetic hand.'],['2','Lower the synthetic hand.']],seed:'123',final:null};}
context.saved=sample();const before=structuredClone(context.saved);
assert.equal(run('applyOpeningPoseSaved(saved)'),true);
assert.equal(context.saved.shots[0][1],context.prefix+'\n\n'+before.shots[0][1]);
assert.equal(JSON.stringify(context.saved.f),JSON.stringify(before.f));
assert.equal(JSON.stringify(context.saved.shots[1]),JSON.stringify(before.shots[1]));
assert.equal(context.saved.shots[0][0],'0');assert.equal(context.saved.seed,'123');
assert.equal(run('applyOpeningPoseSaved(saved)'),false);
for(const marker of ['','[Shot 1] ']){
  context.saved=sample();context.saved.final='summary: Synthetic summary.\n\ndetailed_description: '+context.style+' '+marker+'A manual synthetic action.\n\noverall_soundscape: Synthetic audio.';
  const old=context.saved.final;
  assert.equal(run('applyOpeningPoseSaved(saved)'),true);
  assert.equal(context.saved.final,old.replace(marker+'A manual synthetic action.',marker+context.prefix+'\n\nA manual synthetic action.'));
  assert.equal(run('applyOpeningPoseSaved(saved)'),false);
}
context.saved=sample();context.saved.final='Fully customized synthetic prompt.';
const custom=JSON.stringify(context.saved);assert.equal(run('applyOpeningPoseSaved(saved)'),null);assert.equal(JSON.stringify(context.saved),custom);
context.saved=sample();context.saved.shots[0][0]='2';assert.equal(run('applyOpeningPoseSaved(saved)'),null);
context.saved=sample();context.saved.f.style='Unrelated camera.';assert.equal(run('applyOpeningPoseSaved(saved)'),null);
context.saved=sample();context.saved.shots[0][1]='';context.saved.final='detailed_description: '+context.style+'\n\noverall_soundscape: Synthetic audio.';
assert.equal(run('applyOpeningPoseSaved(saved)'),true);
assert(context.saved.final.endsWith(context.prefix+'\n\noverall_soundscape: Synthetic audio.'));
assert.equal(run('applyOpeningPoseSaved(saved)'),false);
// A completed migration must not reinsert text after a later explicit edit.
const loadCode=page.slice(page.indexOf('function load(){'),page.indexOf('// ---------- 로컬 CPU 프롬프트 도우미'));
const store=new Map([['form',JSON.stringify(sample())],['form:opening-pose-v1','done']]);
Object.assign(context,{KEY:'form',KEY_M:'model',EXAMPLE:sample(),localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v)},apply:s=>context.applied=s,$:()=>({}),save:()=>{},manualFinal:false});
vm.runInContext(loadCode+'\nload();',context);
assert.equal(context.applied.shots[0][1],'Raise a synthetic hand.');
console.log('Opening-action draft tests passed: common style and other scenes preserved, manual edits protected, insertion idempotent.');
