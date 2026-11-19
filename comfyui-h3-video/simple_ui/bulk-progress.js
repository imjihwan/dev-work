(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else if(root.document){let shared;try{if(root.top!==root.self)shared=root.top.H3BulkProgress;}catch{}root.H3BulkProgress=shared||api.mount(root);}})(globalThis,()=>{
  function mount(win){
    const doc=win.document,host=doc.createElement('section'),style=doc.createElement('style');
    host.id='h3BulkProgress';host.hidden=true;host.setAttribute('aria-label','대기항목 일괄 수정 진행률');
    host.innerHTML='<div><strong data-bulk-title></strong><span data-bulk-counts role="status"></span></div><progress max="100" aria-label="대기항목 수정 처리 비율"></progress>';
    style.textContent='#h3BulkProgress{margin:8px 12px;padding:9px 12px;border:1px solid var(--line,#ddd);border-radius:8px;background:var(--card,#fff);font:12px/1.6 system-ui;color:var(--ink,#222)}#h3BulkProgress[hidden]{display:none}#h3BulkProgress>div{display:flex;flex-wrap:wrap;gap:2px 12px;justify-content:space-between}#h3BulkProgress progress{display:block;width:100%;height:9px;margin-top:5px;accent-color:var(--acc,#2f6fe4)}';
    doc.head.appendChild(style);const top=doc.querySelector('.app-top');if(top)top.after(host);else doc.body.prepend(host);
    const title=host.querySelector('[data-bulk-title]'),counts=host.querySelector('[data-bulk-counts]'),bar=host.querySelector('progress');
    let timer=null,loading=false,preparing=false,last=null;
    function render(data){
      if(data.state==='idle'||data.finished_age_seconds>60){if(!preparing)host.hidden=true;return;}
      if(preparing&&data.state!=='running')return;
      if(data.state==='running')preparing=false;
      last=data;host.hidden=false;
      const name=data.all_pending?'전체 대기항목 수정':'대기항목 일괄수정';
      const pct=Math.max(0,Math.min(100,Number(data.percent)||0));
      title.textContent=name+' · '+(data.state==='running'?pct+'%':data.state==='error'?'중단 · 상태 확인':data.failed?'완료 · 일부 미적용':'완료');
      const elapsed=Math.floor(Math.max(0,data.elapsed_seconds||0));
      counts.textContent=`처리 ${data.processed}/${data.total} · 성공 ${data.succeeded} · 실패 ${data.failed} · ${String(Math.floor(elapsed/60)).padStart(2,'0')}:${String(elapsed%60).padStart(2,'0')}`;
      bar.value=pct;
    }
    async function poll(){
      win.clearTimeout(timer);if(loading||doc.hidden)return;
      loading=true;
      try{const response=await win.fetch('/api/queue/bulk-progress',{cache:'no-store'});if(!response.ok)throw Error('status');render(await response.json());}
      catch{if(!host.hidden){title.textContent='일괄 수정 · 연결 확인 중';counts.textContent='처리 결과를 확인하고 있습니다. 자동으로 다시 적용하지 않습니다.';bar.removeAttribute('value');}}
      finally{loading=false;if(!doc.hidden)timer=win.setTimeout(poll,last?.state==='running'||preparing?1000:3000);}
    }
    function prepare(){preparing=true;host.hidden=false;title.textContent='일괄 수정 · 대상 확인 중';counts.textContent='저장 시점의 대기항목을 확인합니다.';bar.removeAttribute('value');poll();}
    function complete(result){
      preparing=false;const success=result.updated_count??result.jobs?.length??0,failed=result.failed?.length||0,total=result.target_count??success+failed;
      render({state:'done',all_pending:!!result.all_pending,total,processed:success+failed,succeeded:success,failed,verified:result.verified_count||0,percent:total?(success+failed)*100/total:100,elapsed_seconds:last?.elapsed_seconds||0,finished_age_seconds:0});poll();
    }
    doc.addEventListener('visibilitychange',()=>{if(doc.hidden)win.clearTimeout(timer);else poll();});poll();
    function uncertain(){preparing=false;poll();}
    return {prepare,complete,poll,render,uncertain};
  }
  return {mount};
});
