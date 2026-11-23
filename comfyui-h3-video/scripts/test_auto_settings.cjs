// Advanced settings follow the chosen model unless edited directly; fake state only, never connects to the app.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const html = fs.readFileSync(process.argv[2] || path.join(__dirname, '../simple_ui/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const section = (start, end) => script.slice(script.indexOf(start), script.indexOf(end, script.indexOf(start)));

const turbo = {name:'turbo', auto:{turbo:true}, effective:{steps:8, sampler:'euler', scheduler:'simple', shift_video:7, shift_audio:4}};
const regular = {name:'regular', auto:{turbo:false}, effective:{steps:25, sampler:'res_multistep', scheduler:'simple', shift_video:11, shift_audio:4}};
const notes = [];
const S = {model:'turbo', steps:8, sampler:'euler', scheduler:'simple', shift_video:7, shift_audio:4, manual:{}, level:null, loras:{}};
const context = vm.createContext({S, CAT:{models:[turbo, regular], loras:[]}, note:t => notes.push(t), Object, JSON});
context.curModel = () => context.CAT.models.find(m => m.name === S.model);
context.turboLora = () => null;
vm.runInContext('const PARAMS = ["steps","sampler","scheduler","shift_video","shift_audio"];', context);
vm.runInContext(section('const PARAM_NAME =', '\n'), context);
vm.runInContext(section('function speedChoices(', 'const runCount'), context);
vm.runInContext(section('function autoParams(', '$("resetModel").onclick'), context);
vm.runInContext(section('function appliedShift(', 'function historySettingsHtml('), context);
const pick = name => { const level = context.speedLevel(); S.model = name; return context.applyModelDefaults({level}); };
const params = () => ({steps:S.steps, sampler:S.sampler, scheduler:S.scheduler, shift_video:S.shift_video, shift_audio:S.shift_audio});
const click = steps => { S.steps = steps; S.level = context.speedChoices().findIndex(([n]) => n === steps); delete S.manual.steps; };

// Untouched advanced settings follow each model's recommended values (the reported turbo 8 → regular case).
pick('regular');
assert.deepEqual(params(), regular.effective);
pick('turbo');
assert.deepEqual(params(), turbo.effective);

// The quality buttons are a top-level choice: "quality" stays "quality" across models.
click(8); pick('regular');
assert.equal(S.steps, 30, 'turbo quality(8) must become regular quality(30)');
click(20); pick('turbo');
assert.equal(S.steps, 4, 'regular fast(20) must become turbo fast(4)');
assert.equal(S.sampler, 'euler');

// A field edited directly stays, with a note; the other fields still follow the model.
S.sampler = 'dpmpp_2m'; S.manual.sampler = true; notes.length = 0;
pick('regular');
assert.equal(S.sampler, 'dpmpp_2m');
assert.equal(S.shift_video, 11);
assert(notes.at(-1).includes('샘플러 dpmpp_2m') && notes.at(-1).includes('res_multistep'));
context.applyModelDefaults({reset:true});
assert.deepEqual(params(), regular.effective, 'reset returns every field to automatic');
assert.equal(JSON.stringify(S.manual), "{}");

// Typed steps are manual and are not translated across models.
S.steps = 27; S.manual.steps = true; S.level = null;
pick('turbo');
assert.equal(S.steps, 27);
context.applyModelDefaults({reset:true});

// Loaded values (preset/history): only values different from the model's recommendation count as manual.
S.model = 'regular'; Object.assign(S, regular.effective, {steps:30, shift_video:12});
context.markManualFromValues();
assert.equal(JSON.stringify(S.manual), JSON.stringify({shift_video:true}));
assert.equal(S.level, 2, 'a quality-button step count is kept as a level, not as a manual value');

// History made before the shift fix ran at video shift 12 regardless of the recorded value.
assert.equal(JSON.stringify(context.appliedShift({shift_video:10, shift_audio:3})), JSON.stringify({shift_video:12, shift_audio:3}));
assert.equal(JSON.stringify(context.appliedShift({shift_video:10, shift_audio:3, shift_applied:true})), JSON.stringify({shift_video:10, shift_audio:3}));

// Samplers and schedulers that do not suit H3 are explained next to the dropdowns (the lists are shared by every ComfyUI model).
vm.runInContext(section('function samplingNotes(', 'function drawSamplingNote('), context);
const samplingNotesFromServer = {samplers:{heun:'스텝마다 모델을 2~3번 불러 그만큼 오래 걸립니다.'}, schedulers:{karras:'영상·소리 shift 를 따르지 않습니다.'}};
assert.deepEqual(Array.from(context.samplingNotes('euler', 'simple', samplingNotesFromServer)), []);
assert.equal(context.samplingNotes('heun', 'karras', samplingNotesFromServer).length, 2);
assert.match(context.samplingNotes('euler_cfg_pp', 'simple', samplingNotesFromServer)[0], /결과 영상이 깨집니다/);
assert.deepEqual(Array.from(context.samplingNotes('heun', 'karras', undefined)), [], 'an older server without notes must not break the page');
assert(html.includes('id="samplingNote"') && script.includes('listed(CAT.samplers, S.sampler)'));

