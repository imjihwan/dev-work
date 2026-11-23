// Stream synthetic File objects through the real UI handler; all requests mocked.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
const photos=n=>Array.from({length:n},(_,i)=>({type:'image/png',dataUri:`data:image/png;base64,SYNTHETIC_${i}`}));
function setup(options={}){
  const nodes=new Map(),requests=[],messages=[],builds=[],faceCounts=[];let polls=0,reads=0,liveReads=0,maxReads=0;
  const get=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:true,disabled:false,textContent:'',firstElementChild:{style:{}},querySelectorAll:()=>[]});return nodes.get(id);};
  const snapshot={f:{aspect:'auto',resolution:'draft',duration:'5',count:'20',summary:'Synthetic scenario'},shots:[[0,'Synthetic movement.']],seed:'42',final:null,
    model:{model:'test-model',steps:4,sampler:'euler',scheduler:'simple',shift_video:5,shift_audio:5,anchor:true,trig:false,oneTake:true,loras:{'test-lora':.75}},images:['unrelated-main-photo']};
  let context;
  class Reader{readAsDataURL(file){reads++;liveReads++;maxReads=Math.max(maxReads,liveReads);queueMicrotask(()=>{liveReads--;if(file.fail)this.onerror();else{this.result=file.dataUri;this.onload();}});}}
  context=vm.createContext({console,$:get,FileReader:Reader,queueSubmitting:false,editingJobId:null,bulkEditingIds:[],manualFinal:false,
    images:Array.from({length:9},(_,i)=>'unchanged-reference-'+i),PARAMS:['steps','sampler','scheduler','shift_video','shift_audio'],
    currentJobs:[{id:'older',state:'queued',seed:9}],pollT0:123,CAT:{capabilities:{restart_running:true}},pollGen:0,timer:null,
    isRef:()=>true,render(){},withFaceReferenceRules:(text,count)=>{faceCounts.push(count);return text;},captureSettings:()=>JSON.parse(JSON.stringify(snapshot)),build:count=>{builds.push(count);return 'synthetic-reference-count:'+count;},
    updateSequenceButton(){},updateGoLabel(){},loadHist(){},saveJobs(){},syncHistoryProgress(){},setStatus:message=>messages.push(message),
    histModelName:value=>value,finished:job=>job.state==='done'||job.state==='error',
    clearTimeout(){},setTimeout:()=>1,
    poll:jobs=>{polls++;context.currentJobs=jobs;},
    fetch:async(url,settings)=>{
      const body=JSON.parse(settings.body);requests.push({url,body});const index=requests.length;
      if(options.mutate && index===1){snapshot.model.loras['test-lora']=2;get('final').value='Changed later';}
      if(options.stopAfter===index)get('stopPhotoBatch').onclick();
      if(options.networkAt===index)throw Error('Synthetic connection loss');
      if(options.httpAt===index)return{ok:false,status:400,json:async()=>({error:'Synthetic registration condition failed'})};
      return{ok:true,status:200,json:async()=>({jobs:[{id:'new-'+index,seed:body.seed||index,width:640,height:384,model:body.model,steps:body.steps,images:['synthetic-upload']}],width:640,height:384})};
    }});
  vm.runInContext(script.slice(script.indexOf('let photoBatchStop='),script.indexOf('let currentJobs =')),context);
  return{context,get,requests,messages,builds,faceCounts,snapshot,stats:()=>({polls,reads,maxReads})};
}
function rotatingSetup(options={}){
  const env=setup(),uploads=[],generations=[],releases=[];
  env.context.CAT={capabilities:{photo_reference_pool:true}};
  env.context.fetch=async(url,settings)=>{
    const body=JSON.parse(settings.body);
    if(url==='/api/photo-references'){
      const id='ref-'+(uploads.length+1);uploads.push({id,...body});
      if(options.mutate&&uploads.length===1){env.snapshot.model.loras['test-lora']=2;env.snapshot.seed='999';}
      if(options.stopUpload===uploads.length)env.get('stopPhotoBatch').onclick();
      return{ok:true,status:200,json:async()=>({id,cropped:body.face_boost})};
    }
    if(url==='/api/photo-references/release'){releases.push(body);return{ok:true,json:async()=>({ok:true})};}
    assert.equal(url,'/api/generate');generations.push(body);
    if(options.stopAfter===generations.length)env.get('stopPhotoBatch').onclick();
    if(options.networkAt===generations.length)throw Error('Synthetic acknowledgement loss');
    return{ok:true,status:200,json:async()=>({jobs:[{id:'rotation-'+generations.length,seed:body.seed,width:640,height:384}]})};
  };
  return{...env,uploads,generations,releases};
}
const folderPhotos=(folder,n)=>photos(n).map((file,index)=>({...file,name:`photo${index+1}.png`,webkitRelativePath:`${folder}/photo${index+1}.png`,size:100,lastModified:index}));
(async()=>{
  let env=setup({mutate:true});const before=JSON.stringify(env.context.images);
  const outcome=await env.context.submitIndividualPhotos(photos(100));assert.equal(outcome.confirmedFiles.length,100);assert.equal(outcome.uncertainFile,null);
  assert.equal(env.requests.length,100);assert.equal(env.context.currentJobs.length,101);assert.equal(env.context.currentJobs[0].id,'older');assert.equal(env.stats().polls,1);assert.equal(env.stats().maxReads,1);
  for(const {url,body} of env.requests){assert.equal(url,'/api/generate');assert.equal(body.images.length,1);assert.equal(body.count,1);assert.equal(body.mode,'REF2VA');assert.equal(body.photo_sequence,false);assert.equal(body.seed,'42');assert.equal(body.prompt,'synthetic-reference-count:1');assert.equal(body.loras[0].strength,.75);assert.equal(body.ui.f.count,1);assert(!JSON.stringify(body).includes('unrelated-main-photo'));}
  assert.equal(JSON.stringify(env.context.images),before);assert.deepEqual(env.builds,[1]);assert.deepEqual(env.faceCounts,[1]);assert.equal(env.context.queueSubmitting,false);assert(env.get('photoBatchStatus').textContent.includes('100개 개별 등록'));
  env=setup();await env.context.submitIndividualPhotos(photos(1001));assert.equal(env.requests.length,1001);assert.equal(env.stats().reads,1001);assert.equal(env.stats().maxReads,1);assert.equal(env.context.currentJobs.length,1002);assert.equal(env.stats().polls,1);assert(!html.includes('최대 100장'));
  env=setup({stopAfter:3});await env.context.submitIndividualPhotos(photos(100));assert.equal(env.requests.length,3);assert.equal(env.context.currentJobs.length,4);assert(env.get('photoBatchStatus').textContent.includes('추가 중단'));
  env=setup({networkAt:3});const uncertainFiles=photos(10),uncertain=await env.context.submitIndividualPhotos(uncertainFiles);assert.equal(uncertain.confirmedFiles.length,2);assert.equal(uncertain.uncertainFile,uncertainFiles[2]);assert.equal(env.requests.length,3);assert.equal(env.context.currentJobs.length,3);assert(env.get('photoBatchStatus').textContent.includes('자동 재시도하지 않습니다'));
  env=setup();const files=photos(5);files[2].fail=true;await env.context.submitIndividualPhotos(files);assert.equal(env.requests.length,4);assert(env.get('photoBatchStatus').textContent.includes('1개 실패'));
  env=setup();env.snapshot.seed='';await env.context.submitIndividualPhotos(photos(2));assert(env.requests.every(item=>item.body.seed===''));
  env=setup();await env.context.submitIndividualPhotos([{name:'camera.JFIF',type:'application/octet-stream',dataUri:'data:application/octet-stream;base64,U1lOVEhFVElD'}]);
  assert.equal(env.requests.length,1);assert.equal(env.requests[0].body.images[0],'data:image/jpeg;base64,U1lOVEhFVElD');
  env=setup({httpAt:1});const rejection=await env.context.submitIndividualPhotos(photos(1));assert.equal(rejection.confirmedFiles.length,0);assert(rejection.error.includes('Synthetic registration condition failed'));assert.equal(env.context.queueSubmitting,false);
  env=setup();env.context.CAT=null;const folderFiles=photos(3).map((file,index)=>({...file,name:`photo${index}.jpg`,webkitRelativePath:`Root/sub/photo${index}.jpg`,size:10,lastModified:index,type:'application/octet-stream'}));
  await env.context.collectPickedFolder(folderFiles);assert.equal(env.requests.length,0);assert.equal(vm.runInContext('FOLDER_PHOTOS.items.size',env.context),3);
  env.context.CAT={};await env.context.submitFolderPhotos();assert.equal(env.requests.length,3);assert.equal(vm.runInContext('FOLDER_PHOTOS.items.size',env.context),0,'Real folder submit must call the real batch submit and remove only confirmed files');
  let rotating=rotatingSetup({mutate:true});rotating.snapshot.model.faceBoost=true;
  const originalMain=JSON.stringify(rotating.context.images);
  await rotating.context.collectPickedFolder(folderPhotos('Folder',50).reverse());assert.equal(rotating.uploads.length,0);
  await rotating.context.submitFolderRotatingPhotos();
  assert.equal(rotating.uploads.length,50);assert.equal(rotating.generations.length,50);assert.equal(rotating.releases.length,1);assert.equal(rotating.stats().maxReads,1);
  for(let index=0;index<50;index++){
    const job=rotating.generations[index];
    assert.deepEqual(job.reference_ids,Array.from({length:9},(_,n)=>rotating.uploads[(index+n)%50].id));
    assert.equal(job.seed,String(42+index));assert.equal(job.loras[0].strength,.75);assert.equal(job.ui.faceBoost,true);assert.equal(job.prompt,'synthetic-reference-count:9');assert.equal(job.reference_sequence_index,index+1);
  }
  assert(rotating.uploads.every(item=>item.face_boost));assert.equal(JSON.stringify(rotating.context.images),originalMain);
  await rotating.context.submitFolderRotatingPhotos();assert.equal(rotating.generations.length,50,'Double submit does not register completed anchors again');
  rotating=rotatingSetup();await rotating.context.collectPickedFolder([...folderPhotos('A',50),...folderPhotos('B',50)]);await rotating.context.submitFolderRotatingPhotos();
  assert.equal(rotating.generations.length,100);assert.equal(rotating.uploads.length,100);assert.equal(rotating.releases.length,2);
  for(const job of rotating.generations)assert.equal(new Set(job.reference_ids.map(id=>rotating.uploads.find(row=>row.id===id).group)).size,1,'References never cross folder boundaries');
  rotating=rotatingSetup({stopAfter:3});await rotating.context.collectPickedFolder(folderPhotos('Resume',50));await rotating.context.submitFolderRotatingPhotos();assert.equal(rotating.generations.length,3);
  await rotating.context.submitFolderRotatingPhotos();assert.equal(rotating.generations.length,50);assert.equal(rotating.generations[3].seed,'45');
  rotating=rotatingSetup({networkAt:3});await rotating.context.collectPickedFolder(folderPhotos('Uncertain',50));await rotating.context.submitFolderRotatingPhotos();assert.equal(rotating.generations.length,3);
  await rotating.context.submitFolderRotatingPhotos();assert.equal(rotating.generations.length,50);assert(rotating.get('photoFolderStatus').textContent.includes('응답 미확인 1개'));
  rotating=rotatingSetup({stopUpload:4});await rotating.context.collectPickedFolder(folderPhotos('UploadStop',50));await rotating.context.submitFolderRotatingPhotos();assert.equal(rotating.generations.length,0);assert.equal(rotating.releases[0].ids.length,4);
  rotating=rotatingSetup();await rotating.context.collectPickedFolder([...folderPhotos('One',1),...folderPhotos('Three',3)]);await rotating.context.submitFolderRotatingPhotos();assert.deepEqual(rotating.generations.map(job=>job.reference_ids.length),[1,3,3,3]);
  // 폴링: 추적 중인 작업을 한 번의 요청으로 묻는다. 큰 묶음은 앞쪽 몇 개만 묻고, 실행 중인 작업에서 멈춘다.
  const pollSource=script.slice(script.indexOf('function poll(jobs,'),script.indexOf('const HIST ='));
  const idsOf=url=>decodeURIComponent(url.split('ids=')[1]).split(',');
  // 가짜 타이머: 다음 바퀴를 직접 돌린다
  const polling=fetch=>{
    const made=setup();let next=null;made.context.setTimeout=callback=>{next=callback;return 1;};made.context.fetch=fetch;
    vm.runInContext(pollSource,made.context);
    const settle=async()=>{for(let i=0;i<50&&!next;i++)await new Promise(resolve=>setImmediate(resolve));};
    return{start:async jobs=>{made.context.poll(jobs,Date.now(),null);await settle();},
      round:async()=>{const run=next;next=null;assert(run,'Polling must keep going');await run();await settle();}};
  };
  let asked=[];
  let loop=polling(async url=>{asked.push(url);return{ok:true,json:async()=>({jobs:Object.fromEntries(idsOf(url).map((id,i)=>[id,i<2?{state:'done',video:{}}:i===2?{state:'running',pct:5}:{state:'queued',position:i-2}]))})};});
  let big=Array.from({length:100},(_,i)=>({id:'queued-'+i,state:'queued'}));
  await loop.start(big);
  assert.equal(asked.length,1,'One status request per tick, however many jobs are tracked');
  assert(asked[0].startsWith('/api/status?id=queued-0&ids='),'The first job is also sent as id so a server without batch status can still answer');
  assert(idsOf(asked[0]).length<=4,'Large batches ask only for the head of the queue');
  assert.deepEqual(big.slice(0,5).map(job=>[job.state,job.position]),[['done',undefined],['done',undefined],['running',undefined],['queued',1],['queued',undefined]],'Every answer that was asked for is applied; later jobs wait');
  // 스무 개 이하는 전부 한 번에 묻는다
  asked=[];
  loop=polling(async url=>{asked.push(url);return{ok:true,json:async()=>({jobs:Object.fromEntries(idsOf(url).map(id=>[id,{state:'queued',position:3}]))})};});
  const few=Array.from({length:20},(_,i)=>({id:'few-'+i,state:'queued'}));
  await loop.start(few);
  assert.equal(asked.length,1);assert.equal(idsOf(asked[0]).length,20);assert(few.every(job=>job.position===3));
  // 응답을 받지 못한 바퀴(화면 서버 재시작·연결 끊김·오류 응답)는 '찾을 수 없음'으로 세지 않는다
  for(const broken of [async()=>{throw new TypeError('Failed to fetch');},async()=>({ok:false,json:async()=>({error:'영상 서버 재시작 중입니다.'})}),async()=>({ok:true,json:async()=>{throw new SyntaxError('not json');}}),
      async()=>({ok:false,status:503,json:async()=>({error:'busy',jobs:{a:{state:'unknown'},b:{state:'unknown'}}})}),async()=>({ok:false,status:500,json:async()=>({state:'unknown'})})]){
    let calls=0;loop=polling(async url=>{calls++;return broken(url);});
    const tracked=[{id:'a',state:'running',pct:40},{id:'b',state:'queued'}];
    await loop.start(tracked);
    for(let round=0;round<7;round++)await loop.round();
    assert.equal(calls,8);
    assert.deepEqual(tracked.map(job=>[job.state,job.miss,job.error,job.pct]),[['running',0,undefined,40],['queued',0,undefined,undefined]],'A failed request must not end or alter tracked jobs');
  }
  // 서버가 모른다고 답한 작업만 다섯 번 뒤에 끝낸다. 큰 묶음에서도 함께 물은 작업들이 같이 정리된다.
  loop=polling(async url=>({ok:true,json:async()=>({jobs:Object.fromEntries(idsOf(url).map(id=>[id,{state:'unknown'}]))})}));
  big=Array.from({length:30},(_,i)=>({id:'gone-'+i,state:'queued'}));
  await loop.start(big);
  for(let round=0;round<3;round++)await loop.round();
  assert(big.every(job=>job.state==='queued'),'Four misses are not enough');
  await loop.round();
  assert.deepEqual(big.slice(0,5).map(job=>job.state),['error','error','error','error','queued'],'Jobs asked together are retired together');
  assert(big[0].error.includes('작업을 찾을 수 없음'));
  // 사이에 살아 있는 작업이 끼어 있어도, 함께 물은 사라진 작업들은 같이 정리된다
  loop=polling(async url=>({ok:true,json:async()=>({jobs:Object.fromEntries(idsOf(url).map((id,i)=>[id,i===1?{state:'queued',position:1}:{state:'unknown'}]))})}));
  big=Array.from({length:30},(_,i)=>({id:'mixed-'+i,state:'queued'}));
  await loop.start(big);
  for(let round=0;round<4;round++)await loop.round();
  assert.deepEqual(big.slice(0,5).map(job=>job.state),['error','queued','error','error','queued']);
  // 묶음 조회를 모르는 서버(작업 하나의 상태만 답함)에는 예전처럼 하나씩 묻는다
  let statusCalls=0;loop=polling(async()=>{statusCalls++;return{json:async()=>statusCalls<4?{state:'done',video:{}}:{state:'running',pct:5}};});
  await loop.start(Array.from({length:100},(_,i)=>({id:'queued-'+i,state:'queued'})));
  assert.equal(statusCalls,4,'Legacy fallback still stops at the active job');
  console.log('Photo batch checks passed: 1,001 photos without a count limit, one-file-at-a-time memory use, frozen settings, existing queue/reference preservation, cancellation, no ambiguous retries, one status request per tick and failed requests never retiring a job.');
})().catch(error=>{console.error(error);process.exitCode=1;});
