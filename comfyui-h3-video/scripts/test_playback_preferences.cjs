// Browser preference checks only; no app requests, user storage or real media.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=process.argv[2]||path.join(__dirname,'../simple_ui');
const snippets=['index.html','gallery.html','story.html'].map(file=>{
  const html=fs.readFileSync(path.join(root,file),'utf8');
  assert(html.includes('id="defaultMuteToggle"'));
  return html.slice(html.indexOf('// Browser playback mute.'),html.indexOf('// End browser playback mute.'));
});
assert(snippets.every(source=>source===snippets[0]),'All screens use the same browser-only storage contract');
function browser(){return {data:new Map(),tabs:[]};}
function tab(storage,source=snippets[0],deny=false){
  const input={checked:false},events=[],changes=[];
  const context=vm.createContext({$:()=>input,window:{addEventListener:(type,fn)=>{if(type==='storage')events.push(fn);}},
    localStorage:{getItem:key=>{if(deny)throw Error('disabled');return storage.data.get(key)??null;},setItem:(key,value)=>{if(deny)throw Error('disabled');storage.data.set(key,value);for(const other of storage.tabs)if(other.events!==events)for(const listener of other.events)listener({key,newValue:value});}},
    fetch:()=>assert.fail('Playback preference must never contact the shared server')});
  vm.runInContext(source,context);context.initDefaultPlaybackMute(value=>changes.push(value));
  const result={context,input,events,changes};storage.tabs.push(result);return result;
}
const firstBrowser=browser(),otherBrowser=browser();
const main=tab(firstBrowser),gallery=tab(firstBrowser,snippets[1]),independent=tab(otherBrowser);
assert.equal(main.context.isDefaultPlaybackMuted(),false);
main.input.checked=true;main.input.onchange();
assert.equal(main.context.isDefaultPlaybackMuted(),true);assert.equal(gallery.input.checked,true);assert.equal(gallery.changes.at(-1),true);
assert.equal(independent.input.checked,false,'Different browsers keep independent settings');
const refreshed=tab(firstBrowser,snippets[2]);assert.equal(refreshed.input.checked,true,'Refresh and other screens retain the preference');
gallery.input.checked=false;gallery.input.onchange();assert.equal(main.input.checked,false);assert.equal(refreshed.input.checked,false);
for(const listener of main.events)listener({key:'unrelated-key',newValue:'1'});
assert.equal(main.input.checked,false);
const unavailable=tab(browser(),snippets[0],true);unavailable.input.checked=true;unavailable.input.onchange();assert.equal(unavailable.context.isDefaultPlaybackMuted(),true);
const malformed=browser();malformed.data.set('h3simple.defaultPlaybackMuted.v1','unexpected');assert.equal(tab(malformed).input.checked,false);
for(const listener of main.events)listener({key:'h3simple.defaultPlaybackMuted.v1',newValue:null});assert.equal(main.input.checked,false);
console.log('Playback preference passed: per-browser persistence, screen/tab synchronization, refresh, unrelated events and disabled storage; no server requests.');
