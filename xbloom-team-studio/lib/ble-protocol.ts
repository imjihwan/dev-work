// Frame layout and CRC verified against APK 2.2.3 and captured app packets.
export const SERVICE='0000e0ff-3c17-d293-8e48-14fe2e4da212';
export const COMMAND='0000ffe1-0000-1000-8000-00805f9b34fb';
export const STATUS='0000ffe2-0000-1000-8000-00805f9b34fb';
export const CMD={session:8100,query:8022,bypass:8102,cup:8104,recipe:8001,noGrind:8004,commit:8002,start:40518,cancel:40519,stop:4507};
export function crc16(bytes:Uint8Array){let crc=0;for(const byte of bytes){crc^=byte;for(let bit=0;bit<8;bit++)crc=crc&1?(crc>>>1)^0x8408:crc>>>1;}return crc;}
export function hex(bytes:Uint8Array){return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');}
export function unhex(value:string){if(!/^(?:[a-f\d]{2})+$/i.test(value)||value.length>1024)throw new Error('기기용 레시피 코드 형식이 올바르지 않습니다.');return Uint8Array.from(value.match(/../g)!,b=>parseInt(b,16));}
export function frame(command:number,data=new Uint8Array()):Uint8Array{const bytes=new Uint8Array(12+data.length),view=new DataView(bytes.buffer);bytes.set([0x58,1,1]);view.setUint16(3,command,true);view.setUint32(5,bytes.length,true);bytes[9]=1;bytes.set(data,10);view.setUint16(bytes.length-2,crc16(bytes.slice(0,-2)),true);return bytes;}
export function ints(...values:number[]){const bytes=new Uint8Array(values.length*4),view=new DataView(bytes.buffer);values.forEach((v,i)=>view.setUint32(i*4,v,true));return bytes;}
function floatBits(n:number){const b=new DataView(new ArrayBuffer(4));b.setFloat32(0,n,true);return b.getUint32(0,true);}
export type BrewPlan={recipeId:string;revision:number;name:string;frames:string[]};
export function loadFrames(recipe:any,code:{theCode:string;theMax:number;theMin:number}){
 if(recipe.cupType===4||recipe.adaptedModel!==1)throw new Error('Bluetooth 직접 추출은 xBloom Studio 커피 레시피를 지원합니다.');
 const blob=unhex(code.theCode);
 if(blob.length<3||blob[0]!==blob.length-3)throw new Error('기기용 레시피 코드 길이가 일치하지 않습니다.');
 if(!Number.isFinite(code.theMin)||!Number.isFinite(code.theMax)||code.theMin<0||code.theMax<=code.theMin||code.theMax>2000)throw new Error('드리퍼 설정 응답을 확인할 수 없습니다.');
 const bypass=recipe.isEnableBypassWater===1;
 return [frame(CMD.session,ints(185,1)),frame(CMD.query),frame(CMD.bypass,ints(floatBits(bypass?recipe.bypassVolume:0),floatBits(bypass?recipe.bypassTemp*10:0),recipe.dose)),frame(CMD.cup,ints(floatBits(code.theMax),floatBits(code.theMin))),frame(recipe.isSetGrinderSize===1?CMD.recipe:CMD.noGrind,blob)];
}
export type Packet={command:number;state?:number;water?:number;coffee?:number};
export function packet(bytes:Uint8Array):Packet|null{
 if(bytes.length<12||bytes[0]!==0x58||bytes[1]!==2||bytes[2]!==7||bytes[9]!==0xc1)return null;
 const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
 if(view.getUint32(5,true)!==bytes.length||crc16(bytes.slice(0,-2))!==view.getUint16(bytes.length-2,true))return null;
 const out:Packet={command:view.getUint16(3,true)};
 if(bytes[3]===0x57&&bytes.length>=13)out.state=bytes[10];
 if([0x4b,0x15].includes(bytes[3])&&bytes.length>=16){const grams=view.getFloat32(10,true)*(bytes[3]===0x4b?.001:1);if(Number.isFinite(grams)&&grams>=0&&grams<=2000)out[bytes[3]===0x4b?'water':'coffee']=grams;}
 return out;
}
export const stateNames:Record<number,string>={1:'대기',12:'물 부족',15:'원두 확인 필요',16:'추출 중',29:'레시피 수신 중',30:'시작 확인 대기',31:'레시피 준비됨',34:'분쇄 / 추출 시작 중',35:'추출 중',36:'추출 완료',59:'추출 중',65:'완료 / Auto Mode'};
