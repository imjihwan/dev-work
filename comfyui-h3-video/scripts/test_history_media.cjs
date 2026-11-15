// Synthetic DOM only: no browser, network, history, images or video files.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
class Video{
  constructor(index){this.attrs={};this.dataset={previewSrc:`/synthetic-${index}.mp4`};this.isConnected=true;this.loads=0;this.plays=0;this.paused=true;}
  getAttribute(name){return this.attrs[name]??null;}
  removeAttribute(name){delete this.attrs[name];}
  set src(value){this.attrs.src=value;}
  pause(){this.paused=true;}
  play(){this.paused=false;this.plays++;return Promise.resolve();}
  load(){this.loads++;}
}
const videos=Array.from({length:1001},(_,index)=>new Video(index));
const elements={histList:{querySelectorAll:()=>videos},singleApp:{hidden:false},videoCompare:{hidden:true}};
let observer,finePointer=false,comparisonPauses=0;
const events={},document={hidden:false,addEventListener(name,fn){events[name]=fn;}};
const context=vm.createContext({document,$:id=>elements[id],window:{matchMedia:()=>({matches:finePointer})},
  pauseVideoComparison(){comparisonPauses++;},esc:value=>value,vurl:()=>'/synthetic.mp4',
  IntersectionObserver:class{constructor(callback){this.callback=callback;this.observed=[];this.disconnects=0;observer=this;}observe(video){this.observed.push(video);}disconnect(){this.observed=[];this.disconnects++;}}
});
vm.runInContext(script.slice(script.indexOf('const HISTORY_MEDIA='),script.indexOf('function drawHist(')),context);
const loaded=()=>videos.filter(video=>video.getAttribute('src'));
const visible=(items,on)=>observer.callback(items.map(target=>({target,isIntersecting:on})));
const markup=context.historyThumb({video:{},id:'synthetic'});
assert(markup.includes('preload="none"')&&markup.includes('data-preview-src='));
assert(!/\ssrc=/.test(markup),'History markup must not initiate a video request');
context.watchHistoryPreviews();assert.equal(observer.observed.length,1001);assert.equal(loaded().length,0);
visible(videos.slice(0,20),true);assert.equal(loaded().length,6,'Preview resource use stays bounded even with many intersecting rows');
const first=loaded();visible(first,false);assert(first.every(video=>!video.getAttribute('src')&&video.loads===1));assert.equal(loaded().length,6);
const hover=loaded()[0];hover.onmouseenter();assert.equal(hover.plays,0,'Touch-generated hover must not start hidden preview playback');
finePointer=true;hover.onmouseenter();assert.equal(hover.plays,1);hover.onmouseleave();assert(hover.paused);
elements.singleApp.hidden=true;context.syncHistoryPreviews();assert.equal(loaded().length,0,'Gallery/story tabs must release all main-page video previews');
visible(videos.slice(30,40),true);assert.equal(loaded().length,0,'Late intersection callbacks cannot load a hidden tab');
elements.singleApp.hidden=false;context.syncHistoryPreviews();assert.equal(loaded().length,6);
elements.videoCompare.hidden=false;context.syncHistoryPreviews();assert.equal(loaded().length,0,'Full playback must have no competing thumbnail buffers');
elements.videoCompare.hidden=true;context.syncHistoryPreviews();assert.equal(loaded().length,6);
document.hidden=true;events.visibilitychange();assert.equal(loaded().length,0);assert.equal(comparisonPauses,1);
document.hidden=false;events.visibilitychange();assert.equal(loaded().length,6);
context.resetHistoryPreviews();assert.equal(loaded().length,0);assert.equal(observer.disconnects,1);
videos.forEach(video=>video.isConnected=false);visible(videos.slice(0,6),true);assert.equal(loaded().length,0,'Detached history rows cannot regain resources');
console.log('History media lifecycle: passed (1001 synthetic rows; no private data or live media).');
