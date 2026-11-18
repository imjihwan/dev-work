/* App-specific Grok assistant. No eval, injected scripts, filesystem or external URLs. */
(function(factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else api.mount(window);
})(function(){
  'use strict';
  const CHAT_STYLES='\n:root{--h3pa-width:clamp(360px,30vw,440px)}\n#h3ProductionToggle{position:fixed;right:16px;bottom:max(18px,env(safe-area-inset-bottom));z-index:100010;border:0;border-radius:24px;padding:12px 18px;background:var(--acc,#245edb);color:#fff;box-shadow:0 3px 16px #0003;font:600 14px system-ui;cursor:pointer}\n#h3ProductionPanel{--pa-bg:var(--card,#fff);--pa-ink:var(--ink,#222);--pa-line:var(--line,#ddd);--pa-soft:var(--soft,#f4f5f7);--pa-muted:var(--mute,#676b74);position:fixed;right:0;top:var(--h3pa-view-top,0px);width:var(--h3pa-width);height:100vh;height:var(--h3pa-view-height,100dvh);z-index:100011;box-sizing:border-box;background:var(--pa-bg);color:var(--pa-ink);border-left:1px solid var(--pa-line);display:flex;flex-direction:column;font:14px/1.65 system-ui,sans-serif;box-shadow:-8px 0 28px #00000008;isolation:isolate}\n#h3ProductionPanel *,#h3ProductionPanel *:before,#h3ProductionPanel *:after{box-sizing:border-box}\n#h3ProductionPanel[hidden],#h3ProductionToggle[hidden],#h3ProductionPanel [hidden]{display:none!important}\n#h3ProductionPanel header{flex:none;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:14px 16px;border-bottom:1px solid var(--pa-line)}\n#h3ProductionPanel .h3pa-heading{display:flex;align-items:center;gap:8px;min-width:0}#h3ProductionPanel .h3pa-badge{font-size:11px;font-weight:600;color:var(--acc,#245edb);background:var(--acc-soft,var(--pa-soft));border-radius:6px;padding:2px 6px}\n#h3ProductionEffort{font:12px system-ui;padding:5px 2px;border:1px solid var(--pa-line);border-radius:6px;background:var(--pa-bg);color:var(--pa-ink);max-width:76px}#h3ProductionPanel .h3pa-tools{display:flex;gap:4px;align-items:center}#h3ProductionPanel button{font:inherit;font-size:12px;line-height:1.4;padding:7px 9px;border:1px solid var(--pa-line);border-radius:8px;background:var(--pa-bg);color:var(--pa-ink);cursor:pointer;white-space:nowrap}#h3ProductionPanel button:hover{border-color:var(--acc,#245edb)}#h3ProductionPanel button:focus-visible,#h3ProductionPanel textarea:focus-visible{outline:2px solid var(--acc,#245edb);outline-offset:2px}#h3ProductionPanel button:disabled{opacity:.45;cursor:default}\n#h3ProductionLog{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;padding:20px 16px;scroll-padding-block:16px;overflow-wrap:anywhere}\n#h3ProductionPanel .h3pa-welcome{padding:20px 2px 10px;color:var(--pa-muted)}#h3ProductionPanel .h3pa-welcome strong{display:block;font-size:21px;letter-spacing:-.6px;line-height:1.35;color:var(--pa-ink);margin-bottom:10px}#h3ProductionPanel .h3pa-welcome p{font-size:13px;margin:0 0 18px}#h3ProductionPanel .h3pa-suggestions{display:grid;gap:8px}#h3ProductionPanel .h3pa-suggestions button{text-align:left;white-space:normal;padding:11px 12px;background:var(--pa-soft);border-color:transparent;font-size:13px}\n#h3ProductionPanel .h3pa-message{display:flex;flex-direction:column;align-items:flex-start;margin:0 0 20px;gap:5px}#h3ProductionPanel .h3pa-message[data-role=user]{align-items:flex-end}#h3ProductionPanel .h3pa-author{font-size:11px;font-weight:600;color:var(--pa-muted)}#h3ProductionPanel .h3pa-message-body{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%;line-height:1.7}#h3ProductionPanel .h3pa-message[data-role=user] .h3pa-message-body{max-width:94%;background:var(--pa-soft);border-radius:13px 13px 3px 13px;padding:10px 13px}#h3ProductionPanel .h3pa-message[data-role=assistant] .h3pa-message-body{padding:2px 0}\n#h3ProductionPanel .h3pa-thinking{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--pa-muted);margin:8px 0 20px}#h3ProductionPanel .h3pa-thinking:before{content:"";height:12px;width:12px;border:2px solid var(--pa-line);border-top-color:var(--acc,#245edb);border-radius:50%;animation:h3pa-spin .8s linear infinite}@keyframes h3pa-spin{to{transform:rotate(360deg)}}\n#h3ProductionPanel .h3pa-plan{width:100%;margin-top:8px;border:1px solid var(--pa-line);border-radius:11px;padding:12px;background:var(--pa-bg)}#h3ProductionPanel .h3pa-plan-head{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;margin-bottom:8px}#h3ProductionPanel .h3pa-plan-state{color:var(--pa-muted);font-size:11px}#h3ProductionPanel .h3pa-plan-step{font-size:13px;padding:7px 0;border-top:1px solid var(--pa-line);white-space:pre-wrap;overflow-wrap:anywhere}#h3ProductionPanel .h3pa-plan-step:first-child{border-top:0}#h3ProductionPanel details{margin:5px 0}#h3ProductionPanel summary{cursor:pointer;color:var(--pa-muted);font-size:12px}#h3ProductionPanel pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto;background:var(--pa-soft);border-radius:7px;padding:9px;font:12px/1.6 system-ui;margin:7px 0}#h3ProductionPanel .h3pa-plan-actions{display:flex;justify-content:flex-end;gap:6px;margin-top:9px}\n#h3ProductionPanel .h3pa-composer{flex:none;border-top:1px solid var(--pa-line);padding:12px 14px max(12px,env(safe-area-inset-bottom));background:var(--pa-bg)}#h3ProductionPanel .h3pa-compose-box{border:1px solid var(--pa-line);border-radius:12px;padding:4px;background:var(--pa-bg)}#h3ProductionPanel .h3pa-compose-box:focus-within{border-color:var(--acc,#245edb)}#h3ProductionPanel textarea{box-sizing:border-box;display:block;width:100%;height:72px;min-height:64px;max-height:min(200px,28vh);border:0;outline:0!important;border-radius:9px;resize:none;background:transparent;color:var(--pa-ink);padding:8px;font:14px/1.6 system-ui;overflow:auto}#h3ProductionPanel .h3pa-send-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 4px 4px}#h3ProductionPanel .h3pa-keyhint,#h3ProductionPanel .h3pa-note{font-size:11px;color:var(--pa-muted)}#h3ProductionPanel .h3pa-controls{display:flex;gap:6px;align-items:center}#h3ProductionPanel .h3pa-auto{display:flex;gap:7px;align-items:center;margin:10px 0 0;font-size:11px;color:var(--pa-muted);font-weight:400}#h3ProductionPanel .h3pa-auto input{width:auto;min-height:0;padding:0;flex:none;margin:0;accent-color:var(--acc,#245edb)}#h3ProductionStatus{font-size:11px;color:var(--pa-muted);margin:7px 0 0;min-height:16px;overflow-wrap:anywhere}#h3ProductionSend,#h3ProductionExecute{background:var(--acc,#245edb)!important;color:#fff!important;border-color:var(--acc,#245edb)!important}#h3ProductionLatest{align-self:center;margin:0 0 8px!important;box-shadow:0 2px 10px #0001}\n@media(min-width:1280px){body.h3pa-open:not(.h3pa-full){padding-right:var(--h3pa-width)}body.h3pa-full #h3ProductionPanel{width:100%;border:0}body.h3pa-full #h3ProductionLog{padding:24px max(24px,calc((100vw - 850px)/2))}body.h3pa-full #h3ProductionPanel .h3pa-composer{padding-left:max(24px,calc((100vw - 850px)/2));padding-right:max(24px,calc((100vw - 850px)/2))}}\n@media(max-width:1279px){#h3ProductionPanel{width:100%;border:0}#h3ProductionExpand{display:none}#h3ProductionPanel textarea{font-size:16px}#h3ProductionPanel header{padding:11px 14px}#h3ProductionLog{padding:16px}#h3ProductionPanel .h3pa-keyhint{font-size:10px}}\n@media(prefers-reduced-motion:reduce){#h3ProductionPanel .h3pa-thinking:before{animation:none}}\n';
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
    style.textContent=CHAT_STYLES;
    doc.head.appendChild(style);
    const toggle=doc.createElement('button');toggle.id='h3ProductionToggle';toggle.textContent='제작 도우미 · Grok';doc.body.appendChild(toggle);
    const panel=doc.createElement('section');panel.id='h3ProductionPanel';panel.hidden=true;panel.setAttribute('aria-label','Grok 영상 제작 도우미');
    panel.innerHTML='<header><div class="h3pa-heading"><strong>제작 도우미</strong><span class="h3pa-badge">Grok 4.7</span><select id="h3ProductionEffort" aria-label="응답 방식" title="같은 Grok 4.7의 추론 강도"><option value="low">빠르게</option><option value="medium">균형</option><option value="high" selected>정밀</option><option value="xhigh">최대</option></select></div><div class="h3pa-tools"><button id="h3ProductionNew" title="입력과 작업은 유지하고 새 대화 시작">새 대화</button><button id="h3ProductionExpand" aria-label="대화 전체 화면" aria-pressed="false">넓게</button><button id="h3ProductionClose" aria-label="대화를 접고 작업 화면 보기">접기</button></div></header><div id="h3ProductionLog" role="log" aria-live="polite" aria-label="제작 도우미 대화"><div class="h3pa-welcome" id="h3ProductionWelcome"><strong>영상 작업을<br>대화로 이어가세요</strong><p>프롬프트를 다듬고, 설정과 대기열을 관리하세요. 질문부터 시작해도 됩니다.</p><div class="h3pa-suggestions"><button id="h3ProductionExample1">현재 프롬프트와 설정 설명해줘</button><button id="h3ProductionExample2">대기 항목과 비교하고 싶어</button><button id="h3ProductionExample3">동작과 시간 흐름을 검토해줘</button></div></div><div id="h3ProductionThinking" class="h3pa-thinking" hidden><span id="h3ProductionThinkingText">Grok이 확인하고 있어요</span></div></div><button id="h3ProductionLatest" hidden>최신 대화로 ↓</button><div id="h3ProductionPlanHome" hidden><div id="h3ProductionPlan" class="h3pa-plan" hidden><div class="h3pa-plan-head"><strong>변경안</strong><span id="h3ProductionPlanState" class="h3pa-plan-state">확인 대기</span></div><div id="h3ProductionPlanSteps"></div><div id="h3ProductionPlanActions" class="h3pa-plan-actions"><button id="h3ProductionExecute" hidden>변경안 실행</button></div></div></div><div class="h3pa-composer"><label for="h3ProductionInput" class="h3pa-note">이어 할 말이나 수정 요청</label><div class="h3pa-compose-box"><textarea id="h3ProductionInput" rows="3" maxlength="8000" placeholder="예: 마지막 동작만 더 천천히 바꿔줘"></textarea><div class="h3pa-send-row"><span class="h3pa-keyhint" id="h3ProductionKeyHint">Enter 전송 · Shift+Enter 줄바꿈</span><div class="h3pa-controls"><button id="h3ProductionCancel" hidden>응답 중지</button><button id="h3ProductionSend">보내기 ↑</button></div></div></div><label class="h3pa-auto"><input type="checkbox" id="h3ProductionAuto">명확하게 요청한 변경은 바로 실행</label><div id="h3ProductionStatus" role="status">입력·최종 프롬프트와 필요한 앱 정보를 참고합니다.</div><div id="h3ProductionStorage" class="h3pa-note">최근 대화·입력은 이 브라우저에 저장됩니다. 새 대화로 지울 수 있습니다.</div></div>';
    doc.body.appendChild(panel);
    const $=id=>doc.getElementById(id),refs={map:new WeakMap(),next:0};
    let conversation=[],job=null,pending=null,busy=false,executing=false;
    const chatKey='h3simple.productionAssistant.chat.v1',draftKey=chatKey+'.draft',rowEntries=new WeakMap();
    let transcript=[],restoring=false;
    let sharedMode=null,sharedRevision=null,sharedSession=null,remoteBusy=false,syncPromise=null;
    const effortLabels={low:'빠르게',medium:'균형',high:'정밀',xhigh:'최대'};
    try{const saved=win.localStorage.getItem('h3simple.productionAssistant.effort.v1');$('h3ProductionEffort').value=Object.hasOwn(effortLabels,saved)?saved:'high';}catch{$('h3ProductionEffort').value='high';}
    $('h3ProductionEffort').addEventListener('input',event=>event.stopImmediatePropagation?.());
    $('h3ProductionEffort').onchange=event=>{event?.stopImmediatePropagation?.();try{win.localStorage.setItem('h3simple.productionAssistant.effort.v1',$('h3ProductionEffort').value);}catch{}};
    const post=async(path,body)=>{const response=await win.fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw Error(value.error||'앱 요청을 처리하지 못했습니다.');return value;};
    let follow=true,full=false,activePlanView=null,scrollRevision=0;
    const say=text=>{$('h3ProductionStatus').textContent=text;};
    function scrollChat(force=false){
      if(force)follow=true;
      if(follow){$('h3ProductionLog').scrollTop=$('h3ProductionLog').scrollHeight;$('h3ProductionLatest').hidden=true;}else $('h3ProductionLatest').hidden=false;
    }
    $('h3ProductionLog').addEventListener('scroll',()=>{scrollRevision++;const node=$('h3ProductionLog');follow=node.scrollHeight-node.scrollTop-node.clientHeight<64;if(follow)$('h3ProductionLatest').hidden=true;});
    $('h3ProductionLatest').onclick=()=>scrollChat(true);
    const log=(role,text,forceUser=true)=>{
      $('h3ProductionWelcome').hidden=true;
      const row=doc.createElement('article');row.className='h3pa-message';row.setAttribute('data-role',role);
      const author=doc.createElement('div');author.className='h3pa-author';author.textContent=role==='user'?'나':'Grok';row.appendChild(author);
      const body=doc.createElement('div');body.className='h3pa-message-body';body.textContent=text;row.appendChild(body);
      $('h3ProductionLog').appendChild(row);scrollChat(role==='user'&&forceUser);conversation.push({role,text:String(text).slice(0,8000)});conversation=conversation.slice(-12);
      const entry={role,text:String(text).slice(0,8000)};transcript.push(entry);transcript=transcript.slice(-100);rowEntries.set(row,entry);saveChat();return row;
    };
    function planSummary(plan){
      return plan.actions.slice(0,24).map(action=>{
        let changes=action.kind==='set'?[{before:action.before,after:action.value}]:[];
        if(action.kind==='api')try{const args=JSON.parse(action.args);if(Array.isArray(args.edits))changes=args.edits.filter(edit=>typeof edit.before==='string'&&typeof edit.after==='string');}catch{}
        return {label:String(action.label||'').slice(0,600),changes:changes.slice(0,24).map(change=>({before:String(change.before??'').slice(0,8000),after:String(change.after??'').slice(0,8000)}))};
      });
    }
    function summarySteps(container,steps){
      container.replaceChildren();
      steps.forEach((action,index)=>{
        const step=doc.createElement('div');step.className='h3pa-plan-step';const label=doc.createElement('div');label.textContent=`${index+1}. ${action.label}`;step.appendChild(label);
        const changes=action.changes;
        if(changes.length){const detail=doc.createElement('details'),summary=doc.createElement('summary');summary.textContent='변경 내용 보기';detail.appendChild(summary);const content=doc.createElement('pre');content.textContent=changes.map(change=>`기존: ${change.before||'(비어 있음)'}\n변경: ${change.after||'(삭제)'}`).join('\n\n');detail.appendChild(content);step.appendChild(detail);}
        container.appendChild(step);
      });
    }
    function planSteps(container,plan){summarySteps(container,planSummary(plan));}
    function readonlyPlan(row,steps,state){
      const card=doc.createElement('div');card.className='h3pa-plan';
      const heading=doc.createElement('div');heading.className='h3pa-plan-head';heading.textContent=`변경안 · ${state}`;card.appendChild(heading);
      const content=doc.createElement('div');summarySteps(content,steps);card.appendChild(content);row.appendChild(card);
    }
    function saveChat(){
      if(restoring)return;
      const draft=$('h3ProductionInput').value.slice(0,8000),inFlight=busy||executing;
      let messages=transcript.slice(-100);
      while(messages.length>1&&JSON.stringify(messages).length>750000)messages=messages.slice(1);
      if(JSON.stringify(messages).length>750000)messages=messages.map(entry=>({...entry,...(entry.plan?{plan:{...entry.plan,steps:entry.plan.steps.map(step=>({label:step.label,changes:[]}))}}:{})}));
      try{
        if(!messages.length&&!draft&&!inFlight)win.localStorage.removeItem(chatKey);
        else {
          // Store display text only: never persist executable plans, DOM targets or bindings.
          for(;;)try{win.localStorage.setItem(chatKey,JSON.stringify({version:1,messages,draft,inFlight}));break;}catch(error){if(messages.length<=1)throw error;messages=messages.slice(Math.max(1,Math.floor(messages.length/2)));}
        }
        $('h3ProductionStorage').textContent=sharedMode?'대화는 서버에 공유됩니다. 작성 중인 입력은 이 기기에만 저장합니다.':'최근 대화·입력은 이 브라우저에 저장됩니다. 새 대화로 지울 수 있습니다.';
      }catch{$('h3ProductionStorage').textContent='브라우저에 대화를 저장하지 못했습니다. 새로고침하면 최근 대화가 사라질 수 있습니다.';}
    }
    function setPlanState(state){
      $('h3ProductionPlanState').textContent=state;
      if(activePlanView?.entry?.plan)activePlanView.entry.plan.state=state;
      saveChat();
    }
    function restoreChat(){
      try{
        const raw=win.localStorage.getItem(chatKey);if(!raw)return;
        if(raw.length>1000000)throw Error('Stored chat too large');
        const data=JSON.parse(raw);if(data?.version!==1||!Array.isArray(data.messages))return;
        restoring=true;
        for(const saved of data.messages.slice(-100)){
          if(!saved||!['user','assistant'].includes(saved.role)||typeof saved.text!=='string')continue;
          const row=log(saved.role,saved.text.slice(0,8000)),entry=rowEntries.get(row);
          if(saved.role==='assistant'&&Array.isArray(saved.plan?.steps)){
            const steps=saved.plan.steps.slice(0,24).filter(step=>step&&typeof step.label==='string').map(step=>({label:step.label.slice(0,600),changes:(Array.isArray(step.changes)?step.changes:[]).slice(0,24).filter(change=>change&&typeof change.before==='string'&&typeof change.after==='string').map(change=>({before:change.before.slice(0,8000),after:change.after.slice(0,8000)}))}));
            const prior=String(saved.plan.state||'').slice(0,100),state=prior==='확인 대기'?'읽기 전용 · 다시 검토 필요':prior==='실행 중'?'새로고침 전 실행 중 · 상태 확인':prior||'읽기 전용';
            entry.plan={steps,state};readonlyPlan(row,steps,state);
          }
        }
        conversation=transcript.slice(-12).map(entry=>({role:entry.role,text:(entry.text+(entry.plan?'\n[이전 변경안 기록 · '+entry.plan.state+']\n'+entry.plan.steps.map(step=>step.label+'\n'+step.changes.map(change=>'기존: '+change.before+'\n변경: '+change.after).join('\n')).join('\n'):'')).slice(0,8000)}));
        $('h3ProductionInput').value=typeof data.draft==='string'?data.draft.slice(0,8000):'';resizeComposer();scrollChat(true);
        if(data.inFlight)say('대화를 복원했습니다. 이전 요청은 자동 재실행하지 않습니다. 앱에서 처리 상태를 확인하세요.');
        else if(transcript.length)say('이 브라우저의 이전 대화를 복원했습니다. 이어서 이야기하세요.');
      }catch{say('저장된 대화를 복원하지 못했습니다. 새 대화를 시작할 수 있습니다.');}
      finally{restoring=false;}
    }
    function archivePlan(replaced=false){
      if(activePlanView){
        const state=$('h3ProductionPlanState').textContent,recorded=replaced&&state==='확인 대기'?'새 요청으로 대체됨':state;
        if(activePlanView.entry?.plan)activePlanView.entry.plan.state=recorded;
        readonlyPlan(activePlanView.row,planSummary(activePlanView.plan),recorded);
      }
      $('h3ProductionPlanHome').appendChild($('h3ProductionPlan'));$('h3ProductionPlan').hidden=true;$('h3ProductionExecute').hidden=true;activePlanView=null;saveChat();
    }
    function renderShared(data){
      restoring=true;
      try{
        archivePlan();pending=null;conversation=[];transcript=[];
        $('h3ProductionLog').replaceChildren($('h3ProductionWelcome'),$('h3ProductionThinking'));$('h3ProductionWelcome').hidden=true;
        for(const saved of data.messages.slice(-100)){
          if(!saved||!['user','assistant'].includes(saved.role)||typeof saved.text!=='string')continue;
          const row=log(saved.role,saved.text.slice(0,8000),false),entry=rowEntries.get(row);entry.id=String(saved.id||'').slice(0,80);
          if(saved.role==='assistant'&&Array.isArray(saved.plan?.steps)){
            const steps=saved.plan.steps.slice(0,24).filter(step=>step&&typeof step.label==='string').map(step=>({label:step.label.slice(0,600),changes:(Array.isArray(step.changes)?step.changes:[]).slice(0,24).filter(change=>change&&typeof change.before==='string'&&typeof change.after==='string').map(change=>({before:change.before.slice(0,8000),after:change.after.slice(0,8000)}))}));
            const prior=String(saved.plan.state||'').slice(0,100),state=prior==='확인 대기'?'읽기 전용 · 다시 검토 필요':prior;
            entry.plan={steps,state};readonlyPlan(row,steps,state);
          }
        }
        $('h3ProductionWelcome').hidden=transcript.length>0;
        conversation=transcript.slice(-12).map(entry=>({role:entry.role,text:(entry.text+(entry.plan?'\n[이전 변경안 기록 · '+entry.plan.state+']\n'+entry.plan.steps.map(step=>step.label+'\n'+step.changes.map(change=>'기존: '+change.before+'\n변경: '+change.after).join('\n')).join('\n'):'')).slice(0,8000)}));
        sharedRevision=data.revision;sharedSession=data.session_id;
        if(data.revision>0&&!data.messages.length)try{win.localStorage.removeItem(chatKey);}catch{}
      }finally{restoring=false;}
      showSharedActive(data.active);saveChat();scrollChat();
    }
    function showSharedActive(active){
      remoteBusy=!!active&&!busy&&!executing;
      if(!busy&&!executing){
        $('h3ProductionThinking').hidden=!remoteBusy;
        if(remoteBusy){$('h3ProductionLog').appendChild($('h3ProductionThinking'));$('h3ProductionThinkingText').textContent='다른 기기의 요청을 처리하고 있어요';say('같은 대화의 응답을 기다리고 있습니다. 완료되면 자동으로 표시합니다.');}
        for(const id of ['h3ProductionSend','h3ProductionNew','h3ProductionExecute','h3ProductionEffort'])$(id).disabled=remoteBusy;
      }
    }
    async function getShared(){
      const query=Number.isInteger(sharedRevision)&&sharedSession?'?revision='+sharedRevision+'&session='+encodeURIComponent(sharedSession):'';
      const response=await win.fetch('/api/production-assistant/conversation'+query,{cache:'no-store'});
      if(response.status===404)return null;
      const data=await response.json();
      const unchanged=data.unchanged===true&&data.revision===sharedRevision&&data.session_id===sharedSession;
      if(!response.ok||!Number.isInteger(data.revision)||!unchanged&&!Array.isArray(data.messages)||typeof data.session_id!=='string')throw Error('공유 대화를 불러오지 못했습니다. 연결을 확인해 주세요.');
      return data;
    }
    async function bootShared(){
      try{
        let data=await getShared();if(data===null){sharedMode=false;return;}
        sharedMode=true;
        if(data.revision===0&&!data.messages.length&&transcript.length){
          try{data=await post('/api/production-assistant/conversation',{operation:'import',revision:0,messages:transcript});}
          catch{data=await getShared();if(!data)throw Error('공유 대화를 불러오지 못했습니다.');}
        }
        renderShared(data);say('서버의 공통 대화를 불러왔습니다. 다른 기기에서도 이어서 볼 수 있습니다.');
      }catch{sharedMode=true;$('h3ProductionStorage').textContent='공유 대화를 불러오지 못했습니다. 연결되면 다시 동기화합니다.';}
    }
    async function syncShared(){
      if(sharedMode===false)return true;
      if(busy||executing)return false;
      if(syncPromise)return syncPromise;
      syncPromise=(async()=>{
        try{
          let data=await getShared();if(!data)throw Error('공유 대화를 사용할 수 없습니다.');
          if(sharedRevision===null&&data.revision===0&&!data.messages.length&&transcript.length){
            try{data=await post('/api/production-assistant/conversation',{operation:'import',revision:0,messages:transcript});}
            catch{data=await getShared();if(!data)throw Error('공유 대화를 사용할 수 없습니다.');}
          }
          sharedMode=true;
          if(data.revision!==sharedRevision||data.session_id!==sharedSession)renderShared(data);else showSharedActive(data.active);
          return true;
        }catch{$('h3ProductionStorage').textContent='서버 연결을 확인해 주세요. 대화를 덮어쓰지 않았습니다.';return false;}
        finally{syncPromise=null;}
      })();
      return syncPromise;
    }
    function showPlan(plan,row){
      activePlanView={plan,row,entry:rowEntries.get(row)};activePlanView.entry.plan={steps:planSummary(plan),state:'확인 대기'};setPlanState('확인 대기');planSteps($('h3ProductionPlanSteps'),plan);
      $('h3ProductionPlanActions').appendChild($('h3ProductionExecute'));row.appendChild($('h3ProductionPlan'));$('h3ProductionPlan').hidden=false;$('h3ProductionExecute').hidden=false;scrollChat();
    }
    const setBusy=value=>{
      busy=value;for(const id of ['h3ProductionSend','h3ProductionNew','h3ProductionExecute','h3ProductionEffort'])$(id).disabled=value||remoteBusy;
      $('h3ProductionCancel').hidden=!value||executing;$('h3ProductionThinking').hidden=!value;
      $('h3ProductionThinkingText').textContent=executing?'앱에 변경을 전달하고 있어요':'Grok이 확인하고 있어요';
      if(value){$('h3ProductionLog').appendChild($('h3ProductionThinking'));scrollChat();}
      toggle.textContent=value?'Grok · 처리 중':'제작 도우미 · Grok';
      saveChat();
    };
    function resizeComposer(){const input=$('h3ProductionInput');input.style.height='auto';input.style.height=Math.max(64,Math.min(200,Number(input.scrollHeight)||64))+'px';}
    $('h3ProductionInput').addEventListener('input',event=>{resizeComposer();saveChat();event.stopImmediatePropagation?.();});
    $('h3ProductionInput').addEventListener('change',event=>event.stopImmediatePropagation?.());
    $('h3ProductionAuto').addEventListener('input',event=>event.stopImmediatePropagation?.());
    panel.addEventListener('input',event=>event.stopPropagation?.());panel.addEventListener('change',event=>event.stopPropagation?.());
    const coarse=()=>!!win.matchMedia?.('(pointer: coarse)').matches;
    if(coarse())$('h3ProductionKeyHint').textContent='여러 줄 입력 · 보내기 버튼으로 전송';
    function viewport(){
      const view=win.visualViewport;
      if(view){panel.style.setProperty?.('--h3pa-view-height',view.height+'px');panel.style.setProperty?.('--h3pa-view-top',view.offsetTop+'px');}
    }
    function openPanel(open,persist=true){
      panel.hidden=!open;toggle.hidden=open;doc.body.classList?.toggle('h3pa-open',open);toggle.setAttribute('aria-expanded',String(open));
      viewport();if(open)scrollChat();if(persist)try{win.localStorage.setItem('h3simple.productionAssistant.open.v1',String(open));}catch{}
      win.dispatchEvent?.(new win.Event('resize'));
    }
    win.visualViewport?.addEventListener('resize',viewport);win.visualViewport?.addEventListener('scroll',viewport);win.addEventListener?.('resize',viewport);
    try{$('h3ProductionAuto').checked=win.localStorage.getItem('h3simple.productionAssistant.auto.v1')==='true';}catch{}
    $('h3ProductionAuto').onchange=event=>{event?.stopImmediatePropagation?.();try{win.localStorage.setItem('h3simple.productionAssistant.auto.v1',String($('h3ProductionAuto').checked));}catch{}};
    toggle.setAttribute('aria-controls','h3ProductionPanel');
    toggle.onclick=()=>{openPanel(true);if(!coarse())$('h3ProductionInput').focus?.({preventScroll:true});};
    $('h3ProductionClose').onclick=()=>openPanel(false);
    $('h3ProductionExpand').onclick=()=>{full=!full;doc.body.classList?.toggle('h3pa-full',full);$('h3ProductionExpand').textContent=full?'분할 보기':'넓게';$('h3ProductionExpand').setAttribute('aria-pressed',String(full));win.dispatchEvent?.(new win.Event('resize'));scrollChat();};
    let opened=Number(win.innerWidth||0)>=1280;try{const saved=win.localStorage.getItem('h3simple.productionAssistant.open.v1');if(saved==='true'||saved==='false')opened=saved==='true';}catch{}openPanel(opened,false);
    for(const [id,message] of [['h3ProductionExample1','현재 최종 프롬프트와 설정을 설명해줘.'],['h3ProductionExample2','대기 1번의 최종 프롬프트를 가져와 현재 내용과 비교해줘. 변경하지 마.'],['h3ProductionExample3','현재 동작이 영상 길이 안에서 자연스럽게 가능한지 검토해줘.']])$(id).onclick=()=>{const input=$('h3ProductionInput');input.value=input.value.trim()?input.value+'\n'+message:message;resizeComposer();saveChat();input.focus?.({preventScroll:true});};
    $('h3ProductionNew').onclick=async()=>{
      await sharedInit;if(busy||executing)return;
      if(sharedMode){
        try{const data=await post('/api/production-assistant/conversation',{operation:'clear',revision:sharedRevision});renderShared(data);}
        catch(error){await syncShared();return say(error.message);}
      }
      archivePlan();conversation=[];transcript=[];pending=null;$('h3ProductionInput').value='';resizeComposer();saveChat();$('h3ProductionLog').replaceChildren($('h3ProductionWelcome'),$('h3ProductionThinking'));$('h3ProductionWelcome').hidden=false;follow=true;$('h3ProductionLatest').hidden=true;say('새 대화를 시작합니다. 화면 입력과 대기열은 그대로입니다.');
    };
    $('h3ProductionCancel').onclick=async()=>{if(job){$('h3ProductionCancel').disabled=true;try{await post('/api/prompt-helper/cancel',{id:job});say('도우미 요청을 취소하고 있습니다.');}catch(error){say(error.message);}finally{$('h3ProductionCancel').disabled=false;}}};
    async function execute(){
      if(!pending||busy||executing)return;
      await sharedInit;if(sharedMode&&!(await syncShared()))return say('공유 대화를 확인한 뒤 다시 실행해 주세요.');
      if(!pending||remoteBusy)return say('다른 기기에서 대화가 갱신됐습니다. 새 변경안을 요청해 주세요.');
      const item=pending;pending=null;executing=true;setPlanState('실행 중');setBusy(true);$('h3ProductionExecute').hidden=true;
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
        setPlanState('앱에 전달됨');log('assistant',`${completed}개 변경·실행 요청을 앱에 전달했습니다. 생성·재생·파일 선택은 화면의 진행 상태를 확인하세요.`);say('처리했습니다.');
      }catch(error){setPlanState('중단 · 상태 확인');say(`중단: ${error.message} 이미 전달된 요청은 앱 상태를 확인하세요.`);log('assistant',`실행 결과: ${error.message} 일부 요청이 이미 처리됐을 수 있으므로 자동 재시도하지 않습니다.`);}
      finally{executing=false;setBusy(false);}
    }
    $('h3ProductionExecute').onclick=execute;
    $('h3ProductionSend').onclick=async()=>{
      const startScrollRevision=scrollRevision;await sharedInit;if(busy||executing)return;if(sharedMode&&!(await syncShared()))return say('공유 대화를 확인한 뒤 다시 요청해 주세요.');if(remoteBusy)return say('현재 응답이 끝난 뒤 이어서 요청해 주세요.');const message=$('h3ProductionInput').value.trim();if(!message)return say('요청을 적어 주세요.');
      let snapshot,guard;try{snapshot=collect(win,refs);guard=sourceGuard(snapshot);}catch(error){return say(error.message);}
      const previous=conversation.slice(),auto=$('h3ProductionAuto').checked,effort=$('h3ProductionEffort').value||'high',began=Date.now();let proposal=null;if(pending){try{preflight(pending.plan.actions,pending.snapshot,pending.guard);proposal={actions:pending.plan.actions};}catch{}}
      archivePlan(true);pending=null;
      const sentRow=log('user',message,startScrollRevision===scrollRevision);$('h3ProductionInput').value='';resizeComposer();setBusy(true);say('현재 화면과 필요한 앱 정보를 확인하고 있습니다…');
      try{
        const started=await post('/api/production-assistant/start',{message,effort,...(sharedMode?{chat_revision:sharedRevision}:{}),controls:snapshot.controls,contexts:snapshot.contexts,conversation:previous,...(proposal?{proposal}:{})});job=started.id;if(sharedMode&&Number.isInteger(started.chat_revision)){sharedRevision=started.chat_revision;rowEntries.get(sentRow).id=started.chat_user_id;}
        while(job){
          const response=await win.fetch('/api/production-assistant/status?id='+encodeURIComponent(job),{cache:'no-store'}),state=await response.json();
          if(!response.ok)throw Error(state.error||'도우미 상태를 확인하지 못했습니다.');
          if(!['done','error','cancelled'].includes(state.state)){const phase={prepare:'앱 정보 준비',model:'Grok 응답 대기',read:'필요한 정보 조회',validate:'변경안 검사'}[state.phase]||'Grok 응답 대기';const elapsed=Math.floor((Date.now()-began)/1000),round=Math.min(5,Math.max(0,Number(state.round)||0));const status=`${effortLabels[effort]} · ${phase}${round?' · '+round+'차 응답':''} · ${elapsed}초`;$('h3ProductionThinkingText').textContent=status;say(status);}
          if(state.state==='done'){
            const plan=state.production,row=log('assistant',plan.reply);if(sharedMode&&Number.isInteger(state.chat_revision)){sharedRevision=state.chat_revision;rowEntries.get(row).id=state.chat_message_id;}
            if(plan.actions.length){pending={plan,snapshot,guard};showPlan(plan,row);}
            say(plan.actions.length?'변경안을 확인하거나 실행하세요.':'답변을 받았습니다.');
            if(state.chat_error)$('h3ProductionStorage').textContent=state.chat_error;
            if(auto&&plan.auto_eligible&&plan.actions.length){setBusy(false);await execute();}
            break;
          }
          if(['error','cancelled'].includes(state.state))throw Error(state.error||'도우미 요청이 중단됐습니다.');
          await new Promise(resolve=>win.setTimeout(resolve,600));
        }
      }catch(error){say(error.message);log('assistant',error.message);if(!$('h3ProductionInput').value.trim()){$('h3ProductionInput').value=message;resizeComposer();saveChat();}}
      finally{job=null;setBusy(false);}
    };
    restoreChat();try{const draft=win.localStorage.getItem(draftKey);if(draft!==null){$('h3ProductionInput').value=draft.slice(0,8000);resizeComposer();}}catch{}const sharedInit=bootShared();win.addEventListener?.('pagehide',saveChat);
    win.setInterval?.(()=>{if(!doc.hidden&&!busy&&!executing)syncShared();},2000);
    doc.addEventListener?.('visibilitychange',()=>{if(!doc.hidden&&!busy&&!executing)syncShared();});
    $('h3ProductionInput').addEventListener('keydown',event=>{if(event.isComposing||event.keyCode===229||busy||event.key!=='Enter')return;if(event.ctrlKey||event.metaKey||!event.shiftKey&&!coarse()){event.preventDefault();event.stopPropagation?.();$('h3ProductionSend').click();}});
    return {ready:sharedInit,sync:syncShared};
  }
  return {CHAT_STYLES,valueOf,replaceOne,bindArgs,collect,sourceGuard,checkSources,preflight,setControl,clickControl,mount};
});
