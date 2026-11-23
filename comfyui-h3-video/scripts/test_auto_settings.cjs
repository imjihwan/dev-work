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
assert(html.includes('id="lengthHint"'));

// A fixed camera plus an action that leaves the opening framing loses the face (measured); the page says so only for that combination.
const defaultStyle = html.match(/<textarea id="style">([^<]*)<\/textarea>/)[1];
assert.match(context.cameraNote(defaultStyle, 'She puts her hands on the table and stands up. She walks two steps toward the window.'), /카메라가 고정인데.*keeping her face in frame/);
assert.equal(context.cameraNote(defaultStyle, 'She smiles slightly, tilts her head and says a short sentence.'), '', 'seated action: nothing to warn about');
assert.equal(context.cameraNote('Photorealistic. Medium shot. The camera tilts up to follow her as she stands.', 'She stands up and walks to the window.'), '', 'a camera that follows needs no warning');
assert.equal(context.cameraNote('Photorealistic. Static camera, then the camera pans left with her.', 'She walks to the door.'), '');
assert.equal(context.cameraNote('Cinematic look, medium shot.', 'She stands up.'), '', 'no fixed camera stated: the model may move the camera');
assert.match(context.cameraNote('The camera remains static.', '그녀가 자리에서 일어나 창가로 걸어간다.'), /카메라가 고정인데/);
assert.equal(context.cameraNote('Static camera.', 'Steam rises from the cup and leaves fall outside the window.'), '', 'objects moving do not count');
assert.equal(context.cameraNote(undefined, undefined), '');
// Ways people really write it: other verb forms, Korean endings, other words for a fixed camera.
const fixedCamera = 'Photorealistic. Static camera, medium shot.';
for (const action of ['She is standing up from the chair.', 'She stood up and walked to the window.', 'He got up slowly.', 'She keeps walking toward the door.', 'She jumped off the step.',
  '그녀가 자리에서 일어선다.', '의자에서 일어나 창가로 걸어간다.', '앉아 있다가 일어난다.', '문 쪽으로 걷는다.', '창가로 달려간다.'])
  assert.notEqual(context.cameraNote(fixedCamera, action), '', `must warn: ${action}`);
for (const style of ['Tripod shot, medium framing.', 'The camera does not move.', 'Locked-off shot.', '고정 카메라, 미디엄 샷.', '카메라는 고정.', '삼각대에 올린 화면.', 'Static camera, no pan, no tilt, no tracking.'])
  assert.notEqual(context.cameraNote(style, 'She stands up and walks to the window.'), '', `a fixed camera written as: ${style}`);
// Not a person leaving the frame: negations, idioms, objects, and Korean words that only look like the verbs.
for (const action of ['She does not stand up.', "She doesn't walk away, she stays seated.", 'She runs her hand through her hair.', 'A tear runs down her cheek.', 'She leans on a walking stick.',
  'She stands still and smiles.', '무슨 일이 일어나는지 창밖을 본다.', '액자를 벽에 걸어 둔다.', '뛰어난 연기를 보여 준다.'])
  assert.equal(context.cameraNote(fixedCamera, action), '', `must not warn: ${action}`);
for (const style of ['Static framing at first, then the camera follows her.', '고정 카메라로 시작해 카메라가 인물을 따라간다.', 'Handheld camera.'])
  assert.equal(context.cameraNote(style, 'She stands up and walks to the window.'), '', `the camera moves with her: ${style}`);
assert(html.includes('id="cameraHint"') && script.includes('manualFinal ? "" : cameraNote($("style").value') && script.includes('.filter((d,i) => !late.includes(i))'),
  'the hint judges the automatic prompt only, without the shots that were dropped as too late');

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

