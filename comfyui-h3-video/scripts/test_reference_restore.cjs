// Synthetic rollback checks only; no localStorage, browser, server or user records.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const file=process.argv[2]||path.join(__dirname,'../simple_ui/index.html');
const source=fs.readFileSync(file,'utf8');
const context=vm.createContext({S:{anchor:false}});
vm.runInContext(source.slice(source.indexOf('const REFERENCE_STYLE_CURRENT ='),source.indexOf('function load(){')),context);
const run=code=>vm.runInContext(code,context);
run('globalThis.removed=REFERENCE_STYLE_REMOVED;globalThis.current=REFERENCE_STYLE_CURRENT;globalThis.background=REFERENCE_BACKGROUND_REMOVED;globalThis.scope=REFERENCE_SCOPE_REMOVED;globalThis.subject=REFERENCE_SUBJECT_REMOVED;globalThis.restoredSubject=REFERENCE_SUBJECT_SINGLE;');
for(const style of context.removed){
  const keep='Preserve synthetic clothes. '+context.background;
  context.saved={f:{style,keep,subject:context.subject+' A custom subject detail.',summary:'A later synthetic summary.'},shots:[[0,'A later custom movement.']],seed:'321',
    final:'subject_definitions: '+context.subject+' A custom subject detail.\n\nsummary: A later synthetic summary.\n\nretention_analysis: '+keep+' '+context.scope+'\n\ndetailed_description: '+style+' A later custom movement.\n\noverall_soundscape: Later synthetic audio.'};
  assert.equal(run('restoreAnchoredSaved(saved)'),true);
  assert.equal(context.saved.f.style,context.current);
  assert(context.saved.f.subject.startsWith(context.restoredSubject));
  for(const fragment of ['A custom subject detail.','A later synthetic summary.','A later custom movement.','Later synthetic audio.','Preserve synthetic clothes.'])assert(context.saved.final.includes(fragment));
  assert(!context.saved.final.includes(context.background));assert(!context.saved.final.includes(context.scope));
  assert.equal(context.saved.seed,'321');assert.equal(context.saved.shots[0][1],'A later custom movement.');
  assert.equal(run('restoreAnchoredSaved(saved)'),false);
}
assert.equal(run('restoreAnchoredModel()'),true);assert.equal(context.S.anchor,true);
context.S.anchor=false;assert.equal(run('restoreAnchoredModel()'),false);assert.equal(context.S.anchor,false,'A later explicit opt-out remains possible');
context.saved={f:{style:context.removed[0],keep:'Synthetic keep.'},final:'An entirely customized manual prompt.'};
const before=JSON.stringify(context.saved);assert.equal(run('restoreAnchoredSaved(saved)'),false);assert.equal(JSON.stringify(context.saved),before);
context.saved={f:{style:'An unrelated camera policy.',keep:'Custom retention.'},final:null};assert.equal(run('restoreAnchoredSaved(saved)'),false);
const anchoredPrevious=context.removed.at(-1);
context.saved={f:{style:anchoredPrevious,keep:'Keep a custom appearance instruction.',subject:'A custom person from <Picture 1>.',summary:'A later custom summary.'},shots:[[0,'A later custom action.']],seed:'123',
  final:'subject_definitions: A custom person from <Picture 1>.\n\nsummary: A later custom summary.\n\nretention_analysis: Keep a custom appearance instruction.\n\ndetailed_description: '+anchoredPrevious+' A later custom action.\n\noverall_soundscape: Custom audio.'};
const oldSaved=JSON.parse(JSON.stringify(context.saved));
assert.equal(run('restoreAnchoredSaved(saved)'),true);
assert.equal(context.saved.final,oldSaved.final.replace(anchoredPrevious,context.current),'Only the known common style may change in an already anchored draft');
for(const key of ['keep','subject','summary'])assert.equal(context.saved.f[key],oldSaved.f[key]);
assert.equal(JSON.stringify(context.saved.shots),JSON.stringify(oldSaved.shots));
assert.equal(context.saved.seed,oldSaved.seed);
console.log('Anchored defaults passed: known policies restored, later custom text retained, manual overrides protected, idempotence and explicit opt-out.');
