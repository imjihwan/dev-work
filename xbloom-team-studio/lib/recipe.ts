// Values traced from APK 2.2.3 CupType, PatternType, CoffeeConstantUtil,
// RecipeEditActivity, RecipePourViewHolder and TeaRecipeEditFragment.
export const PATTERNS=[{value:1,label:'중앙 · Center'},{value:2,label:'나선형 · Spiral'},{value:3,label:'원형 · Circular'}];
export const CUPS=[{value:1,label:'xPod'},{value:2,label:'xDripper / Omni Dripper'},{value:3,label:'다른 드리퍼'},{value:4,label:'Omni Tea Brewer · 차'}];
export function getPours(raw:any){if(Array.isArray(raw.pourList))return raw.pourList;const result=JSON.parse(raw.pourDataJSONStr??'[]');if(!Array.isArray(result))throw new Error('푸어 목록 형식이 잘못되었습니다.');return result;}
export function editableRecipe(raw:any){if(!raw||typeof raw!=='object')throw new Error('레시피 데이터가 필요합니다.');const d=structuredClone(raw);d.isSetGrinderSize??=2;d.isEnableBypassWater??=2;d.pourList=getPours(d).map((p:any)=>({...p,isEnableVibrationBefore:p.isEnableVibrationBefore??2,isEnableVibrationAfter:p.isEnableVibrationAfter??2}));delete d.pourDataJSONStr;return d;}
export function copyRecipe(raw:any){const d=editableRecipe(raw);for(const k of ['tableId','localId','creatorId','theMemberId','theVersion','createTimeStamp','lastUsedTimeStamp','memberShortcutsRecipeId','memberShortcutsRecipeTime'])delete d[k];d.pourList=d.pourList.map((p:any)=>{const copy={...p};delete copy.tableId;delete copy.recipeId;return copy;});return d;}
export function newPour(tea=false){return {theName:tea?'Steep':'Pour',volume:tea?80:40,temperature:tea?85:93,flowRate:3,pattern:1,pausing:tea?120:5,isEnableVibrationBefore:2,isEnableVibrationAfter:2};}
export function newRecipe(tea=false){return {theName:tea?'새 차 레시피':'새 레시피',dose:tea?3:15,grandWater:tea?15:16,grinderSize:tea?50:60,rpm:tea?120:60,cupType:tea?4:2,adaptedModel:1,isEnableBypassWater:2,isSetGrinderSize:tea?2:1,theColor:'#C9D5B8',bypassTemp:85,bypassVolume:5,pourList:tea?[newPour(true),newPour(true)]:[{...newPour(),theName:'Bloom',volume:40,pausing:30},{...newPour(),volume:100,pattern:2,pausing:15},{...newPour(),volume:100,pattern:2,pausing:0}]};}
export function temperatureMode(value:number,kind:'coffee'|'tea'|'bypass'){const rt=kind==='tea'?39:20,bp=kind==='coffee'?98:96;return value===rt?'rt':value===bp?'bp':'custom';}
export function temperatureValue(mode:string,kind:'coffee'|'tea'|'bypass'){return mode==='rt'?(kind==='tea'?39:20):mode==='bp'?(kind==='coffee'?98:96):85;}
export function settingsDifferences(requested:any,observed:any){const differences:string[]=[],tea=requested.cupType===4;const numeric=(v:any)=>v==null?v:Number(v);const check=(name:string,a:any,b:any)=>{if(a!==undefined&&a!==null&&a!==b)differences.push(name);};check('레시피 이름',requested.theName,observed.theName);for(const k of ['dose','cupType','adaptedModel'])check(k,numeric(requested[k]),numeric(observed[k]));if(!tea){check('grandWater',numeric(requested.grandWater),numeric(observed.grandWater));for(const k of ['isSetGrinderSize','isEnableBypassWater'])check(k,numeric(requested[k]),numeric(observed[k]));if(requested.isSetGrinderSize===1)for(const k of ['grinderSize','rpm'])check(k,numeric(requested[k]),numeric(observed[k]));if(requested.isEnableBypassWater===1)for(const k of ['bypassTemp','bypassVolume'])check(k,numeric(requested[k]),numeric(observed[k]));}const a=getPours(requested),b=getPours(observed);if(a.length!==b.length)differences.push('푸어 단계 수');a.forEach((p:any,i:number)=>{for(const k of tea?['volume','temperature','pausing','pattern']:['volume','temperature','pausing','pattern','flowRate','isEnableVibrationBefore','isEnableVibrationAfter'])check(`${i+1}단계 ${k}`,numeric(p[k]),numeric(b[i]?.[k]));});if(requested.theColor)check('레시피 색상',requested.theColor.toLowerCase(),observed.theColor?.toLowerCase());if(requested.theSubsetId!=null)check('보관 폴더',String(requested.theSubsetId),String(observed.theSubsetId));return differences;}
export function validateRecipeSettings(raw:any,previous?:any){
 if(!raw||typeof raw!=='object')throw new Error('레시피 데이터가 필요합니다.');
 const tea=raw.cupType===4,ps=getPours(raw),old=previous?getPours(previous):[];
 if(typeof raw.theName!=='string'||!raw.theName.trim()||raw.theName.length>120)throw new Error('레시피 이름은 1~120자로 입력하세요.');
 const unchanged=(value:any,before:any)=>previous!==undefined&&value===before;
 function range(value:any,min:number,max:number,label:string,before?:any,step?:number){if(typeof value!=='number'||!Number.isFinite(value))throw new Error(`${label} 값을 입력하세요.`);if(unchanged(value,before))return;if(value<min||value>max||step&&Math.abs((value-min)/step-Math.round((value-min)/step))>0.00001)throw new Error(`${label}: ${min}~${max}${step?`, 간격 ${step}`:''} 범위로 입력하세요.`);}
 if(![1,2,3,4].includes(raw.cupType)&&!unchanged(raw.cupType,previous?.cupType))throw new Error('드리퍼 종류를 선택하세요.');
 range(raw.dose,tea?1:raw.cupType===1?0:5,tea?5:raw.cupType===2?18:raw.cupType===1?15:25,tea?'찻잎량':'원두량',previous?.dose,1);
 if(!ps.length||ps.length>(tea?3:9))throw new Error(tea?'차는 1~3회 우림으로 구성하세요.':'커피는 1~9개 푸어로 구성하세요.');
 if(!tea){
  range(raw.grandWater,5,25,'추출 비율',previous?.grandWater,.5);
  if(![1,2].includes(raw.isSetGrinderSize))throw new Error('그라인더 ON/OFF를 선택하세요.');
  if(raw.isSetGrinderSize===1){range(raw.grinderSize,1,raw.adaptedModel===2?30:80,'분쇄도',previous?.grinderSize,1);range(raw.rpm,60,120,'RPM',previous?.rpm,10);}
  const total=ps.reduce((s:number,p:any)=>s+Math.trunc(p.volume),0),target=Math.trunc(raw.dose*raw.grandWater);
  if(total!==target)throw new Error(`푸어 물량 합계 ${total}mL를 추출 목표 ${target}mL에 맞추세요. 바이패스는 별도입니다.`);
  if(![1,2].includes(raw.isEnableBypassWater))throw new Error('바이패스 ON/OFF를 선택하세요.');
  if(raw.isEnableBypassWater===1){range(raw.bypassVolume,5,100,'바이패스 물량',previous?.bypassVolume,1);if(raw.bypassTemp!==20)range(raw.bypassTemp,40,96,'바이패스 온도',previous?.bypassTemp,1);}
 }
 ps.forEach((p:any,i:number)=>{const prior=old.find((o:any)=>p.tableId!=null&&o.tableId===p.tableId)??old[i];const prefix=`${i+1}${tea?'회 우림':'단계 푸어'}`;range(p.volume,1,tea?90:240,`${prefix} 물량`,prior?.volume,1);range(p.pausing,tea?5:0,tea?360:59,`${prefix} ${tea?'우림 시간':'대기 시간'}`,prior?.pausing,1);
 const sentinels=tea?[39,96]:[20,98];if(!sentinels.includes(p.temperature))range(p.temperature,40,95,`${prefix} 온도`,prior?.temperature,1);
 if(!tea&&raw.adaptedModel!==2)range(p.flowRate,3,3.5,`${prefix} 유량`,prior?.flowRate,.1);
 if(![1,2,3].includes(p.pattern)&&!unchanged(p.pattern,prior?.pattern))throw new Error(`${prefix} 물줄기를 선택하세요.`);
 if(!tea)for(const k of ['isEnableVibrationBefore','isEnableVibrationAfter'])if(![1,2].includes(p[k]))throw new Error(`${prefix} 진동 ON/OFF를 선택하세요.`);
 });
 return raw;
}
