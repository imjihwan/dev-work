import {SERVICE,COMMAND,STATUS,CMD,frame,unhex,packet,stateNames,type BrewPlan,type Packet} from './ble-protocol.ts';
// Structural interfaces keep the unsupported-browser path usable without a polyfill.
type Characteristic=EventTarget&{value?:DataView;properties:{writeWithoutResponse:boolean};startNotifications():Promise<unknown>;writeValueWithoutResponse(v:Uint8Array):Promise<void>};
type Device=EventTarget&{name?:string;gatt:{connected:boolean;connect():Promise<{getPrimaryService(uuid:string):Promise<{getCharacteristic(uuid:string):Promise<Characteristic>}>}>;disconnect():void}};
export type BluetoothApi={requestDevice(options:unknown):Promise<Device>};
export type BrewStatus={connected:boolean;name:string;message:string;state?:number;water?:number;coffee?:number;armed?:string;active:boolean;uncertain:boolean};
export class WebBrewer {
 private device?:Device;private command?:Characteristic;private notify?:Characteristic;
 private pending=new Set<{accept:(p:Packet)=>boolean;resolve:(p:Packet)=>void;reject:(e:Error)=>void}>();
 private busy=false;private generation=0;private plan?:BrewPlan;private buffer=new Uint8Array();private writeTail:Promise<void>=Promise.resolve();
 status:BrewStatus={connected:false,name:'',message:'기기를 연결하세요.',active:false,uncertain:false};
 constructor(private update:(s:BrewStatus)=>void,private api?:BluetoothApi,private wait=(ms:number)=>new Promise<void>(r=>setTimeout(r,ms))){}
 private emit(patch:Partial<BrewStatus>){this.status={...this.status,...patch};this.update({...this.status});}
 private reset=()=>{this.generation++;this.busy=false;this.command=undefined;this.plan=undefined;this.buffer=new Uint8Array();for(const p of this.pending)p.reject(new Error('Bluetooth 연결이 끊겼습니다.'));this.pending.clear();this.emit({connected:false,armed:undefined,active:false,uncertain:true,message:'연결 끊김 · 기기 상태를 직접 확인하세요. 연결 해제는 추출 중지가 아닙니다.'});};
 private onValue=(event:Event)=>{const v=(event.target as Characteristic).value;if(v)this.receive(new Uint8Array(v.buffer,v.byteOffset,v.byteLength));};
 // Notifications may be split at the ATT MTU; reassemble by declared frame length.
 receive(chunk:Uint8Array){const joined=new Uint8Array(this.buffer.length+chunk.length);joined.set(this.buffer);joined.set(chunk,this.buffer.length);this.buffer=joined;
  while(this.buffer.length>=9){if(this.buffer[0]!==0x58||this.buffer[1]!==2||this.buffer[2]!==7){this.buffer=this.buffer.slice(1);continue;}const n=new DataView(this.buffer.buffer,this.buffer.byteOffset).getUint32(5,true);if(n<12||n>2048){this.buffer=this.buffer.slice(1);continue;}if(this.buffer.length<n)return;const p=packet(this.buffer.slice(0,n));this.buffer=this.buffer.slice(n);if(!p)continue;
   if(p.state!==undefined){const active=[16,30,34,35,59].includes(p.state);const terminal=[1,36].includes(p.state);if(terminal||[12,15].includes(p.state)){this.plan=undefined;}this.emit({state:p.state,message:stateNames[p.state]??`기기 상태 0x${p.state.toString(16)}`,active,uncertain:false,...(terminal||[12,15].includes(p.state)?{armed:undefined}: {})});}
   if(p.water!==undefined)this.emit({water:p.water});if(p.coffee!==undefined)this.emit({coffee:p.coffee});
   for(const q of [...this.pending])if(q.accept(p)){this.pending.delete(q);q.resolve(p);}
  }
 }
 private expect(accept:(p:Packet)=>boolean,ms=10000){let entry:any,timer:ReturnType<typeof setTimeout>;const promise=new Promise<Packet>((resolve,reject)=>{entry={accept,resolve:(v:Packet)=>{clearTimeout(timer);resolve(v);},reject:(e:Error)=>{clearTimeout(timer);reject(e);}};timer=setTimeout(()=>{this.pending.delete(entry);reject(new Error('기기 응답 시간 초과 · 상태를 확인한 뒤 다시 전송하세요.'));},ms);this.pending.add(entry);});promise.catch(()=>{});return {promise,cancel:()=>{this.pending.delete(entry);clearTimeout(timer);}};}
 private send(bytes:Uint8Array){const generation=this.generation;const work=this.writeTail.then(async()=>{if(generation!==this.generation)throw new Error('전송이 취소되었습니다.');if(!this.device?.gatt.connected||!this.command)throw new Error('기기를 먼저 연결하세요.');await this.command.writeValueWithoutResponse(bytes);});this.writeTail=work.catch(()=>{});return work;}
 private async ack(bytes:Uint8Array){const cmd=new DataView(bytes.buffer,bytes.byteOffset).getUint16(3,true),reply=this.expect(p=>p.command===cmd);try{await this.send(bytes);await reply.promise;}finally{reply.cancel();}}
 async connect(){if(this.busy||this.status.connected)return;this.busy=true;try{
  const api=this.api??(navigator as Navigator&{bluetooth?:BluetoothApi}).bluetooth;if(!api)throw new Error('이 브라우저는 Bluetooth를 지원하지 않습니다. Chrome 또는 Edge에서 사이트를 직접 여세요.');
  // Must stay before any await to preserve the click's transient user activation.
  const device=await api.requestDevice({filters:[{services:[SERVICE]},{namePrefix:'XBLOOM'},{namePrefix:'xBloom'}],optionalServices:[SERVICE]});this.device=device;device.addEventListener('gattserverdisconnected',this.reset);
  const server=await device.gatt.connect(),service=await server.getPrimaryService(SERVICE);this.command=await service.getCharacteristic(COMMAND);this.notify=await service.getCharacteristic(STATUS);
  if(!this.command.properties.writeWithoutResponse)throw new Error('이 기기는 필요한 Bluetooth 쓰기 방식을 지원하지 않습니다.');
  this.notify.addEventListener('characteristicvaluechanged',this.onValue);await this.notify.startNotifications();
  if(!device.gatt.connected)throw new Error('Bluetooth 연결이 끊겼습니다. 다시 연결하세요.');
  this.emit({connected:true,name:device.name??'xBloom Studio',message:'연결됨 · 레시피를 선택해 전송하세요.',uncertain:false,active:false,armed:undefined});
 }catch(e){this.disconnect();throw e;}finally{this.busy=false;}}
 disconnect(){this.notify?.removeEventListener('characteristicvaluechanged',this.onValue);this.device?.removeEventListener('gattserverdisconnected',this.reset);this.device?.gatt.disconnect();this.reset();this.device=undefined;this.notify=undefined;}
 async load(plan:BrewPlan){if(this.busy||this.status.active)throw new Error('기기 동작이 끝난 뒤 전송하세요.');this.busy=true;this.plan=undefined;const generation=this.generation;this.emit({armed:undefined,message:'레시피 전송 중…',uncertain:false});
  let armed:ReturnType<WebBrewer['expect']>|undefined;
  try{const frames=plan.frames.map(unhex);if(frames.length!==5||frames.some((f,i)=>new DataView(f.buffer).getUint16(3,true)!==[CMD.session,CMD.query,CMD.bypass,CMD.cup,new DataView(frames[4].buffer).getUint16(3,true)][i])||![CMD.recipe,CMD.noGrind].includes(new DataView(frames[4].buffer).getUint16(3,true)))throw new Error('레시피 전송 계획이 올바르지 않습니다.');
   await this.ack(frames[0]);await this.wait(500);await this.send(frames[1]);await this.wait(2000);
   for(let i=2;i<frames.length;i++){if(generation!==this.generation)throw new Error('전송이 취소되었습니다.');if(i===4)armed=this.expect(p=>p.state===31);await this.ack(frames[i]);await this.wait(400);}
   await armed!.promise;if(generation!==this.generation)throw new Error('전송이 취소되었습니다.');this.plan=plan;this.emit({armed:`${plan.recipeId}:${plan.revision}`,message:'레시피 준비 완료 · 추출 시작을 누르세요.',uncertain:false});
  }catch(e){if(generation===this.generation){this.plan=undefined;this.emit({armed:undefined,uncertain:true,message:'전송 결과 미확인 · 기기 상태를 확인하세요.'});}throw e;}finally{armed?.cancel();if(generation===this.generation)this.busy=false;}}
 async start(){if(this.busy||!this.plan||this.status.state!==31||this.status.uncertain)throw new Error('선택한 레시피를 기기에 다시 전송하세요.');this.busy=true;const generation=this.generation;this.plan=undefined;this.emit({armed:undefined,active:true,message:'추출 시작 요청 중…'});
  const acted=(p:Packet)=>p.state!==undefined&&[12,15,16,34,35,36,59].includes(p.state);let response=this.expect(acted,8000);
  try{await this.send(frame(CMD.commit));let event:Packet|undefined;try{event=await response.promise;}catch{}
   if(generation!==this.generation)return;
   if(!event){if(Number(this.status.state)!==30)throw new Error('시작 응답을 확인하지 못했습니다. 기기를 직접 확인하세요. 자동 재시작하지 않습니다.');response=this.expect(acted,5000);await this.send(frame(CMD.start));event=await response.promise;}
   if(event.state===12||event.state===15)throw new Error(stateNames[event.state]);
  }catch(e){if(generation===this.generation)this.emit({uncertain:true,message:(e as Error).message});throw e;}finally{response.cancel();if(generation===this.generation)this.busy=false;}}
 async stop(){if(!this.status.connected)throw new Error('연결이 끊겨 웹에서 중지할 수 없습니다. 기기에서 직접 중지하세요.');this.generation++;this.plan=undefined;for(const p of this.pending)p.reject(new Error('중지 요청으로 작업을 취소했습니다.'));this.pending.clear();this.busy=true;this.emit({armed:undefined,uncertain:true,message:'중지 요청 중…'});const reply=this.expect(p=>p.state!==undefined&&[1,36,65].includes(p.state),10000);
  try{await this.send(frame([16,34,35,59].includes(this.status.state??-1)?CMD.stop:CMD.cancel));await reply.promise;this.emit({active:false,uncertain:false,message:'기기에서 중지 상태를 확인했습니다.'});}catch(e){this.emit({uncertain:true,message:'중지 결과 미확인 · 기기에서 직접 상태를 확인하세요.'});throw e;}finally{reply.cancel();this.busy=false;}}
}
