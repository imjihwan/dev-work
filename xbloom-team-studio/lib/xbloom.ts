import {validateRecipeSettings} from './recipe.ts';
// Derived from the APK 2.2.3 request path. Credentials never reach client bundles.
const PUBLIC_DER = 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC4LF40GZ72SdhMyl765K/i4nY5CPcHz2Q1IKWKZ9S79xmK7G8pUhbVf4EZLvnNF1+9IvOFQUKV5Z7ZNNviqSpnql9tAT+8+J/He0R7pcirvVSxgdr2i9V/C/gmqAEZ5qVTzRnd3uWdFoKzPdEBxP0IporJ1VBbCv90yBSOhVxO+QIDAQAB';
// Extract the modulus from the public DER's fixed RSA-1024 structure rather than
// maintaining a second, potentially mistyped copy of the public key.
const der = Uint8Array.from(atob(PUBLIC_DER), c => c.charCodeAt(0));
const n = BigInt('0x' + Array.from(der.slice(29,157), x=>x.toString(16).padStart(2,'0')).join(''));
export function rsaBody(value: unknown) {
  const input = new TextEncoder().encode(JSON.stringify(value)); const output: number[]=[];
  for(let i=0;i<input.length;i+=117){
    const block=input.slice(i,i+117), padded=new Uint8Array(128); padded[1]=2;
    for(let j=2;j<127-block.length;j++){let v=0; while(!v)v=crypto.getRandomValues(new Uint8Array(1))[0];padded[j]=v;}
    padded.set(block,128-block.length);
    let base=BigInt('0x'+Array.from(padded,x=>x.toString(16).padStart(2,'0')).join('')), exp=BigInt(65537), result=BigInt(1);
    while(exp){if(exp&BigInt(1))result=result*base%n;base=base*base%n;exp>>=BigInt(1);}
    const hex=result.toString(16).padStart(256,'0');for(let j=0;j<256;j+=2)output.push(parseInt(hex.slice(j,j+2),16));
  }
  return JSON.stringify(btoa(String.fromCharCode(...output)));
}
export type Account={email:string;password:string;memberId?:number|string;token?:string;countryId?:number;accessToken?:string};
export class VendorError extends Error {constructor(public kind:'auth'|'rejected'|'network',message:string){super(message);}}
export class XBloom {
 constructor(public account:Account,private transport:typeof fetch=fetch){}
 async call(endpoint:string,form:Record<string,unknown>,authenticated=true){
  const body={interfaceVersion:19700101,skey:'testskey',phoneType:'Android',appVersion:'2.2.3',clientType:2,languageType:1,...(authenticated?{memberId:this.account.memberId,token:this.account.token}:{}),...form};
  // Workers supports manual/follow redirects. Reject 3xx below without forwarding credentials.
  let response:Response;try{response=await this.transport('https://client-api.xbloom.com/'+endpoint,{method:'POST',headers:{'Content-Type':'application/json;charset=utf-8'},body:rsaBody(body),signal:AbortSignal.timeout(20000),redirect:'manual'});}catch(e){
   const name=e instanceof Error?e.name:'Error';
   console.error('xBloom transport failure',{endpoint,name});
   throw new VendorError('network',endpoint==='tMemberLogin.thtml'?'xBloom 로그인 서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.':'xBloom 응답을 확인하지 못했습니다. 변경 요청은 자동 재시도하지 않습니다.');
  }
  if(!response.ok)throw new VendorError(response.status===401?'auth':'network',`xBloom HTTP ${response.status}`);
  let data:any;try{data=await response.json();}catch{throw new VendorError('network','xBloom 응답 형식이 예상과 다릅니다.');}
  if(data?.result!=='success'){
   const detail=String(data?.info??''); const auth=/token|expired|unauthor|未登录|登录失效|会话|重新登录/i.test(detail);
   if(endpoint==='tMemberLogin.thtml'&&/password|mot de passe|courriel|not.*register|email|密码|邮箱|账号/i.test(detail))throw new VendorError('rejected','xBloom 이메일 또는 비밀번호를 확인하세요. 앱에서 소셜 로그인으로 가입했다면 이메일 비밀번호 로그인 가능 여부도 확인하세요.');
   throw new VendorError(auth?'auth':'rejected',auth?'xBloom 연결이 만료되었습니다.':'xBloom이 요청을 거절했습니다. 계정·레시피 값과 앱 버전 호환성을 확인하세요.');
  }return data;
 }
 async login(){const d=await this.call('tMemberLogin.thtml',{email:this.account.email,password:this.account.password,jpushId:'',interfaceVersion:20240918},false);if(!d.token||!d.member?.tableId)throw new VendorError('auth','로그인 응답에 계정 정보가 없습니다.');this.account={...this.account,memberId:d.member.tableId,token:d.token,countryId:d.member.country?.tableId??this.account.countryId,accessToken:d.projectToken??this.account.accessToken};return this.account;}
 async page(scope:string,pageNumber:number){const paths:Record<string,string>={created:'tuMyTeaRecipeCreated.tuhtml',shared:'tuMyRecipeShared.tuhtml',product:'tuMyRecipeProduct.tuhtml'};if(!paths[scope])throw new Error('목록 범위 오류');const d=await this.call(paths[scope],{pageNumber,countPerPage:100,adaptedModel:1});if(!Array.isArray(d.list))throw new Error('레시피 목록 형식 오류');return d;}
 async all(scope:string){const list:any[]=[];let pages=1;for(let p=1;p<=pages;p++){const d=await this.page(scope,p);list.push(...d.list);if(Number.isInteger(d.totalPage)&&d.totalPage>=0){pages=Math.max(1,d.totalPage);}else if(d.list.length===100){pages=p+1;}if(pages>100)throw new Error('목록이 10,000개를 초과해 중단했습니다. 부분 목록을 저장하지 않았습니다.');}return list;}
 async groups(){const d=await this.call('tuSubsetListForSelect.tuhtml',{creatorId:this.account.memberId});if(!Array.isArray(d.list))throw new Error('레시피 폴더 목록 형식 오류');return d.list;}
 async machines(){const d=await this.call('tuMachineList.tuhtml',{accessToken:this.account.accessToken??''});if(!Array.isArray(d.machineList))throw new Error('기기 목록 형식 오류');return d.machineList;}
 async slots(device:any){const d=await this.call('tuEasyModeList.tuhtml',{tableId:device.tableId,sn:device.serialNumber,countryId:this.account.countryId??0});if(!Array.isArray(d.easyModeDetailVoList))throw new Error('프리셋 목록 형식 오류');return d.easyModeDetailVoList;}
 async write(data:any,id?:string){return this.call(id?'tuRecipeUpdate.tuhtml':'tuRecipeAdd.tuhtml',{...recipePayload(data),...(id?{tableId:id}:{}),interfaceVersion:20240918});}
}
const keys=['theName','dose','grandWater','grinderSize','rpm','cupType','adaptedModel','isEnableBypassWater','isSetGrinderSize','theColor','theSubsetId','bypassTemp','bypassVolume','podsId','podsImagePath','podsName','podsXid','creatorId','theMemberId'];
export function recipePayload(raw:any){const data:Record<string,any>={};for(const k of keys)if(raw[k]!==undefined&&raw[k]!==null)data[k]=raw[k];const pours=Array.isArray(raw.pourList)?raw.pourList:JSON.parse(raw.pourDataJSONStr??'[]');data.pourDataJSONStr=JSON.stringify(pours);if(raw.isSetGrinderSize===2&&raw.cupType!==4&&raw.adaptedModel!==2)delete data.grinderSize;return data;}
export const validateRecipe=validateRecipeSettings;
export function canonical(raw:any){const d=recipePayload(raw); const ordered=(v:any):any=>Array.isArray(v)?v.map(ordered):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,ordered(v[k])])):v;d.pourDataJSONStr=JSON.parse(d.pourDataJSONStr);return JSON.stringify(ordered(d));}