// The time estimate follows the measured token model (docs/PERFORMANCE.md) and is calibrated by this PC's own finished jobs.
vm.runInContext(section('const ETA =', 'function drawSpeed('), context);
const eta = options => context.etaSeconds({pixels:768 * 960, seconds:5, steps:8, speed:'', ...options});
const near = (value, measured, tolerance, label) => assert(Math.abs(value - measured) <= measured * tolerance, `${label}: model ${value.toFixed(1)} s, measured ${measured} s`);
// Measured totals with a new prompt (text and photo encoding included); benchmark runs that reused the encoding have its 6.4 s added.
near(eta({}), 167.4, 0.05, '5 s default through the page server');
near(eta({seconds:10}), 419.8, 0.05, '10 s default');
near(eta({speed:'sparse'}), 120.9 + 6.4, 0.05, '5 s sparse attention');
near(eta({seconds:10, speed:'sparse'}), 284.0, 0.05, '10 s sparse attention');
near(eta({speed:'sparse_cache'}), 100.9, 0.05, '5 s sparse attention + step cache through the page server');
assert(eta({seconds:10, speed:'sparse'}) / eta({seconds:10}) < eta({speed:'sparse'}) / eta({}), 'longer clips gain more from sparse attention');
// Step-time ratios against the 5 s 768x960 run of the same seed (measured without the chunk node): the model stays within 6% of each.
const stepRatio = options => (eta({...options, steps:9}) - eta({...options, steps:8})) / (eta({steps:9}) - eta({steps:8}));
for (const [label, options, measured] of [['3 s', {seconds:3}, 0.521], ['8 s', {seconds:8}, 1.840], ['10 s', {seconds:10}, 2.610], ['draft 576x736', {pixels:576 * 736}, 0.482],
  ['720p at 4:5 (864x1088)', {pixels:864 * 1088}, 1.396], ['9:16 (768x1376)', {pixels:768 * 1376}, 1.646], ['9:20 (768x1696)', {pixels:768 * 1696}, 2.233], ['21:9 (1792x768)', {pixels:1792 * 768}, 2.427]])
  near(stepRatio(options), measured, 0.06, `step time ratio for ${label}`);
