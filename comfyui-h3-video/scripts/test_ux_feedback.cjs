// 화면 개선 2: 결과 보기 버튼, 고정 시드 표시·랜덤 버튼, 빠진 사진 알림, 남은 시간·탭 제목·탭 복귀 갱신.
// 가짜 요소·가짜 응답만 쓴다. 브라우저·서버·ComfyUI·이력 파일에는 접근하지 않는다.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
const section=(start,end)=>{const from=script.indexOf(start);assert(from>=0,start);const to=script.indexOf(end,from);assert(to>from,end);return script.slice(from,to);};
const elements=()=>{const nodes=new Map();return id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',hidden:true,disabled:false,textContent:'',className:'',dataset:{},firstElementChild:{style:{}}});return nodes.get(id);};};
const settle=async()=>{for(let i=0;i<20;i++)await new Promise(setImmediate);};

// 표시 요소가 HTML 에 있고, 핸드폰 바를 늘리지 않게 띄워 두는지
assert(html.includes('id="showLatest"')&&html.includes('id="seedRandom"')&&html.includes('id="photoSkip"'));
assert(/\.action-quick\{float:right/.test(html),'Quick buttons must float beside the existing summary lines');

(async()=>{
  // 11. 빠진 사진 알림: 한도 초과·사진이 아닌 파일·브라우저가 못 여는 사진
  {
    const $=elements(),statuses=[];
    const context=vm.createContext({$,console,images:[],bulkEditingIds:[],maxImgs:()=>9,drawThumbs(){},setStatus:(text,cls)=>statuses.push([text,cls]),setTimeout,clearTimeout,
      FileReader:class{readAsDataURL(file){queueMicrotask(()=>{this.result=`data:image/png;base64,${file.id}`;this.onload();});}},
      Image:class{set src(value){queueMicrotask(()=>value.includes('BROKEN')?this.onerror():this.onload());}}});
    vm.runInContext(section('let photoImportQueue=','function photoLabel('),context);
    vm.runInContext(section('function photoFileType(','async function submitIndividualPhotos('),context);
    const photo=(id,name=`p${id}.png`)=>({id:String(id),name,type:'image/png'});
    await context.addFiles(Array.from({length:12},(_,i)=>photo(i)));
    assert.equal(context.images.length,9);
    let note=$('photoSkip');assert.equal(note.hidden,false);assert(note.textContent.includes('사진 9장 추가'));assert(note.textContent.includes('최대 9장이라 3장은 넣지 않았습니다'));assert(note.textContent.includes('사진별로 추가'));assert.equal(note.className,'status');
    assert.equal(statuses.length,0,'The progress poll overwrites #status, so the notice belongs under the photos');
    context.images.length=0;
    await context.addFiles([photo(1),{id:'x',name:'clip.mp4',type:'video/mp4'},{id:'y',name:'notes.pdf',type:'application/pdf'}]);
    assert.equal(context.images.length,1);assert(note.textContent.includes('사진이 아닌 파일 2개(clip.mp4, notes.pdf)는 건너뛰었습니다'));
    context.images.length=0;
    await context.addFiles([photo('BROKEN','IMG_0001.HEIC'),photo(2)]);
    assert.deepEqual([...context.images],['data:image/png;base64,2'],'An image the browser cannot draw must not be added');
    assert(note.textContent.includes('1장(IMG_0001.HEIC)은 이 브라우저에서 열 수 없는 형식(HEIC 등)'));assert(note.textContent.includes('JPEG'));assert.equal(note.className,'status err');
    await context.addFiles([photo(3)]);assert.equal(note.hidden,true,'A clean add clears the previous notice');
    // TIFF·BMP 는 Chrome 이 못 그려도 서버가 열 수 있다: 미리 그려 보지 않고 예전처럼 넣는다(HEIC 안내로 막지 않는다)
    await context.addFiles([{id:'BROKEN-tiff',name:'scan.tif',type:'image/tiff'},{id:'BROKEN-bmp',name:'old.bmp',type:''}]);
    assert.equal(context.images.length,4,'TIFF and BMP are added without the draw test');assert.equal(note.hidden,true);
    assert.equal(context.photoNeedsDecodeCheck({name:'IMG.heif',type:''}),true);assert.equal(context.photoNeedsDecodeCheck({name:'x.bin',type:'image/heic'}),true);
    assert.equal(context.photoNeedsDecodeCheck({name:'a.jpg',type:'image/jpeg'}),false);
    const message=context.photoSkipMessage({added:0,over:0,other:['a','b','c','d'],broken:[]},9);assert(message.text.includes('4개(a, b, c 외)'));
    assert.equal(context.photoSkipMessage({added:2,over:0,other:[],broken:[]},9),null);
  }

  // 7. 고정 시드를 요약 줄에 보이고 한 번에 랜덤으로
  {
    const $=elements();let saved=0;const statuses=[];
    $('seed').addEventListener=()=>{};
    const context=vm.createContext({$,console,CAT:{},S:{loras:{},steps:4,speed:'',anchor:false,faceBoost:false},curModel:()=>({name:'m'}),friendlyModel:()=>'모델',base:v=>v,runCount:()=>1,isRef:()=>true,
      SPEED_MODES:{},etaText:()=>'예상 약 3분',updateSequenceButton(){},save:()=>saved++,setStatus:(text,cls)=>statuses.push([text,cls])});
    vm.runInContext(section('function drawGoInfo(','function updateSequenceButton('),context);
    $('seed').value=' 123 ';context.drawGoInfo();
    assert($('goInfo').textContent.includes(' · 예상 약 3분 · 시드 123 고정'),'The estimate comes first: the phone shows one cut line');assert.equal($('seedRandom').hidden,false);
    $('seedRandom').onclick();assert.equal($('seed').value,'');assert.equal(saved,1,'Same save/sync path as typing in the seed field');
    assert(!$('goInfo').textContent.includes('시드'));assert.equal($('seedRandom').hidden,true);assert.equal(statuses[0][1],'ok');
    $('seed').value='abc';context.drawGoInfo();assert(!$('goInfo').textContent.includes('시드'));assert.equal($('seedRandom').hidden,true);
    $('seed').value='77';$('seed').disabled=true;context.drawGoInfo();assert.equal($('seedRandom').hidden,true,'Bulk edit keeps each seed, so no random button');
    $('seedRandom').onclick();assert.equal($('seed').value,'77');
    context.CAT=null;$('seed').disabled=false;context.drawGoInfo();assert.equal($('seedRandom').hidden,false,'The button follows the seed even before the catalog loads');
  }

  // 12. 남은 시간·전체 예상 완료 시각·탭 제목·탭 복귀 즉시 갱신 / 6. 결과 보기
  {
    const $=elements(),statuses=[],listeners={};let next=null,responses=[];
    const doc={title:'H3 영상 만들기',hidden:false,addEventListener:(type,fn)=>{listeners[type]=fn;}};
    const context=vm.createContext({$,console,document:doc,Date,Math,Number,String,
      setTimeout:fn=>{next=fn;return 1;},clearTimeout(){},fetch:async()=>({ok:true,json:async()=>responses.shift()}),
      currentJobs:[],pollT0:0,pollGen:0,timer:null,queueSubmitting:false,CAT:{capabilities:{}},
      finished:job=>job.state==='done'||job.state==='error',saveJobs(){},syncHistoryProgress(){},updateGoLabel(){},loadHist(){},
      setStatus:(text,cls)=>statuses.push([text,cls]),HIST:{items:[],loading:false}});
    vm.runInContext(section('function poll(jobs,','const HIST ='),context);
    const now=Date.now()/1000;
    assert.equal(context.remainingText({pct:50,generation_started_at:now-120},0,now,0),' · 약 2분 남음');
    const whole=context.remainingText({pct:50,generation_started_at:now-120},2,now,0);
    assert(/ · 약 2분 남음 · 전체 약 10분\(\d\d:\d\d쯤\)$/.test(whole),whole);
    assert.equal(context.remainingText({pct:5,generation_started_at:now-30},0,now,300),' · 약 5분 남음','Early percentages use the recent measured job time');
    assert.equal(context.remainingText({pct:5},0,now,0),'','Nothing to estimate from');
    assert.equal(context.remainingText({pct:50,generation_started_at:now-120},2,now,0,false),' · 약 2분 남음','Different waiting settings: no whole-queue time');
    assert.equal(context.jobShape({info:'832×480, 모델 8스텝, 시드 5 · 사진 2번을 첫 번째 참조로'}),context.jobShape({info:'832×480, 모델 8스텝, 시드 9'}));
    assert.notEqual(context.jobShape({width:832,height:480,steps:8,model:'m'}),context.jobShape({width:1280,height:720,steps:8,model:'m'}));
    assert.equal(context.jobShape({}),'');
    context.HIST.items=[{state:'done',generation_seconds:100},{state:'done',generation_seconds:300},{state:'error',generation_seconds:5},{state:'done',generation_seconds:200}];
    assert.equal(context.recentJobSeconds(),200);
    responses.push({jobs:{a:{state:'running',pct:40,label:" 생성",generation_started_at:now-78},b:{state:'queued',position:1}}});
    const shape='832×480, 모델 8스텝, 시드 ';
    context.poll([{id:'a',state:'queued',info:shape+1},{id:'b',state:'queued',info:shape+2}],Date.now(),'info');await settle();
    let line=statuses.at(-1)[0];assert(line.includes('40% · 생성'));assert(line.includes('약 2분 남음'),line);assert(line.includes('전체 약'),line);
    assert.equal(doc.title,'40% · H3 영상 만들기');assert.equal($('showLatest').hidden,true);
    // 탭 복귀가 응답을 기다리는 바퀴와 겹치면 두 번째 바퀴는 돌지 않는다(찾을 수 없음 횟수가 두 번씩 오르지 않게)
    {
      let release,asked=0;const realFetch=context.fetch;
      context.fetch=async()=>{asked++;await new Promise(ok=>release=ok);return {ok:true,json:async()=>({jobs:{a:{state:'running',pct:45,label:' 생성',generation_started_at:now-90},b:{state:'queued',position:1}}})};};
      const pending=next;next=null;const first=pending();await settle();
      doc.hidden=false;listeners.visibilitychange();await settle();
      assert.equal(asked,1,'A tick already waiting for its answer is not doubled');
      release();await first;await settle();context.fetch=realFetch;
    }
    // 탭 복귀: 늦춰진 예약을 기다리지 않고 바로 한 바퀴
    doc.hidden=true;listeners.visibilitychange();assert.equal(responses.length,0);
    responses.push({jobs:{a:{state:'running',pct:80,label:' 생성',generation_started_at:now-160},b:{state:'queued',position:1}}});
    doc.hidden=false;listeners.visibilitychange();await settle();
    assert(statuses.at(-1)[0].includes('80%'),'Returning to the tab refreshes immediately');assert.equal(doc.title,'80% · H3 영상 만들기');
    // 숨은 탭에서 끝나면 탭 제목으로 알리고, 결과 보기 버튼이 방금 만든 영상을 가리킨다
    doc.hidden=true;
    responses.push({jobs:{a:{state:'done',video:{filename:'a.mp4'}},b:{state:'done',video:{filename:'b.mp4'}}}});
    const run=next;next=null;await run();await settle();
    assert.equal(doc.title,'완료 · H3 영상 만들기');assert.equal($('showLatest').hidden,false);assert.equal($('showLatest').textContent,'결과 보기 (2)');
    assert.deepEqual(vm.runInContext('latestResultIds',context),['a','b']);
    doc.hidden=false;listeners.visibilitychange();assert.equal(doc.title,'H3 영상 만들기','Coming back restores the title');
    assert.deepEqual(context.latestDoneIds([{id:1,state:'done',video:{}},{id:2,state:'error'},{id:3,state:'done'},{id:4,state:'done',video:{}},{id:5,state:'done',video:{}},{id:6,state:'done',video:{}}]),[4,5,6]);
    // 한 건 실패는 '실패'
    doc.hidden=true;responses.push({jobs:{c:{state:'error',error:'synthetic'}}});
    context.poll([{id:'c',state:'queued'}],Date.now(),null);assert.equal($('showLatest').hidden,true,'A new run hides the old result button');await settle();
    assert.equal(doc.title,'실패 · H3 영상 만들기');assert.equal($('showLatest').hidden,true);
    // 다시 열었을 때 이미 끝나 있던 묶음(어제 것)은 '결과 보기'·탭 제목 '완료'를 띄우지 않는다
    doc.title='H3 영상 만들기';doc.hidden=true;
    context.poll([{id:'old',state:'done',video:{filename:'old.mp4'}}],Date.now()-86400000,null,Date.now()-80000000);await settle();
    assert.equal($('showLatest').hidden,true,'A batch that was already finished shows no result button');assert.equal(doc.title,'H3 영상 만들기');

    // 6. 결과 보기: 이력 목록을 새로 읽은 뒤 그 영상들을 함께 재생 창으로 연다
    const selected=new Set();let opened=0,loads=0;
    Object.assign(context,{VIDEO_COMPARE:{selected},setVideoPlaybackSelection:(id,on)=>{if(on)selected.add(id);},openVideoComparison:()=>opened++,
      loadHist:async()=>{loads++;context.HIST.items=[{id:'a',video:{}},{id:'b',video:{}}];}});
    vm.runInContext(section('async function showLatestResults(','$("showLatest").onclick'),context);
    vm.runInContext('latestResultIds=["a","b"]',context);context.HIST.items=[];selected.add('old');
    await context.showLatestResults();
    assert.equal(loads,1);assert.deepEqual([...selected],['a','b'],'Only the just-made videos are selected');assert.equal(opened,1);
    await context.showLatestResults();assert.equal(loads,1,'No reload when the entries are already listed');assert.equal(opened,2);
    context.loadHist=async()=>{};context.HIST.items=[];await context.showLatestResults();assert.equal(opened,2);assert(statuses.at(-1)[0].includes('작업 이력에서 찾아'));
  }
  console.log('UX feedback checks passed: skipped-photo notices, fixed-seed summary and random button, remaining time, tab title, immediate refresh on return and result playback button.');
})().catch(error=>{console.error(error);process.exitCode=1;});
