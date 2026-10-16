'use client';
import {useEffect,useRef,useState} from 'react';
import {Bluetooth,Play,Square,Send,Unplug,Loader2,Check} from 'lucide-react';
import {WebBrewer,type BrewStatus} from '../lib/web-bluetooth';
type Recipe={id:string;name:string;revision:number;state:string;data:any};
export default function BluetoothBrew({recipes,canEdit,selectedId,onSelect}:{recipes:Recipe[];canEdit:boolean;selectedId:string;onSelect:(id:string)=>void}){
 const [status,setStatus]=useState<BrewStatus>({connected:false,name:'',message:'기기를 연결하세요.',active:false,uncertain:false}),[supported,setSupported]=useState<boolean|null>(null),[busy,setBusy]=useState(''),[error,setError]=useState(''),[ready,setReady]=useState(false);
 const brewer=useRef<WebBrewer|null>(null),operation=useRef(0),canEditRef=useRef(canEdit);canEditRef.current=canEdit;
 useEffect(()=>{setSupported(window.isSecureContext&&typeof (navigator as Navigator&{bluetooth?:{requestDevice?:unknown}}).bluetooth?.requestDevice==='function');brewer.current=new WebBrewer(setStatus);return()=>brewer.current?.disconnect();},[]);
 const selected=recipes.find(r=>r.id===selectedId),key=selected?`${selected.id}:${selected.revision}`:'',armed=!!key&&status.armed===key;
 useEffect(()=>setReady(false),[key,status.armed]);
 async function run(name:string,fn:()=>Promise<unknown>){const op=++operation.current;setError('');setBusy(name);try{await fn();}catch(e){if(op===operation.current)setError((e as Error).name==='NotFoundError'?'기기 선택을 취소했거나 주변에서 기기를 찾지 못했습니다.':(e as Error).message);}finally{if(op===operation.current)setBusy('');}}
 async function load(){if(!selected)return;const selection=key;await run('load',async()=>{const response=await fetch('/api/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'prepareBrew',id:selected.id,revision:selected.revision})}),data:any=await response.json();if(!response.ok||data.error)throw new Error(data.error??'기기용 레시피 준비에 실패했습니다.');if(!canEditRef.current)throw new Error('편집 권한이 변경되었습니다.');if(`${data.plan.recipeId}:${data.plan.revision}`!==selection)throw new Error('레시피가 변경되었습니다. 다시 선택하세요.');await brewer.current!.load(data.plan);});}
 const eligible=!!selected&&selected.data.cupType!==4&&selected.data.adaptedModel===1&&!['uncertain','conflict'].includes(selected.state);
 return <section className="panel bluetooth-panel" aria-label="Bluetooth 직접 추출">
  <div className="section-heading"><div><div className="eyebrow">BREW NEARBY</div><h2><Bluetooth size={23}/> Bluetooth 직접 추출</h2></div><span className={'badge '+(status.connected?'synced':'draft')}>{status.connected?status.name:'연결 전'}</span></div>
  <p className="muted">기기 근처에서 이 브라우저를 Bluetooth로 연결하세요. 레시피를 기기로 보낸 뒤 추출을 시작할 수 있습니다.</p>
  {supported===false&&<div role="alert" className="alert warning">이 브라우저에서는 Bluetooth를 사용할 수 없습니다. PC의 Chrome·Edge 또는 Android Chrome에서 사이트를 직접 여세요. 앱 내 브라우저에서는 연결이 제한될 수 있습니다.</div>}
  <div className="ble-connect"><button className="button secondary" disabled={!canEdit||!supported||!!busy||status.connected} onClick={()=>run('connect',()=>brewer.current!.connect())}><Bluetooth size={17}/>{busy==='connect'?'기기 연결 중…':'Bluetooth 기기 연결'}</button>{status.connected&&<button className="button secondary" disabled={!!busy||status.active} onClick={()=>brewer.current?.disconnect()}><Unplug size={17}/>연결 해제</button>}</div>
  <div className="ble-state" aria-live="polite"><span className={'connection-dot'}><i className={status.connected?'online':''}/>{status.message}</span>{status.connected&&<div className="ble-weights"><span>물 <b>{status.water?.toFixed(1)??'—'} g</b></span><span>추출량 <b>{status.coffee?.toFixed(1)??'—'} g</b></span></div>}</div>
  <label>추출할 레시피<select aria-label="추출할 레시피" value={selectedId} disabled={!canEdit||!!busy||status.active} onChange={e=>onSelect(e.target.value)}><option value="">레시피를 선택하세요</option>{recipes.map(r=><option key={r.id} value={r.id}>{r.name}{r.state==='draft'?' · 웹 초안':''}{r.data.cupType===4?' · 차 추출 미지원':''}</option>)}</select></label>
  {selected&&<div className="ble-recipe"><strong>{selected.name}</strong><span>{selected.data.dose}g · 1:{selected.data.grandWater} · 버전 {selected.revision}</span>{armed&&<span><Check size={14}/> 이 레시피가 기기에 준비되었습니다.</span>}</div>}
  {selected&&!eligible&&<p className="text-warning">Studio 커피 레시피를 선택하세요. 차·다른 모델 또는 동기화 충돌 상태는 직접 추출할 수 없습니다.</p>}
  <div className="ble-actions"><button className="button secondary" disabled={!canEdit||!status.connected||!eligible||!!busy||status.active} onClick={load}><Send size={17}/>{busy==='load'?'레시피 전송 중…':'1. 레시피를 기기로 전송'}</button><button className="button primary" disabled={!canEdit||!status.connected||!armed||!ready||!!busy||status.uncertain||status.state!==31} onClick={()=>run('start',async()=>{if(!canEditRef.current)throw new Error('편집 권한이 필요합니다.');setReady(false);await brewer.current!.start();})}><Play size={17}/>2. 추출 시작</button><button className="button danger" disabled={!canEdit||!status.connected||busy==='connect'||busy==='stop'} onClick={()=>run('stop',()=>brewer.current!.stop())}><Square size={17}/>{busy==='stop'?'중지 확인 중…':'추출 중지'}</button>{busy&&<Loader2 size={18} className="spin"/>}</div>
  <label className="ble-ready"><input type="checkbox" checked={ready} disabled={!armed||!!busy||!canEdit} onChange={e=>setReady(e.target.checked)}/>물·원두와 드리퍼·컵을 준비했고, 지금 이 기기에서 추출합니다.</label>
  {error&&<div role="alert" className="alert error">{error}</div>}
  {!canEdit&&<p className="fine">기기 제어는 관리자와 편집자만 사용할 수 있습니다.</p>}
  <p className="fine">이 연결은 현재 브라우저에서만 유지됩니다. 추출 중에는 탭을 열어 두세요. 연결이 끊겨도 추출이 자동 중지되지는 않습니다. 중지 결과를 확인할 수 없다면 기기에서 직접 중지하세요.</p>
 </section>;
}