assert.equal(eta({pixels:384 * 480, seconds:3, speed:'sparse'}), eta({pixels:384 * 480, seconds:3}), 'below min_tokens the sparse node computes densely');
assert.equal(context.canvasPixels('auto', 'auto', 768 / 960), 768 * 960);
assert.equal(context.canvasPixels('9:16', 'auto', 0), 768 * 1376, 'a fixed aspect ignores the photo; the long side snaps to 32');
assert.equal(context.canvasPixels('16:9', 'auto', 0), 1376 * 768);
assert.equal(context.canvasPixels('auto', 'auto', 0), 768 * 1024, 'no photo yet: assume a 3:4 phone photo');
// Above the model's pixel budget (768x1344) the page says what size will be made and what it costs; the default behaviour is unchanged.
assert.deepEqual(Array.from(context.canvasSize('9:16', 'auto', 0)), [768, 1376]);
assert.equal(context.sizeNote('9:16', 'auto', 0), '', '9:16 at the default quality is within the budget: no note');
assert.equal(context.sizeNote('auto', 'auto', 768 / 960), '');
assert.equal(context.sizeNote('auto', '720p', 9 / 20), '', 'the fixed-area qualities below the budget get no note');
assert.match(context.sizeNote('auto', 'auto', 9 / 20), /^만들어질 크기는 약 768×1696\(1\.30MP\)라, 768×960 보다 한 편이 약 2\.[12]배 오래 걸립니다\..*720p/, 'measured: 376 s against 179 s');
assert.match(context.sizeNote('21:9', 'auto', 0), /1792×768\(1\.38MP\).*약 2\.[234]배/, 'measured: 407 s against 179 s');
assert.match(context.sizeNote('16:9', '1080p', 0), /^만들어질 크기는 약 \d+×\d+\(2\.\d\dMP\)라/);
assert.doesNotMatch(context.sizeNote('16:9', '1080p', 0), /720p/, 'someone who chose 1080p is not told to pick 720p');
assert(html.includes('id="sizeHint"') && script.includes('addEventListener("load", refreshSizeEstimate'));
assert(context.canvasPixels('1:1', 'draft', 0) < context.canvasPixels('1:1', 'auto', 0) && context.canvasPixels('1:1', 'auto', 0) < context.canvasPixels('1:1', '1080p', 0));
const row = (factor, job = {}) => {
  const j = {width:768, height:960, duration:5, steps:8, speed:'', ...job};
  return {state:'done', ...j, generation_seconds:context.etaSeconds({pixels:j.width * j.height, seconds:j.duration, steps:j.steps, speed:j.speed, photos:j.mode === 'REF2VA' ? j.images.length : 1, upscale:j.resolution === 'up15' ? 1.5 : undefined}) * factor};
};
// Every extra reference photo slows each step by about 8% at 5 s (measured: 17.97 s with one photo, 21.0 s with three; 209.6 s for the clip).
near(eta({photos:3}), 209.6, 0.03, '5 s with three reference photos');
near(eta({photos:9}), 324, 0.03, '5 s with nine reference photos (one photo plus eight face crops at full size)');
assert.equal(eta({photos:1}), eta({}), 'one photo is the reference case');
assert.equal(eta({photos:0}), eta({}));
assert(eta({seconds:10, photos:3}) / eta({seconds:10}) < eta({photos:3}) / eta({}), 'the photos weigh less in a longer clip');
near(context.etaScale([row(1.3, {mode:'REF2VA', images:['a', 'b', 'c']}), row(1.3, {mode:'FL2VA', images:['a', 'b']}), row(1.3, {mode:'REF2VA', images:['a']})]), 1.3, 0.001, 'reference photos are counted for the reference mode only');
const finished = factor => row(factor);
assert.equal(context.etaScale([]), null);
assert.equal(context.etaScale([finished(2), finished(2)]), null, 'two finished jobs are not enough to calibrate');
near(context.etaScale([finished(1.4), finished(1.5), finished(9)]), 1.5, 0.001, 'median of recent jobs (a cold start does not dominate)');
near(context.etaScale([{...finished(2), state:'error'}, {...finished(2), generation_seconds:null}, finished(1.2), finished(1.2), finished(1.2)]), 1.2, 0.001, 'only finished jobs with a recorded time count');
near(context.etaScale([row(1.3, {duration:10}), row(1.3, {steps:25}), row(1.3, {width:768, height:1376}), row(1.3, {speed:'sparse'}), row(1.3, {speed:'sparse_cache', duration:8}), row(1.3, {width:576, height:736})]), 1.3, 0.001, 'every job is compared with the model for its own length, steps, size and speed mode');
near(context.etaScale([{...finished(1), generation_seconds:0.8}, {...finished(1), generation_seconds:1.5}, {...finished(1), generation_seconds:2}, finished(1.2), finished(1.2), finished(1.2)]), 1.2, 0.001, 'a job answered from the ComfyUI cache in a second or two is not a speed sample');
assert.equal(context.etaScale([{...finished(1), generation_seconds:0.8}, {...finished(1), generation_seconds:1.5}, finished(1.2), finished(1.2)]), null);
assert.equal(context.etaScale([finished(50), finished(50), finished(50)]), 3, 'clamped above');
assert.equal(context.etaScale([finished(0.3), finished(0.3), finished(0.3)]), 0.4, 'clamped below');
const many = factor => Array.from({length:30}, () => finished(factor));
assert.equal(context.etaScale([...Array.from({length:5}, () => finished(1)), ...Array.from({length:4}, () => finished(2)), ...many(3)]), 1, 'the window is not larger than nine finished jobs');
assert.equal(context.etaScale([...Array.from({length:4}, () => finished(2)), ...Array.from({length:5}, () => finished(1)), ...many(3)]), 1, 'the window is not smaller than nine finished jobs');
// Below the reference size the growth is a little flatter (draft 576x736 measured: 9.21 s a step against 19.14 s, 90 s a clip against 177 s); above it the fitted power applies.
assert(eta({pixels:576 * 736}) / eta({}) > 0.48 && eta({pixels:576 * 736}) / eta({}) < 0.56, 'draft');
assert(eta({pixels:768 * 1376}) / eta({}) > 1.55 && eta({pixels:768 * 1376}) / eta({}) < 1.7, '9:16 at the default quality');
context.$ = id => ({aspect:{value:'auto'}, resolution:{value:'auto'}, duration:{value:5}, thumbs:{querySelector:() => ({naturalWidth:768, naturalHeight:960})}})[id];
S.steps = 8; S.speed = '';
assert.equal(context.etaText(1), '예상 약 3분', 'before the history list exists the model is used as it is');
vm.runInContext('var HIST = {items: []};', context);
context.HIST.items = [finished(2), finished(2), finished(2)];
assert.equal(context.etaText(1), '예상 약 6분');
assert.equal(context.etaText(3), '예상 약 17분');
context.HIST.items = [];
S.speed = 'sparse'; assert.equal(context.etaText(1), '예상 약 2분', 'the speed mode is part of the estimate');
S.speed = ''; S.steps = 4; assert.equal(context.etaText(1), '예상 약 2분', 'so are the steps');
S.steps = 8;
context.$ = id => ({aspect:{value:'auto'}, resolution:{value:'720p'}, duration:{value:10}, thumbs:{querySelector:() => ({naturalWidth:768, naturalHeight:960})}})[id];
assert.equal(context.etaText(1), `예상 약 ${Math.round(context.etaSeconds({pixels:context.canvasPixels('auto', '720p', 0.8), seconds:10, steps:8, speed:''}) / 60)}분`, 'and the chosen quality and length');
assert(context.etaSeconds({pixels:context.canvasPixels('auto', '720p', 0.8), seconds:10, steps:8, speed:''}) > 2.5 * eta({}));
// With a long queue the loaded history may hold fewer than three finished jobs: the last factor is remembered in the browser.
const kept = new Map();
context.localStorage = {getItem:key => kept.has(key) ? kept.get(key) : null, setItem:(key, value) => kept.set(key, String(value))};
assert.equal(context.etaFactor([]), 1, 'nothing remembered yet');
near(context.etaFactor([finished(1.6), finished(1.6), finished(1.6)]), 1.6, 0.001, 'a fresh factor is used and remembered');
near(context.etaFactor([finished(9), {state:'queued'}, {state:'running'}]), 1.6, 0.001, 'fewer than three finished jobs loaded: the remembered factor');
kept.set(vm.runInContext('ETA_KEY', context), 'junk');
assert.equal(context.etaFactor([]), 1, 'an unusable remembered value is ignored');
context.localStorage = {getItem:() => { throw new Error('blocked'); }, setItem:() => { throw new Error('blocked'); }};
near(context.etaFactor([finished(1.6), finished(1.6), finished(1.6)]), 1.6, 0.001, 'storage that throws does not break the estimate');
assert.equal(context.etaFactor([]), 1);
assert(script.includes('if (CAT) refreshSizeEstimate();') && script.includes('if (typeof drawEstimates === "function") drawEstimates();'), 'both estimate labels are refreshed when the history arrives and on every render');

