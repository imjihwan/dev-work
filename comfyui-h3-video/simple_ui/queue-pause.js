(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else api.mount(root);})(globalThis,()=>{
  function mount(win){
    const doc=win.document,host=doc.getElementById('queuePauseHost');if(!host)return;
    const button=doc.createElement('button'),status=doc.createElement('span');
    button.type='button';button.disabled=true;button.textContent='일시정지 확인 중';
    button.style.cssText='min-height:40px;padding:6px 10px;font:inherit;font-size:12px;white-space:normal';
    status.setAttribute('role','status');status.style.cssText='font-size:11px;display:block;max-width:240px';
    host.appendChild(button);host.appendChild(status);
    let state=null,busy=false,loading=false,revision=0,timer;
    function render(value){
      state=value;button.disabled=busy||!value?.supported;
      if(!value?.supported){button.textContent=value?.state==='unsupported'?'일시정지 준비 필요':'일시정지 연결 확인';status.textContent=value?.state==='unsupported'?'ComfyUI 재시작 후 활성화됩니다.':'영상 서버 연결을 확인하고 있습니다.';return;}
      button.textContent=busy?'처리 중…':value.paused?'작업 재개':'작업 일시정지';
      button.setAttribute('aria-pressed',String(value.paused));
      button.title='현재 작업은 완료하고 다음 작업부터 멈춥니다. 재개하면 기존 순서대로 진행합니다.';
      status.textContent=value.state==='finishing'?'현재 작업 완료 후 일시정지':value.state==='paused'?'일시정지됨 · 다음 작업 시작 보류':'';
      if(value.storage_error)status.textContent+=' · 저장 상태 확인 필요';
    }
    async function poll(){
      win.clearTimeout(timer);if(doc.hidden||loading||busy)return;
      const version=revision;loading=true;
      try{const response=await win.fetch('/api/queue/pause',{cache:'no-store'});if(!response.ok)throw Error('status');const value=await response.json();if(version===revision)render(value);}
      catch{if(version===revision)render({supported:false,state:'unavailable'});}
      finally{loading=false;if(!doc.hidden)timer=win.setTimeout(poll,2000);}
    }
    button.onclick=async()=>{
      if(busy||!state?.supported)return;
      const paused=!state.paused;busy=true;revision++;render(state);
      try{
        const response=await win.fetch('/api/queue/pause',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paused})});
        const value=await response.json();if(!response.ok||!value.supported)throw Error('request');
        state=value;
      }catch{state={supported:false,state:'unavailable'};}
      finally{busy=false;render(state);win.clearTimeout(timer);timer=win.setTimeout(poll,1000);}
    };
    doc.addEventListener('visibilitychange',()=>{if(doc.hidden)win.clearTimeout(timer);else poll();});poll();
    return {poll,button,status};
  }
  return {mount};
});
