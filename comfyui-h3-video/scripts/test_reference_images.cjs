// Synthetic strings and FileReaders only; no photos, browser, network or jobs.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
const section=(start,end)=>script.slice(script.indexOf(start),script.indexOf(end,script.indexOf(start)));
const get=()=>({value:''}),started=[],waiting=[],errors=[];let limit=9;
const context=vm.createContext({$:get,console,images:[],bulkEditingIds:[],maxImgs:()=>limit,drawThumbs(){},setStatus:message=>errors.push(message),
  FileReader:class{readAsDataURL(file){started.push(file.id);waiting.push(()=>{if(file.fail)this.onerror();else{this.result=`synthetic-data-${file.id}`;this.onload();}});}}
});
vm.runInContext(section('function pics(', '// 영상 길이'),context);
vm.runInContext(section('const FACE_REFERENCE_RETENTION=', 'function build('),context);
vm.runInContext(section('let photoImportQueue=', 'function photoLabel('),context);
vm.runInContext(section('function readPhotoDataUrl(', 'async function submitIndividualPhotos('),context);
const raw='subject_definitions: Custom person from <Picture 1>.  \n\nsummary: Keep this exact summary.\n\nretention_analysis: Preserve custom accessories.  \n\ndetailed_description: Original waist instruction.\nAt 2.000 seconds, a synthetic gesture.\n\noverall_soundscape: Unchanged sound.\n\nnon_diegetic_music: N/A\n';
for(let count=2;count<=9;count++){
  const updated=context.withFaceReferenceRules(raw,count);
  for(let index=1;index<=count;index++)assert(updated.includes(`<Picture ${index}>`));
  assert(!updated.includes(`<Picture ${count+1}>`));
  assert.equal(context.stripFaceReferenceRules(updated),raw,'Only managed reference paragraphs may change');
  assert.equal(context.withFaceReferenceRules(updated,count),updated,'Repeated application must not duplicate identity rules');
  assert(updated.includes('not separate characters or a sequence of poses'));
  assert(updated.includes('Supplementary views do not request a head turn'));
  assert(updated.includes('existing instructions for the upper-body pose and lower-body movement'));
}
assert.equal(context.withFaceReferenceRules(context.withFaceReferenceRules(raw,9),2),context.withFaceReferenceRules(raw,2));
assert.equal(context.withFaceReferenceRules(context.withFaceReferenceRules(raw,9),1),raw);
const freeform='Manual freeform text.\r\nKeep whitespace and timing.   \n';
assert.equal(context.stripFaceReferenceRules(context.withFaceReferenceRules(freeform,9)),freeform);
const settle=()=>new Promise(setImmediate),file=(id,fail=false)=>({id,type:'image/png',fail});
(async()=>{
  const first=context.addFiles([file(1),file(2)]),second=context.addFiles([file(3)]);
  await settle();assert.deepEqual(started,[1],'Only the first selected file is read initially');
  waiting.shift()();await settle();assert.deepEqual(started,[1,2]);assert.deepEqual([...context.images],['synthetic-data-1']);
  waiting.shift()();await settle();assert.deepEqual(started,[1,2,3]);
  waiting.shift()();await first;await second;assert.deepEqual([...context.images],['synthetic-data-1','synthetic-data-2','synthetic-data-3']);
  context.images.length=0;started.length=0;
  const many=context.addFiles(Array.from({length:1001},(_,index)=>file(index)));
  await settle();for(let index=0;index<9;index++){assert.equal(waiting.length,1);waiting.shift()();await settle();}await many;
  assert.equal(started.length,9,'Do not decode files beyond the nine available reference slots');
  assert.deepEqual([...context.images],Array.from({length:9},(_,index)=>`synthetic-data-${index}`));
  context.images.length=0;started.length=0;
  const failure=context.addFiles([file(10,true),file(11)]);await settle();waiting.shift()();await failure;
  assert.equal(errors.length,1);assert.equal(context.images.length,0);assert.deepEqual(started,[10],'A failed primary photo must not silently promote a later photo');
  const recovery=context.addFiles([file(12)]);await settle();waiting.shift()();await recovery;assert.deepEqual([...context.images],['synthetic-data-12']);
  const edit=context.addFiles([file(13)]);await settle();context.bulkEditingIds.push('synthetic-edit');waiting.shift()();await edit;
  assert.deepEqual([...context.images],['synthetic-data-12'],'An in-flight read cannot alter photos during bulk editing');
  console.log('Reference-image checks passed: 2–9 roles, scoped/idempotent manual updates, original text preservation and ordered bounded file reads.');
})().catch(error=>{console.error(error);process.exitCode=1;});