// "Default + 1.5x upscale" (opt-in): made at the default size, then grown by the latent upscaler and refined for one step.
// Measured at 5 s without the chunk node: 176.7 s at 768x960, 266.6 s for 1152x1440 through the upscaler, 540.1 s when 1152x1440 is sampled directly.
near(eta({upscale:1.5}) - eta({}), 266.6 - 176.7, 0.08, 'the upscale stage and the larger decode');
assert.equal(eta({upscale:1}), eta({})); assert.equal(eta({upscale:undefined}), eta({}));
assert(eta({upscale:1.5}) < 0.6 * eta({pixels:1152 * 1440}), 'about half the time of sampling the large canvas directly');
assert(eta({seconds:10, upscale:1.5}) - eta({seconds:10}) > 1.8 * (eta({upscale:1.5}) - eta({})), 'the upscale stage grows with the clip length');
near(context.etaScale([row(1.3, {resolution:'up15'}), row(1.3, {resolution:'up15', duration:8}), row(1.3, {resolution:'auto'})]), 1.3, 0.001, 'finished upscaled jobs are compared with the upscaled model');
assert.match(context.sizeNote('auto', 'up15', 768 / 960), /^약 768×960 로 만든 뒤 1\.5배로 키워 약 1152×1440 로 저장합니다.*약 절반 시간/);
assert.match(context.sizeNote('1:1', 'up15', 0), /768×768 로 만든 뒤 1\.5배로 키워 약 1152×1152/);
// 1376 x 1.5 / 32 = 64.5: the node rounds half to even (Python round), so the saved long side is 2048, not 2080.
assert.match(context.sizeNote('9:16', 'up15', 0), /768×1376 로 만든 뒤 1\.5배로 키워 약 1152×2048/);
assert.equal(vm.runInContext('sizeText(768, 960, "up15")', context), '768×960 → 1152×1440');
assert.equal(vm.runInContext('sizeText(768, 1376, "up15", " × ")', context), '768 × 1376 → 1152 × 2048');
assert.equal(vm.runInContext('sizeText(768, 960, "auto") + "|" + sizeText(768, 960, undefined)', context), '768×960|768×960');
assert(script.includes('sized(j.width, j.height)') && script.includes('sizeText(w, h, quality)') && script.includes('sizeText(e.width, e.height, e.resolution, " × ")'), 'the queue line and the history row show the saved size too');
assert.deepEqual(Array.from(context.canvasSize('auto', 'up15', 768 / 960)), [768, 960], 'the canvas that is sampled is the default one');
const upOption = {disabled:false}, qualityBox = {value:'auto', querySelector:selector => selector === 'option[value="up15"]' ? upOption : null}, sizeBox = {textContent:''}, etaBox = {textContent:''};
context.$ = id => ({aspect:{value:'auto'}, resolution:qualityBox, duration:{value:5}, sizeHint:sizeBox, eta:etaBox, thumbs:{querySelector:() => ({naturalWidth:768, naturalHeight:960})}})[id];
context.CAT.capabilities = {upscale_modes:[]};
context.drawEstimates();
assert.equal(upOption.disabled, true, 'a ComfyUI without the upscaler node or model cannot pick it');
assert.equal(sizeBox.textContent, '');
qualityBox.value = 'up15'; context.drawEstimates();
assert.equal(upOption.disabled, false, 'a saved choice stays selectable so that it can be seen and changed');
assert.match(sizeBox.textContent, /업스케일 모델 파일이 없어 이 화질로 만들 수 없습니다/);
context.CAT.capabilities = {upscale_modes:['up15']}; context.drawEstimates();
assert.match(sizeBox.textContent, /1152×1440 로 저장합니다/); assert.equal(upOption.disabled, false);
assert.match(etaBox.textContent, /예상 약 4분/, '11 + 8 x 17.85 + 73 + 13 x 2.25 = 256 s');
qualityBox.value = 'auto'; context.drawEstimates();
assert.equal(upOption.disabled, false); assert.equal(sizeBox.textContent, ''); assert.match(etaBox.textContent, /예상 약 3분/);
context.CAT.capabilities = undefined; context.drawEstimates();
assert.equal(upOption.disabled, true, 'an older server without the capability must not offer it');
assert(html.includes('<option value="up15">기본 + 1.5배 업스케일</option>') && script.includes('up15: "기본 + 1.5배 업스케일"'));

