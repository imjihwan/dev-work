// Synthetic File handles, directory entries and fake DOM only. No disk photos or network.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
const start=script.indexOf('// Folder photo batch:'),end=script.indexOf('// End folder photo batch.');
assert(start>=0&&end>start);assert(/id="photoFolderFiles"[^>]*webkitdirectory[^>]*multiple/.test(html));
function photo(name,relative=name,type='image/png'){return{name,webkitRelativePath:relative,type,size:100,lastModified:123};}
function setup(){
  const nodes=new Map(),requests=[];
  const get=id=>{if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',disabled:false,open:false,webkitdirectory:false,classList:{add(){},remove(){}},click(){this.clicks=(this.clicks||0)+1;},scrollIntoView(){}});return nodes.get(id);};
  const context=vm.createContext({console,$:get,setTimeout,queueSubmitting:false,editingJobId:null,bulkEditingIds:[],CAT:{},isRef:()=>true,
    submitIndividualPhotos:async files=>{requests.push(files);return{confirmedFiles:files,uncertainFile:null};}});
  vm.runInContext(script.slice(script.indexOf('function photoFileType('),script.indexOf('function readPhotoDataUrl(')),context);
  vm.runInContext(script.slice(start,end),context);
  return{context,get,requests,pool:()=>vm.runInContext('FOLDER_PHOTOS.items',context)};
}
const entry=file=>({name:file.name,isFile:true,file:resolve=>queueMicrotask(()=>resolve(file))});
function directory(name,children,batchSize=100){
  return{name,isDirectory:true,createReader(){let position=0;return{readEntries(resolve){const batch=children.slice(position,position+batchSize);position+=batchSize;queueMicrotask(()=>resolve(batch));}};}};
}
const drop=entries=>({files:[],items:entries.map(value=>({kind:'file',webkitGetAsEntry:()=>value,getAsFile:()=>null}))});
(async()=>{
  let env=setup();assert.equal(env.get('photoFolderSubmit').disabled,true);
  const files=[photo('photo10.png','Alpha/nested/photo10.png'),photo('photo2.png','Alpha/nested/photo2.png'),photo('memo.txt','Alpha/memo.txt','text/plain')];
  await env.context.collectPickedFolder(files);
  assert.equal(env.pool().size,2);assert.equal(env.requests.length,0,'Selection must never queue or decode photos');
  assert.deepEqual(Array.from(env.pool().values(),item=>item.file.name),['photo2.png','photo10.png']);
  await env.context.collectPickedFolder([photo('other.png','Beta/deep/other.png'),...files]);
  assert.equal(env.pool().size,3,'Repeated selection skips identical relative-path/size/date metadata');assert(env.get('photoFolderStatus').textContent.includes('중복 선택 2장'));
  await env.context.submitFolderPhotos();assert.equal(env.requests.length,1);assert.equal(env.requests[0].length,3);assert.equal(env.pool().size,0);
  await env.context.submitFolderPhotos();assert.equal(env.requests.length,1,'Completed items cannot be submitted twice');

  // Multiple root folders, nested folders, and all readEntries batches beyond 100.
  env=setup();const many=Array.from({length:1001},(_,i)=>entry(photo(`photo${i}.png`,'')));
  await env.context.collectDroppedFolders(drop([directory('RootA',[directory('deep',many)]),directory('RootB',[entry(photo('other.png',''))])]));
  assert.equal(env.pool().size,1002);assert.equal(env.requests.length,0);assert.equal(env.get('photoFolderSubmit').disabled,false);
  await env.context.submitFolderPhotos();assert.equal(env.requests[0].length,1002);

  // A cancelled native dialog does not clear previously gathered photos.
  env=setup();await env.context.collectPickedFolder([photo('keep.png')]);await env.context.collectPickedFolder([]);assert.equal(env.pool().size,1);
  // A directory read error commits none of that selection.
  await env.context.collectDroppedFolders(drop([directory('New',[entry(photo('new.png','')),{name:'bad',isDirectory:true,createReader:()=>({readEntries:(_,reject)=>reject(Error('Synthetic failure'))})}])]));
  assert.equal(env.pool().size,1);assert(env.get('photoFolderStatus').textContent.includes('이번 선택은 추가하지 않았습니다'));

  // Clear invalidates a slow scan; late callbacks cannot restore cancelled items.
  let release;const slow={name:'slow.png',isFile:true,file:resolve=>{release=()=>resolve(photo('slow.png',''));}};
  const pending=env.context.collectDroppedFolders(drop([directory('Slow',[slow])]));
  await new Promise(setImmediate);env.context.clearFolderPhotos();release();await pending;assert.equal(env.pool().size,0);
  assert.equal(env.get('photoFolderSubmit').disabled,true);

  // Confirmed and ambiguous items are removed; failed/unprocessed items remain for explicit continuation.
  await env.context.collectPickedFolder([photo('a.png'),photo('b.png'),photo('c.png')]);
  env.context.submitIndividualPhotos=async files=>({confirmedFiles:[files[0]],uncertainFile:files[1]});
  await env.context.submitFolderPhotos();assert.deepEqual(Array.from(env.pool().values(),x=>x.file.name),['c.png']);
  assert(env.get('photoFolderStatus').textContent.includes('응답 미확인 1장'));
  env.context.queueSubmitting=true;await env.context.collectPickedFolder([photo('blocked.png')]);await env.context.submitFolderPhotos();env.context.clearFolderPhotos();assert.equal(env.pool().size,1);
  env.context.queueSubmitting=false;env.context.editingJobId='synthetic-edit';env.context.updateFolderPhotoControls();assert.equal(env.get('photoFolderSubmit').disabled,true);
  env.context.editingJobId=null;env.context.isRef=()=>false;env.context.updateFolderPhotoControls();assert.equal(env.get('photoFolderChoose').disabled,false);assert.equal(env.get('photoFolderSubmit').disabled,true);assert(env.get('photoFolderAvailability').textContent.includes('참조 사진'));

  env=setup();await env.context.collectPickedFolder([photo('blank.JPG','Root/blank.JPG',''),photo('bad.bin','Root/bad.bin','')]);assert.equal(env.pool().size,1);
  // Entries must be captured before the drag event's data becomes unreadable.
  let readable=true;const transfer={files:[],items:[{kind:'file',getAsEntry(){assert(readable);return directory('Now',[entry(photo('now.png',''))]);}}]};
  const captured=env.context.collectDroppedFolders(transfer);readable=false;await captured;assert.equal(env.pool().size,2);
  env=setup();env.context.CAT=null;
  await env.context.collectPickedFolder([photo('unknown.jpg','Root/unknown.jpg','application/octet-stream'),photo('camera.JFIF','Root/camera.JFIF','')]);
  assert.equal(env.pool().size,2,'Collecting metadata must not depend on catalog readiness or a recognized MIME type');
  assert.equal(env.get('photoFolderSubmit').disabled,true);assert(env.get('photoFolderAvailability').textContent.includes('모델 목록'));
  env.context.CAT={};env.context.updateFolderPhotoControls();assert.equal(env.get('photoFolderSubmit').disabled,false);
  env.context.submitIndividualPhotos=async()=>({confirmedFiles:[],uncertainFile:null,error:'Synthetic registration error'});
  await env.context.submitFolderPhotos();assert(env.get('photoFolderStatus').textContent.includes('Synthetic registration error'));assert.equal(env.pool().size,2);
  console.log('Folder photo checks passed: nested/multiple folders, 1,002 handles, paged directory reads, no early uploads, natural order, duplicate selection, scan cancellation, atomic read failure, queue/edit guards and safe continuation.');
})().catch(error=>{console.error(error);process.exitCode=1;});
