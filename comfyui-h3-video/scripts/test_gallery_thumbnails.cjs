// Synthetic image nodes and a fake clock only; never loads a photo, video or network URL.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/gallery.html'),'utf8');
const start=html.indexOf('// Recover transient image failures'),end=html.indexOf('function drawGallery()',start);assert(start>0&&end>start);
let clock=1000;const timers=[],grid={children:[]},document={hidden:false};
const context=vm.createContext({document,G:{active:true},window:{innerHeight:700},$:()=>grid,Date:{now:()=>clock},setTimeout:(fn,delay)=>timers.push({fn,delay})});
vm.runInContext(html.slice(start,end),context);
function fixture(complete=false,naturalWidth=undefined){
  const placeholder={hidden:false,textContent:''},image={style:{},hidden:false,isConnected:true,complete,naturalWidth,top:0,getBoundingClientRect(){return{top:this.top,bottom:this.top+180};}},
    node={querySelector:selector=>selector==='img'?image:placeholder};grid.children.push(node);
  context.bindGalleryThumbnail(node,'/api/gallery/thumbnail?id=synthetic&v=synthetic');return{image,placeholder,node};
}
const fire=()=>{const timer=timers.shift();assert(timer);clock+=timer.delay;timer.fn();};
let {image,placeholder}=fixture();image.onload();assert(placeholder.hidden,'Successful loading removes the loading text');
image.onerror();assert.equal(image.style.visibility,'hidden');assert(!image.hidden,'A failed lazy image keeps its layout for retry visibility checks');
fire();assert(image.src.includes('retry='));assert.equal(image.style.visibility,'');assert(!placeholder.hidden);
image.onerror();fire();image.onerror();fire();const last=image.src;
image.onerror();assert.equal(timers.length,0,'Three retries is a hard bound');context.retryGalleryThumbnails();assert.equal(image.src,last);
context.retryGalleryThumbnails(true);assert.notEqual(image.src,last,'Manual refresh explicitly retries with a fresh URL');image.onload();assert(placeholder.hidden);
({image,placeholder}=fixture());image.top=2000;image.onerror();fire();assert.equal(image.src,undefined,'Offscreen failures do not flood the server');
image.top=0;context.retryGalleryThumbnails();assert(image.src);image.onload();
({image}=fixture());document.hidden=true;image.onerror();fire();assert.equal(image.src,undefined);document.hidden=false;context.retryGalleryThumbnails();assert(image.src);image.onload();
({image}=fixture());context.G.active=false;image.onerror();fire();assert.equal(image.src,undefined);context.G.active=true;context.retryGalleryThumbnails();assert(image.src);image.onload();
({image}=fixture());image.onerror();image.isConnected=false;fire();assert.equal(image.src,undefined,'Detached cards cannot restart requests');
({image,placeholder}=fixture(true,480));assert(placeholder.hidden,'An already-cached image is handled even if load fired before binding');
console.log('Gallery thumbnail checks passed: loading state, bounded retries, manual refresh, viewport/visibility guards, disconnected nodes and cached-image races.');
