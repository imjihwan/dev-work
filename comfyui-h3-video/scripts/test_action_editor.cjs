// In-memory editor and prompt tests. No browser, server, image or video access.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(process.argv[2]||path.join(__dirname,'../simple_ui/index.html'),'utf8');
const source=html.match(/<script>([\s\S]*)<\/script>/)[1];
const section=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
class Element{
 constructor(){this.children=[];this.parts={};this.value='';this.hidden=false;this.style={};this._html='';}
 set innerHTML(value){this._html=value;if(!value)this.children=[];}
 get innerHTML(){return this._html;}
 querySelector(key){return this.parts[key]??=(new Element());}
 appendChild(item){this.children.push(item);item.parent=this;}
 remove(){this.parent.children=this.parent.children.filter(x=>x!==this);}
}
const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
let updates=0;
const ctx=vm.createContext({$,document:{createElement:()=>new Element()},Number,Math,Array,Object,JSON,String,Set,Map,
 FIELDS:['subject','summary','style','keep','sound','music','duration'],S:{},images:[],manualFinal:false,
 updatePromptFromFields:()=>updates++,sendMode:()=> 'REF2VA',isRef:()=>true});
vm.runInContext(section('// Canonical rows remain','const ts ='),ctx);
vm.runInContext(section('function captureSettings()','function rememberManualPromptInputs()'),ctx);
vm.runInContext(section('function apply(s){','let lastDur ='),ctx);
const run=code=>vm.runInContext(code,ctx),plain=value=>JSON.parse(JSON.stringify(value));
run("addShot(0,'First natural action.');addShot(3.5,'Second natural action.');");
const original=plain(ctx.actionRows());
ctx.setActionMode('single');assert.equal($('shots').children.length,1);assert($('shots').hidden);assert(!$('actionText').hidden);
assert.equal($('actionText').value,'First natural action.\n\nSecond natural action.');
assert.equal(plain(ctx.captureSettings()).actionMode,'single');
ctx.setActionMode('timeline');assert.deepEqual(plain(ctx.actionRows()),original,'Unedited mode switch retains timing exactly');
ctx.setActionMode('single');$('actionText').value='Move naturally, pause, then settle.';$('actionText').oninput();
assert.deepEqual(plain(ctx.captureSettings()).shots,[[0,'Move naturally, pause, then settle.']]);
ctx.setActionMode('timeline');assert.equal($('shots').children.length,1,'Edited prose must not restore obsolete timed actions');
ctx.apply({f:{summary:'Synthetic'},actionMode:'single',shots:[[0,'Loaded prose.']]});assert.equal($('actionText').value,'Loaded prose.');
// Explicit synchronization also covers programmatic edits that emit no input event.
$('actionText').value='Programmatic latest prose.';assert.equal(plain(ctx.captureSettings()).shots[0][1],'Programmatic latest prose.');
ctx.apply({f:{},shots:[[0,'Old first.'],[2,'Old second.']]});assert.equal($('actionMode').value,'timeline');assert(!$('shots').hidden);
assert(updates>=4);
console.log('Action editor checks passed: natural prose, reversible toggle, save/load, latest text, timed compatibility.');