// The requested length is rounded UP to the model's 17k+5 frame grid by the Director; the page says so and warns below the trained range.
vm.runInContext(section('function actualFrames(', 'const ONE_TAKE_KEEP'), context);
const grid = {1:39, 2:56, 3:73, 4:107, 5:124, 6:158, 7:175, 8:192, 9:226, 10:243, 11:277, 12:294, 13:328, 14:345, 15:362};
for (const [seconds, frames] of Object.entries(grid)) assert.equal(context.actualFrames(Number(seconds)), frames, `${seconds}s`);
assert.equal(context.lengthNote(5), '', '5 s is on the grid within rounding and inside the trained range');
assert.equal(context.lengthNote(8), '');
assert.match(context.lengthNote(6), /실제 길이는 6\.6초\(158프레임\)/);
assert.doesNotMatch(context.lengthNote(6), /학습한 길이/);
assert.match(context.lengthNote(4), /실제 길이는 4\.5초\(107프레임\).*학습한 길이/);
assert.match(context.lengthNote(3), /^5초보다 짧은 영상은/);
assert(html.includes('id="lengthHint"') && script.includes('actualFrames($("duration").value) / 124'));

// A turbo LoRA on a checkpoint that already has the distillation baked in is flagged (the author and the Pika Flex docs warn against stacking).
context.base = name => name.split(/[\\/]/).pop();
vm.runInContext(section('function doubleTurboNote(', 'function speedChoices('), context);
assert.match(context.doubleTurboNote(turbo, {name:'loras\\ref2v_turbo_4step.safetensors'}), /ref2v_turbo_4step\.safetensors.*일반\(터보 아님\) 모델에만/);
assert.equal(context.doubleTurboNote(regular, {name:'ref2v_turbo_4step.safetensors'}), '');
assert.equal(context.doubleTurboNote(turbo, null), '');
assert.equal(context.doubleTurboNote(undefined, undefined), '');
assert(script.includes('doubleTurboNote(m, turboLora())'));

// "Speed first" is opt-in: the dropdown offers only the modes this ComfyUI supports, keeps a saved-but-unavailable mode visible, and every request carries it.
const speedBox = {innerHTML:'', value:'', disabled:false}, speedHint = {textContent:''};
context.$ = id => ({speedMode:speedBox, speedHint})[id];
context.esc = text => String(text);
vm.runInContext(section('const SPEED_MODES =', '// 고른 샘플러·스케줄러가'), context);
context.CAT.capabilities = {speed_modes:['sparse', 'sparse_cache', 'future-mode']};
S.speed = '';
context.drawSpeedMode();
assert.equal((speedBox.innerHTML.match(/<option/g) || []).length, 3, 'default + the two known modes; unknown server modes are ignored');
assert.equal(speedBox.disabled, false); assert.equal(speedBox.value, '');
assert.match(speedHint.textContent, /결과를 바꾸지 않는/);
S.speed = 'sparse'; context.drawSpeedMode();
assert.equal(speedBox.value, 'sparse'); assert.match(speedHint.textContent, /다른 영상이 나옵니다/);
assert.equal(vm.runInContext('speedTime("sparse") < 1 && speedTime("sparse_cache") < speedTime("sparse") && speedTime("") === 1 && speedTime(undefined) === 1', context), true);
context.CAT.capabilities = {speed_modes:[]};
S.speed = 'sparse_cache'; context.drawSpeedMode();
assert.equal(speedBox.value, 'sparse_cache', 'a saved mode stays visible on a ComfyUI that lacks the nodes');
assert.match(speedBox.innerHTML, /<option value="sparse_cache">/, 'the saved mode is rendered as an option');
assert.match(speedHint.textContent, /노드가 이 ComfyUI 에 없습니다/);
S.speed = ''; context.drawSpeedMode();
assert.equal(speedBox.disabled, true); assert.match(speedHint.textContent, /필요한 노드가 없습니다/);
context.CAT.capabilities = undefined; context.drawSpeedMode();
assert.equal(speedBox.disabled, true, 'an older server without the capability must not break the page');
assert.equal((html.match(/id="speed"/g) || []).length, 1, 'the speed buttons keep their id; the dropdown is speedMode');
for (const piece of ['speed: S.speed || ""', 'speed:m.speed||""', 'speed:model.speed||""', 'speed:S.speed||""', 'S.speed = SPEED_MODES[e.speed] ? e.speed : ""'])
  assert(script.includes(piece), piece);
assert.equal(script.split('speed:m.speed||""').length - 1, 2, 'both batch request builders send it');
assert(script.includes('applySnapshot({...snapshot, model:{speed:"", ...snapshot.model}})'), 'a bundle saved before this option loads with the default, not with the choice left on screen');

// The page ships automatic defaults and labels the advanced section accordingly.
assert(script.includes('shift_video:11, shift_audio:4, manual:null, level:null'));
assert(html.includes('id="advState"') && html.includes('자동 값으로 되돌리기'));
console.log('auto settings ok');
