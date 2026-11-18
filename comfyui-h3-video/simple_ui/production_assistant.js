/* App-specific Grok assistant. No eval, injected scripts, filesystem or external URLs. */
(function(factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else api.mount(window);
})(function(){
  'use strict';
  const tidy=value=>String(value??'').replace(/\s+/g,' ').trim();
  function valueOf(node){return ['checkbox','radio'].includes(node.type)?String(!!node.checked):String(node.value??'');}
  function replaceOne(original,before,value){
    if(before===''){if(original!=='')throw Error('비어 있지 않은 칸은 덮어쓰지 않았습니다.');return value;}
    const at=original.indexOf(before);
    if(at<0||original.indexOf(before,at+before.length)>=0)throw Error('원문이 바뀌었거나 수정 위치가 여러 곳입니다. 다시 요청해 주세요.');
    return original.slice(0,at)+value+original.slice(at+before.length);
  }
  function bindArgs(template,bindings){
    if(typeof template==='string'&&template.startsWith('$current_')){
      const key=template.slice(1);if(!Object.hasOwn(bindings,key))throw Error('현재 탭에서 사용할 수 없는 입력입니다. 필요한 탭을 열어 주세요.');
      return structuredClone(bindings[key]);
    }
    if(Array.isArray(template))return template.map(item=>bindArgs(item,bindings));
    if(template&&typeof template==='object')return Object.fromEntries(Object.entries(template).map(([key,value])=>[key,bindArgs(value,bindings)]));
    return template;
  }
  function blocked(node,win){
    for(let parent=node;parent;parent=parent.parentElement){
      if(parent.id==='singleApp')continue;
      if(parent.hidden)return true;
      if(win.getComputedStyle&&win.getComputedStyle(parent).display==='none')return true;
    }
    return false;
  }
  function collect(win,refs){
    const controls=[],nodes=new Map(),documents=[{win,page:'main',scope:win.document.body}];
    // Main controls remain addressable when a gallery/story tab is active.
    for(const frame of win.document.querySelectorAll('iframe')){
      if(frame.hidden)continue;
      try{if(frame.contentWindow.location.origin===win.location.origin&&frame.contentDocument?.body)documents.push({win:frame.contentWindow,page:frame.id==='storyFrame'?'story':'gallery',scope:frame.contentDocument.body});}catch{}
    }
    const bridges=[],contexts=[];
    for(const doc of documents){
      if(doc.win.H3ProductionBridge){doc.win.H3ProductionBridge.beforeSnapshot?.();bridges.push({page:doc.page,bridge:doc.win.H3ProductionBridge});contexts.push({page:doc.page,...(doc.win.H3ProductionBridge.context?.()||{}),statuses:[...doc.scope.querySelectorAll('[role=status],.status,#queueFeedback')].filter(node=>!node.closest('#h3ProductionPanel')&&!blocked(node,doc.win)).slice(0,20).map(node=>({id:node.id||'',text:tidy(node.textContent).slice(0,2000)}))});}
      for(const node of doc.scope.querySelectorAll('input,textarea,select,button,a[href]')){
        if(node.closest('#h3ProductionPanel,#h3ProductionToggle')||node.type==='password'||node.type==='hidden'||['cancel','restartCurrent','histClear'].includes(node.id))continue;
        const tag=node.tagName.toLowerCase();
        let type=tag==='textarea'?'textarea':tag==='select'?'select':tag==='button'?'button':tag==='a'?'link':node.type||'text';
        if(['submit','reset'].includes(type))type='button';
        if(['email','url','search','tel','range'].includes(type))type=type==='range'?'number':'text';
        if(!['text','textarea','number','checkbox','radio','select','button','link','file'].includes(type))continue;
        if(type==='link'){
          let url;try{url=new URL(node.href,win.location.href);}catch{continue;}
          if(url.origin!==win.location.origin)continue;
        }
        if(!refs.map.has(node))refs.map.set(node,++refs.next);
        const ref=doc.page+':'+refs.map.get(node);
        const labels=node.labels?[...node.labels].map(label=>tidy(label.textContent)).join(' '):'';
        const label=(labels||node.getAttribute('aria-label')||node.title||(type==='button'||type==='link'?tidy(node.textContent):node.id||node.placeholder||type)).slice(0,200);
        const row=node.closest('[data-l],[data-m],[data-id]');
        const itemId=node.getAttribute('data-id')||row?.getAttribute('data-l')||row?.getAttribute('data-m')||row?.getAttribute('data-id')||'';
        const entry={ref,id:node.id||'',item_id:itemId,action:node.getAttribute('data-action')||'',page:doc.page,type,label,value:['button','link','file'].includes(type)?'':valueOf(node),readonly:!!node.readOnly,disabled:!!node.disabled,hidden:blocked(node,doc.win)};
        if(type==='number')for(const key of ['min','max','step'])if(node.getAttribute(key)!==null)entry[key]=node.getAttribute(key);
        if(type==='select')entry.options=[...node.options].map(option=>({value:String(option.value),label:tidy(option.textContent).slice(0,120),disabled:!!option.disabled}));
        controls.push(entry);nodes.set(ref,{node,entry,win:doc.win});
      }
    }
    if(controls.length>1500)throw Error('화면에 조작 항목이 많습니다. 필요한 탭이나 목록 범위를 줄여 주세요.');
    return {controls,nodes,bridges,contexts};
  }
  function sourceGuard(snapshot){
    return snapshot.bridges.map(item=>({page:item.page,bridge:item.bridge,fingerprint:item.bridge.fingerprint?.(),images:item.bridge.imageRefs?.()}));
  }
  function checkSources(guard){
    for(const item of guard){
      if(item.fingerprint!==undefined&&item.fingerprint!==item.bridge.fingerprint?.())throw Error('요청 후 입력값이 바뀌었습니다. 현재 내용으로 다시 요청해 주세요.');
      const now=item.bridge.imageRefs?.();
      if(item.images&&(item.images.length!==now?.length||item.images.some((image,index)=>image!==now[index])))throw Error('요청 후 사진 선택이 바뀌었습니다. 다시 요청해 주세요.');
    }
  }
  function preflight(actions,snapshot,guard){
    if(actions.some(action=>action.kind==='set'||action.kind==='api'&&action.args.includes('$current_')||action.kind==='click'&&['go','priorityGo','sequenceGo','settingsSave','saveProject'].includes(snapshot.nodes.get(action.target)?.entry.id)))checkSources(guard);
    for(const action of actions){
      if(action.kind==='api')continue;
      const record=snapshot.nodes.get(action.target);
      if(!record||record.node.isConnected===false||record.node.disabled||blocked(record.node,record.win))throw Error('화면의 대상이 바뀌었습니다. 다시 요청해 주세요.');
      if(action.kind==='set'&&valueOf(record.node)!==record.entry.value)throw Error('수정할 원문이 바뀌었습니다. 다시 요청해 주세요.');
    }
  }
  function setControl(record,action){
    const {node,win,entry}=record;
    if(node.isConnected===false||node.disabled||node.readOnly||blocked(node,win))throw Error('입력 대상이 바뀌었습니다.');
    const original=valueOf(node),value=replaceOne(original,action.before,action.value);
    if(entry.type==='number'&&value!==''&&!Number.isFinite(Number(value)))throw Error('숫자 입력 형식을 확인해 주세요.');
    if(['checkbox','radio'].includes(entry.type)){
      if(!['true','false'].includes(value))throw Error('체크 상태를 확인해 주세요.');node.checked=value==='true';
    }else{
      if(entry.type==='select'&&![...node.options].some(option=>option.value===value&&!option.disabled))throw Error('선택할 값이 현재 목록에 없습니다.');
      node.value=value;
      if(String(node.value)!==value){node.value=original;throw Error('입력 형식을 확인해 주세요.');}
    }
    node.dispatchEvent(new win.Event('input',{bubbles:true}));
    node.dispatchEvent(new win.Event('change',{bubbles:true}));
  }
  function clickControl(record){
    const {node,win}=record;
    if(node.isConnected===false||node.disabled||blocked(node,win))throw Error('버튼 대상이 바뀌었습니다.');
    for(let parent=node.parentElement;parent;parent=parent.parentElement){if(parent.id==='singleApp'&&parent.hidden)win.document.getElementById('singleTab')?.click();if(parent.tagName==='DETAILS')parent.open=true;}
    node.click(); // The app's own validation and any native confirmation remain intact.
  }
  function mount(win){
    if(win.top!==win.self||win.document.getElementById('h3ProductionPanel'))return;
    const doc=win.document,style=doc.createElement('style');
    style.textContent='#h3ProductionToggle{position:fixed;right:16px;bottom:18px;z-index:100010;border:0;border-radius:24px;padding:12px 18px;background:#245edb;color:#fff;box-shadow:0 3px 16px #0003;font:600 14px system-ui;cursor:pointer}#h3ProductionPanel{position:fixed;right:12px;bottom:12px;z-index:100011;width:min(440px,calc(100vw - 24px));max-height:82vh;max-height:82dvh;box-sizing:border-box;background:#fff;color:#222;border:1px solid #ddd;border-radius:14px;box-shadow:0 8px 40px #0003;display:flex;flex-direction:column;padding:12px;gap:10px;font:14px/1.5 system-ui}#h3ProductionPanel[hidden]{display:none}#h3ProductionPanel header{display:flex;align-items:center;justify-content:space-between;gap:10px}#h3ProductionPanel button{font:inherit;padding:7px 10px;border:1px solid #d8d8d8;border-radius:7px;background:#fff;color:#222;cursor:pointer}#h3ProductionPanel button:disabled{opacity:.5;cursor:default}#h3ProductionPanel textarea{box-sizing:border-box;width:100%;min-height:95px;max-height:28vh;resize:vertical;font:inherit;padding:9px;border:1px solid #ccc;border-radius:8px}#h3ProductionLog{overflow:auto;min-height:60px;max-height:38vh;white-space:pre-wrap;overflow-wrap:anywhere;padding:6px;background:#fafafa;border-radius:8px}#h3ProductionPanel .h3pa-row{display:flex;flex-wrap:wrap;gap:7px;align-items:center}#h3ProductionPanel .h3pa-note{font-size:12px;color:#666}#h3ProductionPlan{white-space:pre-wrap;overflow:auto;max-height:25vh;border:1px solid #e2e2e2;border-radius:7px;padding:8px;overflow-wrap:anywhere}#h3ProductionSend,#h3ProductionExecute{background:#245edb!important;color:white!important;border-color:#245edb!important}';
    doc.head.appendChild(style);
    const toggle=doc.createElement('button');toggle.id='h3ProductionToggle';toggle.textContent='제작 도우미 · Grok';doc.body.appendChild(toggle);
    const panel=doc.createElement('section');panel.id='h3ProductionPanel';panel.hidden=true;panel.setAttribute('aria-label','Grok 영상 제작 도우미');
    panel.innerHTML='<header><strong>영상 제작 도우미 · Grok</strong><button id="h3ProductionClose" aria-label="도우미 닫기">닫기</button></header><div class="h3pa-note">현재 입력·최종 프롬프트와 필요한 앱 정보를 참고합니다. 다른 대기 항목은 번호로 요청하세요.</div><div id="h3ProductionLog" role="log" aria-live="polite"></div><label for="h3ProductionInput">요청</label><textarea id="h3ProductionInput" maxlength="8000" placeholder="예: 현재 설정을 설명해줘 / 대기 2번 프롬프트와 비교해줘 / 길이를 5초로 바꾸고 1순위로 추가해줘"></textarea><div class="h3pa-row"><button id="h3ProductionSend">보내기</button><button id="h3ProductionCancel" hidden>요청 취소</button><button id="h3ProductionNew">새 대화</button></div><label class="h3pa-note"><input type="checkbox" id="h3ProductionAuto"> 명확하게 요청한 변경은 바로 실행</label><div class="h3pa-note" id="h3ProductionStatus" role="status"></div><div id="h3ProductionPlan" hidden></div><div class="h3pa-row"><button id="h3ProductionExecute" hidden>변경안 실행</button></div>';
    doc.body.appendChild(panel);
    const $=id=>doc.getElementById(id),refs={map:new WeakMap(),next:0};
    let conversation=[],job=null,pending=null,busy=false,executing=false;
    const post=async(path,body)=>{const response=await win.fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw Error(value.error||'앱 요청을 처리하지 못했습니다.');return value;};
    const say=text=>{$('h3ProductionStatus').textContent=text;};
    const log=(role,text)=>{const row=doc.createElement('div');row.textContent=(role==='user'?'나: ':'Grok: ')+text;row.style.marginBottom='12px';$('h3ProductionLog').appendChild(row);$('h3ProductionLog').scrollTop=$('h3ProductionLog').scrollHeight;conversation.push({role,text:String(text).slice(0,8000)});conversation=conversation.slice(-12);};
    const setBusy=value=>{busy=value;for(const id of ['h3ProductionSend','h3ProductionNew','h3ProductionExecute'])$(id).disabled=value;$('h3ProductionCancel').hidden=!value||executing;};
    try{$('h3ProductionAuto').checked=win.localStorage.getItem('h3simple.productionAssistant.auto.v1')==='true';}catch{}
    $('h3ProductionAuto').onchange=()=>{try{win.localStorage.setItem('h3simple.productionAssistant.auto.v1',String($('h3ProductionAuto').checked));}catch{}};
    toggle.onclick=()=>{panel.hidden=false;toggle.hidden=true;};
    $('h3ProductionClose').onclick=()=>{panel.hidden=true;toggle.hidden=false;};
    $('h3ProductionNew').onclick=()=>{conversation=[];pending=null;$('h3ProductionLog').replaceChildren();$('h3ProductionPlan').hidden=true;$('h3ProductionExecute').hidden=true;say('새 대화를 시작합니다. 화면 입력과 대기열은 그대로입니다.');};
    $('h3ProductionCancel').onclick=async()=>{if(job){$('h3ProductionCancel').disabled=true;try{await post('/api/prompt-helper/cancel',{id:job});say('도우미 요청을 취소하고 있습니다.');}catch(error){say(error.message);}finally{$('h3ProductionCancel').disabled=false;}}};
    async function execute(){
      if(!pending||busy||executing)return;
      const item=pending;pending=null;executing=true;setBusy(true);$('h3ProductionExecute').hidden=true;
      let completed=0;
      try{
        preflight(item.plan.actions,item.snapshot,item.guard);
        for(let index=0;index<item.plan.actions.length;index++){
          const claimed=await post('/api/production-assistant/claim',{plan_id:item.plan.plan_id,index});
          if(claimed.already_claimed)throw Error('이미 실행 요청한 변경안입니다. 상태를 확인해 주세요.');
          const action=claimed.action;
          try{
            if(action.kind==='api'){
              const bindings={};for(const entry of item.snapshot.bridges){const values=entry.bridge.bindings?.()||{};Object.defineProperties(bindings,Object.getOwnPropertyDescriptors(values));}
              const args=bindArgs(JSON.parse(action.args),bindings);
              const result=await post('/api/production-assistant/execute',{plan_id:item.plan.plan_id,index,args});
              if(!result.ok)throw Error(result.receipt?.message||'실행 결과를 확인하지 못했습니다.');
              if(result.result?.failed?.length)throw Error(`일부 항목 ${result.result.failed.length}건은 적용하지 못했습니다. 앱의 대상별 상태를 확인해 주세요.`);
              for(const entry of item.snapshot.bridges)entry.bridge.afterApi?.(action.path,result.result);
            }else{
              const record=item.snapshot.nodes.get(action.target);
              if(!record)throw Error('화면의 대상이 사라졌습니다.');
              if(action.kind==='set')setControl(record,action);else clickControl(record);
              await post('/api/production-assistant/finish',{plan_id:item.plan.plan_id,index,ok:true});
            }
          }catch(error){if(action.kind!=='api')try{await post('/api/production-assistant/finish',{plan_id:item.plan.plan_id,index,ok:false});}catch{}throw error;}
          completed++;say(`${completed}/${item.plan.actions.length} 요청 전달`);
        }
        for(const entry of item.snapshot.bridges)entry.bridge.refresh?.();
        log('assistant',`${completed}개 변경·실행 요청을 앱에 전달했습니다. 생성·재생·파일 선택은 화면의 진행 상태를 확인하세요.`);say('처리했습니다.');
      }catch(error){say(`중단: ${error.message} 이미 전달된 요청은 앱 상태를 확인하세요.`);log('assistant',`실행 결과: ${error.message} 일부 요청이 이미 처리됐을 수 있으므로 자동 재시도하지 않습니다.`);}
      finally{executing=false;setBusy(false);}
    }
    $('h3ProductionExecute').onclick=execute;
    $('h3ProductionSend').onclick=async()=>{
      if(busy||executing)return;const message=$('h3ProductionInput').value.trim();if(!message)return say('요청을 적어 주세요.');
      let snapshot,guard;try{snapshot=collect(win,refs);guard=sourceGuard(snapshot);}catch(error){return say(error.message);}
      const previous=conversation.slice(),auto=$('h3ProductionAuto').checked;let proposal=null;if(pending){try{preflight(pending.plan.actions,pending.snapshot,pending.guard);proposal={actions:pending.plan.actions};}catch{}}
      pending=null;$('h3ProductionPlan').hidden=true;$('h3ProductionExecute').hidden=true;
      log('user',message);$('h3ProductionInput').value='';setBusy(true);say('현재 화면과 필요한 앱 정보를 확인하고 있습니다…');
      try{
        const started=await post('/api/production-assistant/start',{message,controls:snapshot.controls,contexts:snapshot.contexts,conversation:previous,...(proposal?{proposal}:{})});job=started.id;
        while(job){
          const response=await win.fetch('/api/production-assistant/status?id='+encodeURIComponent(job),{cache:'no-store'}),state=await response.json();
          if(!response.ok)throw Error(state.error||'도우미 상태를 확인하지 못했습니다.');
          if(state.state==='done'){
            const plan=state.production;log('assistant',plan.reply);
            if(plan.actions.length){pending={plan,snapshot,guard};$('h3ProductionPlan').textContent=plan.actions.map((action,index)=>`${index+1}. ${action.label}`).join('\n');$('h3ProductionPlan').hidden=false;$('h3ProductionExecute').hidden=false;}
            say(plan.actions.length?'변경안을 확인하거나 실행하세요.':'답변을 받았습니다.');
            if(auto&&plan.auto_eligible&&plan.actions.length){setBusy(false);await execute();}
            break;
          }
          if(['error','cancelled'].includes(state.state))throw Error(state.error||'도우미 요청이 중단됐습니다.');
          await new Promise(resolve=>win.setTimeout(resolve,1300));
        }
      }catch(error){say(error.message);}
      finally{job=null;setBusy(false);}
    };
    $('h3ProductionInput').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();$('h3ProductionSend').click();}});
  }
  return {valueOf,replaceOne,bindArgs,collect,sourceGuard,checkSources,preflight,setControl,clickControl,mount};
});