// In reference mode a style LoRA competes with the reference photo: the page says so from strength 0.7 (measured on the realism LoRA).
vm.runInContext(section('function loraStrengthNote(', 'function drawLoras('), context);
const realism = {name:'loras\\h3-realism-people-t2v-i2v-r2v.safetensors', auto:{}}, cinematic = {name:'cinematic.safetensors', auto:{}}, turboLoraCard = {name:'ref2v_turbo_4step.safetensors', auto:{turbo:true}};
assert.equal(context.loraStrengthNote(realism, 0.5, true), '');
assert.match(context.loraStrengthNote(realism, 0.7, true), /0\.5 안팎을 권합니다.*실측: 이 LoRA 는 앉아서 말하는 근접 장면에서 0\.7부터/);
assert.match(context.loraStrengthNote(realism, '1', true), /극단적 클로즈업/);
assert.match(context.loraStrengthNote(cinematic, 1, true), /0\.5 안팎을 권합니다\(H3 문서\)\.$/, 'other LoRAs get the documented advice only, not the measurement');
assert.equal(context.loraStrengthNote(turboLoraCard, 1, true), '', 'an acceleration LoRA is meant to run at 1');
assert.equal(context.loraStrengthNote(realism, 1, false), '', 'first/last-frame modes have no reference photo to compete with');
assert.equal(context.loraStrengthNote(undefined, undefined, true), '');
assert(script.includes('class="note strnote"') && script.includes('hint.hidden = !text'));

// The page ships automatic defaults and labels the advanced section accordingly.
assert(script.includes('shift_video:11, shift_audio:4, manual:null, level:null'));
assert(html.includes('id="advState"') && html.includes('자동 값으로 되돌리기'));
console.log('auto settings ok');
