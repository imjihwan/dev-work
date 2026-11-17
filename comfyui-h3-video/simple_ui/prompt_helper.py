"""Text-only prompt drafts using an on-demand, low-priority CPU process."""
import ctypes
import json
import math
import os
import re
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

FIELDS = ("summary", "sound", "music")
FIXED_FIELDS = ("subject", "style", "keep")
REFERENCE_APPEARANCE = "Keep the subject's appearance exactly as in <Picture 1> throughout the video."
# Adapted from DutchIT/minimax-prompt-enhancer Modelfile.ref (Apache-2.0).
# Pinned upstream and modification notes: third_party/dutchit/NOTICE.md.
DUTCHIT_MODEL = "Huihui-Qwen3-VL-8B-Instruct-abliterated.Q4_K_M.gguf"
DUTCHIT_POLICY = "dutchit-ref-adapter-v1"
DUTCHIT_SYSTEM = """You are the DutchIT MiniMax H3 reference-prompt adapter for an existing editor.
H3 produces video and audio together. Make the requested action, its physical sound,
and the passage of time agree, with concrete preparation, contact, travel and outcome.
The host assembles six H3 sections. Its subject_definitions and retention_analysis are
already supplied as fixed.subject and fixed.keep; the style/camera prefix of
detailed_description is fixed.style. Copying, paraphrasing, replacing or overriding
those fields is forbidden. Return only the editable JSON fields requested by the host.
Use an existing <Subject N> label only if the supplied text defines it. Never infer
what any unseen reference image contains. This adapter receives TEXT ONLY, no images.
Picture 1 is the primary reference; Pictures 2 through reference_count are alternate
views of that same identity, never new characters, locations, styles or storyboards.
The anchor flag is owned by the host: when true the first frame is fixed by the
workflow. Begin feasible movement from that frame; never promise a different opening.
When anchor is false, references still define identity; do not toggle frame anchoring.
Use the supplied duration exactly, without an 8/10-second default. Phase times describe
continuous action, not separate camera shots. For one_take=true do not introduce cuts,
fades, viewpoint resets or time jumps. Use only the camera path already in fixed.style.
Do not put camera, framing, lighting or location instructions in generated action text.
The unchanged fixed camera prefix supplies them, including any initial zoom then hold.
Do not guess age, ethnicity, clothing, accessories or anatomy; all appearance belongs
to the reference and fixed fields. Do not add speech, objects or music without a request.
If dialogue is requested, preserve its exact words and language inside <d> tags; add a
speaker ID only to someone who actually speaks. Never put a speaker ID on a silent actor.
For partial editing, make only exact requested substring edits; unchanged words,
whitespace, time values, phase order and all fixed constraints remain byte-for-byte.
The host may use the same adapter for first/end-frame mode and a four-clip story; obey
that mode and story_context instead of forcing reference-mode defaults.
"""
SYSTEM = """You write detailed, executable MiniMax H3 video prompts from a user's idea.
Return JSON only, with summary, sound, music, shots.
All descriptions must be English; preserve the original language of spoken dialogue.
Each shot is {"time": seconds, "text": description}. First time is 0; every time must
be before the video ends, strictly increasing. Times mark continuous action phases,
not cuts. Use 1-3 connected beats within the requested duration. Spread the beat start
times across the whole duration in proportion to how long each action takes; never
crowd several actions into the first seconds and leave one long idle beat at the end. The final beat must
leave time for its action to complete or hand off naturally to the following clip.
Keep summary to ONE sentence. Start the requested movement at time 0, rather than
spending the first phase standing still. Put every requested action, including the
final lowering/releasing/settling action, in shots as well as summary.
Keep shots concise: about 60-150 English words in total across the action descriptions.
Describe only the requested actions. Never fill space with appearance, clothing, hair,
colors, props, furniture or setting details; those come from <Picture 1> and the fixed fields.
Detail means precise motion, not more events, objects or adjectives.
Describe the relevant preparation, direction and extent of movement, speed/acceleration,
contact or weight transfer, visible response, and settled or continuing end state.
Develop one main action with supporting micro-movements that actually serve it.
Use gaze/expression/hand/body changes only as supported by the requested action.
Track the same actor, object, grip, contact, balance and motion direction over time.
For contact actions, reach and contact precede lifting, pulling or releasing. Bodies
and objects follow continuous paths: no teleportation, interpenetration, instant
pose changes, unexplained hand swaps, or incompatible simultaneous actions.
Budget preparation, travel, reaction and recovery in real seconds. Reserve the ending
for a stable pose or continuous motion handoff. Do not require multiple full actions
in one short interval, rushed dialogue, or a distant destination reached instantly.
If the request cannot fit, describe a slower feasible partial progression toward it,
without claiming the entire request was completed; the separate reviewer will flag it.
Preserve exactly the objects and actions the user named; never substitute, add or name any other object.
The fixed subject, style (location, atmosphere, camera), and keep fields are immutable
constraints. Do not rewrite or override them, even when the idea conflicts with them.
Do not add or change locations, camera movements, lighting, or visual styles. Follow
the supplied fixed camera exactly; never invent a zoom/pan/cut to create detail.
Keep the subject's appearance, face, identity, hairstyle, body and outfit exactly as in
<Picture 1>. Do not invent or change gender, age, facial features, hair, clothing or
colors in the summary or shots. Never guess what unseen photos show. Describe actions
using "the subject" when no subject was supplied. Avoid inventing extra
characters or unrelated actions. Do not add dialogue or music unless requested.
Use music="N/A" if no music. Sound must describe the requested ambience (for example
"Quiet room tone."); do not use N/A for sound unless the user requests silence.
For one_take=true use continuous real-time action, no cuts, and one consistent location.
One take does not require fixed framing: allow only the camera movement explicitly
specified in the fixed style field, including a continuous zoom followed by a hold.
Never replace that movement with a cut, a new shot, or a reset of the scene.
If existing editable text is provided, revise it following the idea; otherwise draft anew.
Do not guess an unseen photo's pose, limb side, layout or available props. Use the
established starting state and relative movements when those details are unspecified.
No section headings inside field values. No markdown or explanation.
"""
SCHEMA = {"type": "object", "properties": {**{key: {"type": "string"} for key in FIELDS},
    "shots": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "object",
        "properties": {"time": {"type": "number"}, "text": {"type": "string"}},
        "required": ["time", "text"], "additionalProperties": False}}},
    "required": [*FIELDS, "shots"], "additionalProperties": False}
EDIT_SYSTEM = """You are a minimal editor of an EXISTING MiniMax H3 video prompt.
Return JSON {"edits":[{"target":"...","index":0,"before":"exact original substring","after":"replacement"}]}.
Field meanings: music is BACKGROUND MUSIC (배경음악, BGM, 음악). sound is ambient noise
and physical sound effects (환경음, 효과음), NOT music. A background-music-only request
must edit music ONLY, leaving sound, summary and all shots unchanged.
Example: existing music="N/A", idea="배경음악만 피아노로 바꿔줘" ->
{"edits":[{"target":"music","index":0,"before":"N/A","after":"Gentle piano music."}]}.
Make ONLY changes explicitly requested by idea. Everything else must remain byte-for-byte
identical: no paraphrasing, translation, polishing, formatting, new detail, default sounds,
summary updates, extra actions, reordered shots, or changed timing unless specifically asked.
An edit replaces one unique exact substring within one target. Copy before exactly from
existing text. Use a short phrase, not a whole sentence when a phrase suffices. For an empty
field only, before may be empty. Return edits=[] if no permitted change is needed.
For structured input, targets are summary, sound, music, shot_text, shot_time.
index is the zero-based shot index for shot targets, otherwise 0. Keep every other shot.
For manual_prompt input, target must be prompt, index 0. Edit only the requested words in
editable H3 sections; never replace a whole prompt or change section headings.
Fixed subject, style/location/camera, and keep constraints are immutable. Preserve appearance,
face and outfit exactly as in <Picture 1>; never introduce changes to appearance or clothes.
Keep the original language and punctuation of unaffected text. Do not add an appearance
reminder if missing: this mode changes only what was requested. Within the requested
change, use precise, physically continuous motion and realistic timing. Do not repair
unrelated issues; a separate reviewer reports them without changing the original.
Output no explanation.
"""
EDIT_SCHEMA = {"type":"object", "properties":{"edits":{"type":"array", "maxItems":12,
    "items":{"type":"object", "properties":{
        "target":{"type":"string","enum":[*FIELDS,"shot_text","shot_time","prompt"]},
        "index":{"type":"integer","minimum":0,"maximum":5},
        "before":{"type":"string"},"after":{"type":"string"}},
        "required":["target","index","before","after"],"additionalProperties":False}}},
    "required":["edits"],"additionalProperties":False}
STORY_SYSTEM = """\nThis is one clip of a four-clip continuous story. Write or minimally edit ONLY the
clip_index requested (zero-based). Each clip adds about five seconds. The original photo
defines appearance for all clips. Later clips start from the preceding clip's actual tail;
never reset to the original pose or repeat completed actions. Use story_context to make
the current action fit its opening/ending states and the neighboring scenarios. When a
boundary is blank, plan a plausible handoff without changing another clip's scenario.
Do not invent a cut, fade, new location, new costume, or camera move beyond fixed constraints. Other clips are context,
not text to rewrite. Keep actions achievable within this clip's duration.
"""
REVIEW_SYSTEM = """영상 프롬프트의 동작과 시간 흐름을 검토한다. JSON만 출력한다.
문제가 없으면 issues=[]와 status=ok를 반환한다. 억지로 문제를 찾지 않는다.
candidate는 실제 영상이 아니라 프롬프트 텍스트다. timeline은 코드가 계산한 가용 시간이다.
동작의 준비·접촉·이동·마무리가 시간 안에 가능한지, 순서와 물체·신체 상태가 모순되는지,
고정 조건 위반이나 요청 동작 누락, 앞뒤 편의 연결 충돌이 있는지 확인한다.
사진·실제 영상을 못 봤다는 이유만으로 문제를 만들지 않는다. 원문에 없는 속도·각도·거리·횟수를
가정하지 않는다. 원본의 생김새를 추측하지 않는다. quiet room tone은 말이나 음악이 아니다.
고개를 천천히 돌리고 미소 지은 뒤 원래 방향으로 돌아오는 5초 연결 동작은 보통 가능하다.
서로 다른 중요한 문제만 최대 3개 쓴다. 같은 문제를 반복하지 않는다.
각 문제의 evidence는 candidate 또는 fixed/story_context에서 그대로 복사한 짧은 원문이다.
영어 원문이면 evidence도 영어 그대로 복사한다. 번역·의역·생략 부호를 넣지 않는다.
summary, issue, suggestion은 한국어로 쓴다. 근거 없는 수치·물리 법칙·해결책을 만들지 않는다.
최소 수정으로 동작 단순화·시간 조정·다음 편으로 분배를 제안한다. 원문을 자동 수정하지 않는다.
severity는 warning 또는 critical, category는 timing/physics/continuity/constraints/uncertainty이다.
status는 큰 충돌 미검출 ok, 주의 caution, 명백한 주요 충돌 revise이다.
예시 A: 5초 안에 고개 돌리기→미소→원래 방향으로 돌아오기, 각 구간에 시간이 배분됨.
출력: {"status":"ok","summary":"주어진 시간과 동작 순서에서 큰 충돌이 발견되지 않았습니다.","issues":[]}
예시 B: 5초 영상의 4초 시점 원문에 "remains motionless for ten complete seconds"가 있음.
출력: {"status":"revise","summary":"마지막 동작이 남은 시간을 초과합니다.","issues":[{"severity":"critical","category":"timing","at":"4–5초","evidence":"for ten complete seconds","issue":"남은 1초 안에 10초 정지를 완료할 수 없습니다.","suggestion":"정지를 남은 시간으로 줄이거나 다음 편으로 나누세요."}]}
텍스트 검토로 실행 가능성이나 실제 영상 품질을 보장하지 않는다.
"""
REVIEW_SCHEMA = {"type":"object","properties":{
    "status":{"type":"string","enum":["ok","caution","revise"]},"summary":{"type":"string"},
    "issues":{"type":"array","maxItems":3,"items":{"type":"object","properties":{
        "severity":{"type":"string","enum":["warning","critical"]},
        "category":{"type":"string","enum":["timing","physics","continuity","constraints","uncertainty"]},
        **{key:{"type":"string"} for key in ("at","evidence","issue","suggestion")}},
        "required":["severity","category","at","evidence","issue","suggestion"],"additionalProperties":False}}},
    "required":["status","summary","issues"],"additionalProperties":False}
DETAIL_SYSTEM = """Expand the action descriptions in this NEW MiniMax H3 draft.
Return JSON with exactly the requested beat IDs as keys, each value one detailed
English paragraph for that beat ONLY. beats contains the start/end seconds and action.
Do NOT combine the entire sequence into the first beat. Do NOT output field names
such as sound/music as descriptions. Keep the original actions, actors, objects, timing,
starting/ending states and requested intent. Do not add new events or directions.
Make each paragraph about 80-130 words where useful, with several concrete sentences:
describe how the motion starts, its continuous path, pace and extent, any established
contact/grip/balance, the visible response, and how that phase ends or leads onward.
Detail the mechanics of the SAME movement rather than inventing more movements.
For example, for an already requested turn, specify gradual initiation, continuous
rotation and gentle deceleration; do not add walking, waving or new props.
Use only details supported by the requested action. Do not guess an unseen photo's
pose, hand side, support geometry, distances, body appearance or available objects.
Do not change fixed subject/style/keep, camera/framing, location, lighting, face or
clothing. Appearance always stays as in <Picture 1>. Do not add cuts, music or dialogue.
Avoid poetic adjectives, repeated preservation rules, lists and filler. A simple action
may stay shorter if there is nothing useful to add. Existing fields are context only.
"""
SECTION_HEADERS = re.compile(r"(?m)^(subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music|integrated_multimodal_description):[ \t]*")


# 사용자 요청·고정 칸·현재 내용에 없는데 모델이 지어내기 쉬운 단어(외모는 사진 1, 장소는 고정 칸이 정한다).
# 동작 설명에 자주 쓰이는 단어(plant=발을 딛다, ball=발볼, curls=손가락을 말다, tie, watch 등)는 넣지 않는다.
UNREQUESTED_TERMS = {
    "옷": "shirt t-shirt blouse sweater jumper hoodie cardigan jacket coat blazer vest dress skirt jeans trousers pants shorts suit uniform apron scarf hat cap beanie helmet gloves shoes boots sneakers heels socks",
    "장신구": "glasses sunglasses earring earrings necklace bracelet wristwatch handbag bag backpack purse",
    "머리 모양": "ponytail bun braid braids bangs",
    "색": "white black red blue green yellow pink purple beige brown gray grey orange",
    "소품": "teapot cup mug glass bottle book books phone smartphone laptop tablet umbrella flower flowers bouquet pen paper notebook cigarette guitar toy tray plate bowl",
    "가구": "table desk chair sofa couch bed shelf bookshelf lamp curtain curtains window door mirror",
    "장소": "living room|kitchen|bedroom|office|cafe|café|restaurant|street|park|beach|garden|studio|hallway|corridor|classroom|balcony",
}
_TERM_RES = [(kind, term, re.compile(r"(?<![\w-])" + re.escape(term) + r"(?:s|es)?(?![\w-])", re.IGNORECASE))
             for kind, terms in UNREQUESTED_TERMS.items()
             for term in (terms.split("|") if "|" in terms else terms.split())]


def request_text(request):
    """요청에서 사용자가 직접 쓴 글 전체(이 안에 있는 단어는 지어낸 것이 아니다)."""
    parts = [request.get("idea", ""), request.get("manual_prompt", "")]
    parts += [value for value in (request.get("fixed") or {}).values() if isinstance(value, str)]
    existing = request.get("existing") or {}
    parts += [value for key, value in existing.items() if isinstance(value, str)]
    parts += [str(shot[1]) for shot in existing.get("shots", []) if isinstance(shot, list) and len(shot) == 2]
    parts.append(json.dumps(request.get("story_context") or {}, ensure_ascii=False))
    return " ".join(parts)


def unrequested_terms(text, allowed):
    found = []
    for kind, term, pattern in _TERM_RES:
        if pattern.search(text) and not pattern.search(allowed) and term not in found:
            found.append(term)
    return found


# 지어낸 단어를 꾸미는 구(句): "wearing a blue jacket", "in a sunlit living room", "holding a white teapot"
_PHRASE_LEAD = (r"(?:wearing|dressed in|clad in|holding|carrying|clutching|gripping|next to|in front of|"
                r"toward|towards|in|with|on|at|near|beside|by|inside|from|across|into|onto|under|behind|over|against)")
_ARTICLE = r"(?:(?:a pair of|a|an|the|his|her|their|its)\s+)?"
_COLOR_TERMS = set(UNREQUESTED_TERMS["색"].split())
# 지어낸 물건을 목적어로 받는 동사: "holds a cup and smiles" → "smiles"
_OBJECT_VERB = r"(?:holds|carries|wears|clutches|grips|sips from|drinks from|picks up|puts down|sets down)"
_DETERMINERS = {"a", "an", "the", "his", "her", "their", "its", "this", "that"}


def _is_sentence(text):
    """잘라 낸 뒤 남은 것이 문장 구실을 하는지: 3단어 이상, 또는 "She waves." 같은 2단어(관사+명사 "The subject." 는 아님)."""
    words = text.rstrip(".!?").split()
    return len(words) >= 3 or (len(words) == 2 and words[0].lower() not in _DETERMINERS)


def _tidy(sentence):
    """구·절을 뺀 뒤 쉼표·공백·대문자·마침표를 정리한다."""
    text = re.sub(r"\s+", " ", sentence)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    text = re.sub(r"(?:,\s*){2,}", ", ", text)
    text = re.sub(r"^[,;\s]+|[,;\s]+$", "", text)
    text = re.sub(r"(?:,?\s+(?:and|or|while|as|then))+([.!?]?)$", r"\1", text)
    text = re.sub(r",\s*([.!?])$", r"\1", text)
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def _drop_phrases(sentence, allowed):
    """지어낸 단어가 든 구만 뺀다. 남은 문장에 지어낸 단어가 없고 문장 구실을 하면 성공."""
    result, cut = sentence, []
    terms = unrequested_terms(sentence, allowed)
    # 명사(옷·소품·장소)를 먼저: "a white teapot" 에서 색만 먼저 자르면 "teapot" 이 홀로 남는다
    terms.sort(key=lambda term: term in _COLOR_TERMS)
    any_term = "(?:" + "|".join(re.escape(term) for term in terms) + r")(?:s|es)?(?![\w-])"
    # 수식어는 0~3단어, 다른 구의 시작 단어는 넘지 않는다("in the room holding a cup" 에서 room 까지 지우지 않게)
    modifier = r"(?:(?!" + _PHRASE_LEAD + r"\s)[\w'-]+\s+)"
    for term in terms:
        word = re.escape(term) + r"(?:s|es)?(?![\w-])"
        if term in _COLOR_TERMS:
            # 색이 구의 끝("dressed in white")일 때만 구째, 아니면 꾸밈말인 색 단어만 뺀다("a white teapot" → "a teapot")
            word += r"(?=\s*(?:[,.;!?]|$)|\s+(?:and|or|while|as|then)\b)"
        pattern = re.compile(r"(,\s*)?(?<![\w-])(?:(?P<verb>" + _OBJECT_VERB + ")|" + _PHRASE_LEAD + r")\s+" + _ARTICLE + modifier + "{0,3}?" + word +
                             # "white shirt and black jeans" 처럼 지어낸 단어끼리 and/or 로 이어지면 함께
                             r"(?:\s+(?:and|or)\s+" + _ARTICLE + modifier + "{0,2}?" + any_term + r"(?:\s+" + any_term + ")*)?" +
                             # 앞 쉼표를 먹었으면 짝이 되는 뒤 쉼표도("The subject, wearing a jacket, waves")
                             r"(?(1)\s*,?)" +
                             # 동사째 빼면 뒤의 and 도("holds a cup and smiles" → "smiles")
                             r"(?(verb)(?:\s+and(?=\s))?)", re.IGNORECASE)
        for match in list(pattern.finditer(result)):
            if unrequested_terms(match.group(0), allowed):
                cut.append(match.group(0).strip(" ,"))
                result = result.replace(match.group(0), " ", 1)
        if term in _COLOR_TERMS:
            bare = re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])(?:\s*(?:and|or|-)\s*(?:" +
                              "|".join(sorted(_COLOR_TERMS)) + r")(?![\w-]))?", re.IGNORECASE)
            for match in list(bare.finditer(result)):
                cut.append(match.group(0))
            result = bare.sub(" ", result)
    result = _tidy(result)
    if any(term in _COLOR_TERMS for term in terms):  # 색을 빼서 "an cup" 이 된 경우
        result = re.sub(r"\b([Aa])n(\s+[b-df-hj-np-tv-z])", r"\1\2", result)
    if cut and not unrequested_terms(result, allowed) and _is_sentence(result):
        return result, cut
    return None, []


def _drop_clauses(sentence, allowed):
    """구로 안 되면 지어낸 단어가 든 절(쉼표·and·while 로 나뉜 부분)만 뺀다."""
    parts = re.split(r"\s*(?:,|;|\s[—–-]\s)\s*|\s+(?:and|while|as|then)\s+", sentence.rstrip(".!?"))
    keep = [part for part in parts if part.strip() and not unrequested_terms(part, allowed)]
    cut = [part.strip() for part in parts if part.strip() and unrequested_terms(part, allowed)]
    result = _tidy(", ".join(keep))
    if cut and keep and _is_sentence(result):
        return result, cut
    return None, []


def strip_unrequested(text, allowed):
    """요청에 없는 외모·소품·장소 단어를 뺀다: 그 단어가 든 구 → 절 → 문장 순으로 가장 작게.
    장면의 동작 문장이 모두 사라지게 되면 원문을 두고 표시만 한다."""
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
    kept, notes, whole = [], [], []
    for sentence in sentences:
        terms = [] if sentence.startswith(REFERENCE_APPEARANCE) else unrequested_terms(sentence, allowed)
        if not terms:
            kept.append(sentence)
            continue
        for method in (_drop_phrases, _drop_clauses):
            reduced, cut = method(sentence, allowed)
            if reduced:
                kept.append(reduced)
                notes.append({"terms": terms, "sentence": sentence, "removed": True, "fragment": "; ".join(cut)})
                break
        else:
            whole.append((sentence, terms))
    action = [sentence for sentence in kept if not sentence.startswith(REFERENCE_APPEARANCE)]
    if whole and not action:
        return text, [{"terms": terms, "sentence": sentence, "removed": False} for sentence, terms in whole] + \
            [dict(note, removed=False) for note in notes]
    notes += [{"terms": terms, "sentence": sentence, "removed": True} for sentence, terms in whole]
    return " ".join(kept), notes


def ground_draft(draft, request):
    """새 초안의 요약·장면에서 지어낸 문장을 빼고 무엇을 뺐는지 남긴다."""
    allowed, notes = request_text(request), []
    if any(ord(char) > 127 and char.isalpha() for char in allowed):
        # Literal English matching cannot establish that a Korean/multilingual request omitted an object.
        for where, text in [("요약", draft["f"]["summary"])] + [(f"장면 {i + 1}", shot[1]) for i, shot in enumerate(draft["shots"])]:
            terms = unrequested_terms(text, allowed)
            if terms:
                notes.append({"terms": terms, "sentence": text, "removed": False, "where": where, "language_uncertain": True})
        return notes
    summary, found = strip_unrequested(draft["f"]["summary"], allowed)
    draft["f"]["summary"] = summary
    notes += [dict(note, where="요약") for note in found]
    for index, shot in enumerate(draft["shots"]):
        text, found = strip_unrequested(shot[1], allowed)
        shot[1] = text
        notes += [dict(note, where=f"장면 {index + 1}") for note in found]
    return notes


def flag_edit_terms(draft, request):
    """부분 수정은 원문을 건드리지 않고, 새로 넣은 문구에 지어낸 단어가 있으면 표시만 한다."""
    allowed, notes = request_text(request), []
    for change in draft.get("changes", []):
        terms = unrequested_terms(str(change.get("after", "")), allowed)
        if terms:
            notes.append({"terms": terms, "sentence": str(change.get("after", ""))[:300], "removed": False, "where": "수정 문구",
                          "language_uncertain": any(ord(char) > 127 and char.isalpha() for char in allowed)})
    return notes


def unrequested_issues(notes):
    issues = []
    for note in notes:
        terms = ", ".join(note["terms"])
        if note.get("language_uncertain"):
            issues.append({"severity": "warning", "category": "uncertainty", "at": note["where"], "evidence": note["sentence"][:300],
                           "issue": f"요청과 생성문의 언어가 달라 '{terms}'이(가) 요청에 포함됐는지 자동 확인하지 못했습니다. 문장은 유지했습니다.",
                           "suggestion": "요청한 대상·동작과 일치하는지 확인해 주세요."})
            continue
        issues.append({"severity": "warning", "category": "constraints", "at": note["where"], "evidence": note["sentence"][:300],
                       "issue": (f"요청에 없는 '{terms}' 부분(\"{note['fragment'][:120]}\")을 뺐습니다." if note["removed"] and note.get("fragment")
                                 else f"요청에 없는 '{terms}'을(를) 넣은 문장을 뺐습니다." if note["removed"]
                                 else f"요청에 없는 '{terms}'이(가) 들어 있습니다. 적용 전에 확인해 주세요."),
                       "suggestion": "외모·옷은 사진 1, 장소는 고정 칸을 따릅니다. 꼭 필요하면 요청에 직접 적어 주세요."})
    return issues


def spread_times(shots, duration):
    """장면 시작 시각을 영상 전체에 다시 나눈다(작은 모델은 앞쪽 0~2초에 몰아 넣는 경향: 실측 0/1.2/1.8초).
    몫 = 절반은 균등, 절반은 동작 설명 길이(제곱근으로 완화). 장면마다 최소 0.8초. 순서·문장은 그대로."""
    count = len(shots)
    if count < 2:
        return shots
    def action_words(text):
        return len(text.removeprefix(REFERENCE_APPEARANCE).split())
    weights = [math.sqrt(max(action_words(text), 4)) for _, text in shots]
    total = sum(weights)
    shares = [0.5 / count + 0.5 * weight / total for weight in weights]
    floor = min(0.8, duration / count * 0.6)
    lengths = [max(floor, share * duration) for share in shares]
    scale = duration / sum(lengths)
    lengths = [length * scale for length in lengths]
    start, times = 0.0, []
    for length in lengths:
        times.append(round(start, 1))
        start += length
    for index in range(1, count):  # 반올림 뒤에도 시간순·영상 길이 안
        times[index] = min(max(times[index], times[index - 1] + 0.1), round(duration - 0.1 * (count - index), 1))
    return [[when, text] for when, (_, text) in zip(times, shots)]


def replace_exact(text, before, after):
    if not isinstance(before,str) or not isinstance(after,str):
        raise ValueError("수정 응답 형식이 맞지 않습니다. 원문은 유지했습니다.")
    if not before:
        if text: raise ValueError("수정 위치가 불분명합니다. 원문은 유지했습니다.")
        return after
    if text.count(before)!=1:
        raise ValueError("수정할 원문을 정확히 찾지 못했습니다. 원문은 유지했습니다.")
    return text.replace(before,after,1)


def check_manual_edit(text, updated, fixed):
    if text==updated: return "", ""
    start=0
    while start<min(len(text),len(updated)) and text[start]==updated[start]: start+=1
    stop,new_stop=len(text),len(updated)
    while stop>start and new_stop>start and text[stop-1]==updated[new_stop-1]:
        stop-=1; new_stop-=1
    after=updated[start:new_stop]
    headers=list(SECTION_HEADERS.finditer(text))
    if headers and not any(header.end()<=start and stop<=(headers[i+1].start() if i+1<len(headers) else len(text))
        and header[1] not in ("subject_definitions","retention_analysis") for i,header in enumerate(headers)):
        raise ValueError("고정된 프롬프트 구역은 수정하지 않습니다.")
    if SECTION_HEADERS.search(after): raise ValueError("프롬프트 구역 구성은 그대로 유지합니다.")
    for value in [REFERENCE_APPEARANCE,*fixed.values()]:
        if not value: continue
        for match in re.finditer(re.escape(value),text):
            if start<match.end() and stop>match.start():
                raise ValueError("대상·외관 유지 조건·장소·분위기·카메라는 수정하지 않습니다.")
    return text[start:stop],after


def apply_edits(output, request):
    edits=output.get("edits") if isinstance(output,dict) else None
    if not isinstance(edits,list) or len(edits)>12:
        raise ValueError("수정 응답 형식이 맞지 않습니다. 원문은 유지했습니다.")
    original=request["existing"]
    merged=json.loads(json.dumps(original))
    manual=request.get("manual_prompt")
    changes=[]
    for edit in edits:
        if not isinstance(edit,dict): raise ValueError("수정 응답 형식이 맞지 않습니다.")
        target,index=edit.get("target"),edit.get("index")
        before,after=edit.get("before"),edit.get("after")
        changed_before,changed_after=before,after
        if not isinstance(index,int) or isinstance(index,bool): raise ValueError("수정할 장면 번호가 맞지 않습니다.")
        if manual is not None:
            if target!="prompt" or index!=0: raise ValueError("직접 편집한 최종 프롬프트에서만 부분 수정합니다.")
            updated=replace_exact(manual,before,after)
            changed_before,changed_after=check_manual_edit(manual,updated,request.get("fixed",{}))
            manual=updated
        elif target in FIELDS and index==0:
            value=merged.get(target,"")
            merged[target]=replace_exact(value,before,after)
        elif target in ("shot_text","shot_time") and 0<=index<len(merged.get("shots",[])):
            slot=1 if target=="shot_text" else 0
            value=str(merged["shots"][index][slot])
            updated=replace_exact(value,before,after)
            if target=="shot_time":
                time_value=float(updated)
                if not math.isfinite(time_value) or not 0<=time_value<request["duration"]:
                    raise ValueError("수정할 장면 시각이 영상 길이를 벗어났습니다. 원문은 유지했습니다.")
                if index==0 and time_value!=0:
                    raise ValueError("첫 장면은 0초에 시작해야 합니다. 원문은 유지했습니다.")
            elif REFERENCE_APPEARANCE in value and REFERENCE_APPEARANCE not in updated:
                raise ValueError("사진 1의 외관 유지 조건은 수정하지 않습니다.")
            if updated!=value:
                merged["shots"][index][slot]=updated
        else: raise ValueError("요청한 수정 위치를 찾지 못했습니다. 원문은 유지했습니다.")
        if changed_before!=changed_after: changes.append({"target":target,"index":index,"before":changed_before,"after":changed_after})
    result={"f":{key:merged[key] for key in FIELDS if key in merged and merged[key]!=original.get(key,"")},"edit":True,"changes":changes}
    if manual is not None and manual!=request["manual_prompt"]: result["final"]=manual
    if merged.get("shots")!=original.get("shots"): result["shots"]=merged["shots"]
    return result


def available_memory():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                    *[(key, ctypes.c_ulonglong) for key in ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise RuntimeError("메모리 여유를 확인하지 못했습니다.")
    return status.available


def validate_request(body):
    engine = body.get("engine", "legacy")
    if engine not in ("legacy", "dutchit"):
        raise ValueError("프롬프트 도우미 방식을 확인해 주세요.")
    review_only = body.get("review_only") is True
    idea = body.get("idea") or ("현재 프롬프트의 동작과 시간 흐름을 검토해 주세요." if review_only else "")
    if not isinstance(idea, str) or not idea.strip():
        raise ValueError("만들고 싶은 영상이나 수정 요청을 적어 주세요.")
    if len(idea) > 4000:
        raise ValueError("요청은 4,000자 이내로 적어 주세요.")
    duration = float(body.get("duration") or 5)
    if not math.isfinite(duration) or not 1 <= duration <= 15:
        raise ValueError("영상 길이는 1~15초로 정해 주세요.")
    clean = {"idea": idea.strip(), "duration": duration, "one_take": body.get("one_take") is True, "detail": body.get("detail") is True,
             "mode": "REF2VA" if body.get("mode") == "REF2VA" else "I2VA/FL2VA", "engine": engine}
    count = body.get("reference_count", 1)
    if type(count) is not int or not 1 <= count <= 9:
        raise ValueError("참조 사진 수는 1~9장이어야 합니다.")
    clean["reference_count"] = count
    if "anchor" in body:
        if not isinstance(body["anchor"], bool): raise ValueError("첫 장면 고정 상태를 확인해 주세요.")
        clean["anchor"] = body["anchor"]
    fixed = body.get("fixed")
    if isinstance(fixed, dict):
        clean["fixed"] = {key: value for key, value in fixed.items() if key in FIXED_FIELDS and isinstance(value, str)}
    context = body.get("context")
    if isinstance(context, dict):
        clean["existing"] = {key: value for key, value in context.items() if key in FIELDS and isinstance(value, str)}
        shots = context.get("shots")
        if isinstance(shots, list):
            if len(shots)>6 or any(not isinstance(shot,list) or len(shot)!=2 or not isinstance(shot[0],(str,int,float)) or not isinstance(shot[1],str) for shot in shots):
                raise ValueError("현재 장면 정보를 확인해 주세요. 원문은 유지했습니다.")
            clean["existing"]["shots"] = json.loads(json.dumps(shots))
        if isinstance(body.get("manual_prompt"),str): clean["manual_prompt"]=body["manual_prompt"]
    if review_only:
        if "existing" not in clean or not (clean.get("manual_prompt") or any(clean["existing"].get(key) for key in ("summary","shots"))):
            raise ValueError("검토할 현재 프롬프트를 먼저 작성해 주세요.")
        clean["review_only"] = True
    story=body.get("story_context")
    if isinstance(story,dict):
        index=story.get("clip_index")
        scenarios=story.get("scenarios")
        if type(index) is not int or not 0<=index<4 or not isinstance(scenarios,list) or len(scenarios)!=4 or not all(isinstance(value,str) for value in scenarios):
            raise ValueError("이어 만들기 시나리오 정보를 확인해 주세요.")
        clean["story_context"]={"clip_index":index,"scenarios":scenarios,
            "opening_state":str(story.get("opening_state", "")),"ending_state":str(story.get("ending_state", ""))}
    if len(json.dumps(clean,ensure_ascii=False))>16000:
        raise ValueError("현재 내용이 너무 길어 부분 수정하지 못했습니다. 내용을 줄인 뒤 다시 시도해 주세요.")
    return clean


def validate_draft(draft, duration):
    if not isinstance(draft, dict) or not all(isinstance(draft.get(key), str) for key in FIELDS):
        raise ValueError("도우미 응답 형식이 맞지 않습니다. 다시 작성해 주세요.")
    fields = {key: draft[key].strip()[:2500] for key in FIELDS}
    shots = draft.get("shots")
    if not fields["summary"] or not isinstance(shots, list) or not 1 <= len(shots) <= 6:
        raise ValueError("요약이나 장면이 비어 있습니다. 다시 작성해 주세요.")
    beats = []
    for shot in shots:
        if not isinstance(shot, dict) or not isinstance(shot.get("text"), str) or not shot["text"].strip():
            raise ValueError("장면 설명이 비어 있습니다. 다시 작성해 주세요.")
        start = float(shot["time"])
        if not math.isfinite(start) or not 0 <= start < duration:
            raise ValueError("장면 시각이 영상 길이를 벗어났습니다. 다시 작성해 주세요.")
        beats.append([start, shot["text"].strip()])
    beats.sort(key=lambda beat: beat[0])
    beats[0][0] = 0
    if not beats[0][1].startswith(REFERENCE_APPEARANCE):
        beats[0][1] = REFERENCE_APPEARANCE + " " + beats[0][1]
    return {"f": fields, "shots": beats}


def review_candidate(request, draft):
    content = {key: request[key] for key in ("duration","one_take","fixed","story_context") if key in request}
    content["requested_change"] = request["idea"]
    if "manual_prompt" in request:
        content["candidate"] = {"manual_prompt":draft.get("final",request["manual_prompt"])}
    else:
        candidate = json.loads(json.dumps(request.get("existing", {})))
        candidate.update(draft.get("f", {}))
        if "shots" in draft: candidate["shots"] = draft["shots"]
        content["candidate"] = candidate
        timeline=[]
        for index,shot in enumerate(candidate.get("shots",[])):
            try:
                start=float(shot[0]);end=float(candidate["shots"][index+1][0]) if index+1<len(candidate["shots"]) else request["duration"]
                if math.isfinite(start) and math.isfinite(end): timeline.append({"start":start,"end":end,"available_seconds":round(end-start,3)})
            except (ValueError,TypeError,IndexError): pass
        content["timeline"]=timeline
    return content


def validate_review(output, content):
    if not isinstance(output,dict) or output.get("status") not in ("ok","caution","revise") or not isinstance(output.get("summary"),str) or not isinstance(output.get("issues"),list):
        raise ValueError("동작·시간 검토 응답을 확인하지 못했습니다.")
    def text_values(value):
        if isinstance(value,str): yield value
        elif isinstance(value,dict):
            for part in value.values(): yield from text_values(part)
        elif isinstance(value,list):
            for part in value: yield from text_values(part)
    source=" ".join(" ".join(value.split()) for value in text_values({key:content.get(key) for key in ("candidate","fixed","story_context")}))
    issues=[];unsupported=False
    for item in output["issues"][:3]:
        if not isinstance(item,dict) or item.get("severity") not in ("warning","critical") or item.get("category") not in ("timing","physics","continuity","constraints","uncertainty") or not all(isinstance(item.get(key),str) for key in ("at","evidence","issue","suggestion")):
            raise ValueError("동작·시간 검토 응답을 확인하지 못했습니다.")
        evidence=" ".join(item["evidence"].split())
        evidence=re.sub(r"^(?:candidate|fixed|story_context)(?:\.\w+)?\s*:\s*","",evidence)
        for left,right in (("'","'"),('"','"'),('`','`'),('‘','’'),('“','”')):
            if evidence.startswith(left) and evidence.endswith(right):
                evidence=evidence[1:-1];break
        if not evidence or evidence not in source:
            unsupported=True;continue
        if any(evidence==previous.get("evidence") for previous in issues): continue
        issues.append({**{key:item[key][:600] for key in ("severity","category","at","issue","suggestion")},"evidence":evidence[:600]})
    # Check actual numeric timing independently of the language model's verdict.
    shots=content["candidate"].get("shots",[])
    times=[]
    for shot in shots:
        try: times.append(float(shot[0]))
        except (ValueError,TypeError,IndexError): times.append(float("nan"))
    if times and (times[0]!=0 or any(not math.isfinite(value) or not 0<=value<content["duration"] for value in times) or any(right<=left for left,right in zip(times,times[1:]))):
        issues.insert(0,{"severity":"critical","category":"timing","at":"",
            "issue":"장면 시각이 중복되거나 순서·영상 길이와 맞지 않습니다.",
            "suggestion":"첫 시각을 0초로 두고, 영상 끝 이전에 시간순으로 간격을 배분해 주세요."})
    status="revise" if any(item["severity"]=="critical" for item in issues) else "caution" if issues else "unavailable" if unsupported else output["status"]
    summary=("입력에서 근거를 확인한 항목만 표시했습니다." if issues else "검토 지적의 근거를 원문에서 확인하지 못했습니다. 다시 검토하거나 직접 확인해 주세요.") if unsupported else output["summary"][:900]
    return {"status":status,"summary":summary,"issues":issues[:4]}


def enforce_dutchit_constraints(draft, request):
    """Reject new conflicting action instructions; never migrate or rewrite stored text."""
    if request.get("engine") != "dutchit" or draft.get("review_only"):
        return
    if draft.get("edit"):
        texts = [change["after"] for change in draft.get("changes", []) if change["target"] in ("summary", "shot_text", "prompt")]
    else:
        texts = [draft["f"].get("summary", ""), *[text for _, text in draft.get("shots", [])]]
    camera = re.compile(r"\b(?:the\s+)?camera\s+(?:remains|stays|moves|pushes|pulls|pans|tilts|zooms|tracks|orbits|arcs|rolls|rises|lowers|is\s+(?:fixed|static|locked|stationary))\b|\b(?:zoom\s*(?:in|out)|pan\s+(?:left|right)|close-up\s+shot|wide\s+shot|medium\s+shot)\b", re.I)
    cuts = re.compile(r"\b(?:camera|shot)\s+(?:cuts|transitions|switches|changes)\s+to\b|\bcut\s+to\b|\bfade\s+(?:in|out)\b|\bdissolve\s+to\b", re.I)
    for text in texts:
        action = re.sub(r"<d>.*?</d>", "", text, flags=re.I|re.S)
        if request.get("one_take") and cuts.search(action):
            raise ValueError("원테이크와 충돌하는 컷 전환이 포함되어 적용하지 않았습니다. 동작만 다시 작성해 주세요.")
        if camera.search(action):
            raise ValueError("고정 카메라와 충돌할 수 있는 새 촬영 지시가 포함되어 적용하지 않았습니다. 동작만 다시 작성해 주세요.")
        if any(int(value) > request["reference_count"] for value in re.findall(r"<Picture\s+(\d+)>", action, flags=re.I)):
            raise ValueError("등록한 사진 수를 벗어난 참조가 포함되어 적용하지 않았습니다.")
    if draft.get("edit") and "shots" in draft:
        times = [float(shot[0]) for shot in draft["shots"]]
        if any(a >= b for a,b in zip(times,times[1:])):
            raise ValueError("수정한 장면 시각의 순서가 맞지 않아 원문을 유지했습니다.")


class PromptHelper:
    def __init__(self, home=None):
        self.home = Path(home) if home else Path(__file__).resolve().parents[2] / "local-prompt-helper"
        self.exe = self.home / "runtime" / "llama-server.exe"
        self.model = self.home / "Qwen3.5-2B-Q4_K_M.gguf"
        self.dutchit_model = self.home / DUTCHIT_MODEL
        self.active_engine = "legacy"
        self.lock = threading.Lock()
        self.job = None
        self.cancel_event = threading.Event()

    def start(self, body):
        request = validate_request(body)
        engine = request["engine"]
        model = self.dutchit_model if engine == "dutchit" else self.model
        if not self.exe.is_file() or not model.is_file():
            raise ValueError("도우미 모델 준비가 아직 끝나지 않았습니다.")
        minimum = 8 if engine == "dutchit" else 4
        if available_memory() < minimum * 1024**3:
            raise ValueError(f"영상 작업에 메모리를 남기기 위해 도우미를 시작하지 않았습니다. {'DutchIT 8B는' if engine == 'dutchit' else '기존 도우미는'} RAM 여유가 {minimum}GB 이상일 때 실행할 수 있습니다.")
        with self.lock:
            if self.job and self.job["state"] in ("starting", "generating", "enriching", "reviewing"):
                raise ValueError("도우미가 작성 중입니다. 완료하거나 취소한 뒤 다시 요청해 주세요.")
            self.cancel_event = threading.Event()
            self.job = {"id": uuid.uuid4().hex, "state": "starting", "created": time.time(), "engine":engine, "cpu_only":True}
            result = dict(self.job)
            threading.Thread(target=self._run, args=(request,), daemon=True).start()
        return result

    def status(self, job_id):
        with self.lock:
            if not self.job or self.job["id"] != job_id:
                raise ValueError("도우미 요청을 찾을 수 없습니다.")
            return dict(self.job)

    def cancel(self, job_id):
        with self.lock:
            if not self.job or self.job["id"] != job_id:
                raise ValueError("도우미 요청을 찾을 수 없습니다.")
            self.cancel_event.set()
        return {"ok": True}

    def command(self, port, engine="legacy"):
        model = self.dutchit_model if engine == "dutchit" else self.model
        return [str(self.exe), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
                "--alias", "h3-prompt-helper", "-ngl", "0", "-t", "2", "-tb", "2",
                "-c", "8192", "-np", "1", "-b", "128", "-ub", "128", "--cache-ram", "0",
                "--prio", "-1", "--poll", "0", "--poll-batch", "0", "--threads-http", "2",
                "--jinja", "--reasoning", "off", "--no-webui", "--no-slots", "--log-disable"]

    def _complete(self, base, system, content, schema, tokens, temperature):
        if self.active_engine == "dutchit":
            # Count the actual chat template, including Korean and fixed constraints;
            # reject excess input instead of letting llama.cpp discard its beginning.
            template_request=urllib.request.Request(base+"/apply-template",json.dumps({"messages":[{"role":"system","content":system},{"role":"user","content":json.dumps(content,ensure_ascii=False)}],"add_generation_prompt":True}).encode(),{"Content-Type":"application/json"})
            with urllib.request.urlopen(template_request,timeout=15) as response: formatted=json.load(response)["prompt"]
            token_request=urllib.request.Request(base+"/tokenize",json.dumps({"content":formatted,"add_special":True}).encode(),{"Content-Type":"application/json"})
            with urllib.request.urlopen(token_request,timeout=15) as response: count=len(json.load(response)["tokens"])
            if count+tokens+64>8192: raise ValueError("고정 조건과 현재 내용이 DutchIT의 문맥 한도를 넘었습니다. 원문은 유지했으며 확인할 부분을 나눠 요청해 주세요.")
        payload = {"model":"h3-prompt-helper","messages":[{"role":"system","content":system},
            {"role":"user","content":json.dumps(content,ensure_ascii=False)}],"temperature":temperature,
            "max_tokens":tokens,"stream":False,"response_format":{"type":"json_object","schema":schema}}
        if self.active_engine == "dutchit": payload.update(top_p=.8,top_k=20,cache_prompt=False)
        req=urllib.request.Request(base+"/v1/chat/completions",json.dumps(payload).encode(),{"Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=900 if self.active_engine == "dutchit" else 420) as response: output=json.load(response)
        if output["choices"][0].get("finish_reason")=="length":
            raise ValueError("응답 길이를 초과했습니다. 시나리오를 한 가지 핵심 동작으로 줄여 다시 요청해 주세요.")
        return json.loads(output["choices"][0]["message"]["content"])

    def _run(self, request):
        process = None
        stop_monitor = threading.Event()
        reason = []
        final = {}
        try:
            self.active_engine = request.get("engine", "legacy")
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            env = dict(os.environ, CUDA_VISIBLE_DEVICES="-1", HIP_VISIBLE_DEVICES="-1", OMP_NUM_THREADS="2")
            process = subprocess.Popen(self.command(port, self.active_engine), cwd=self.exe.parent, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS)

            def monitor():
                deadline = time.monotonic() + (900 if self.active_engine == "dutchit" else 420)
                while not stop_monitor.wait(1):
                    if self.cancel_event.is_set():
                        reason.append("작성을 취소했습니다.")
                    elif time.monotonic() > deadline:
                        reason.append("작성·검토 시간이 길어 중지했습니다. 시나리오를 나눠 다시 시도해 주세요.")
                    elif available_memory() < 2.5 * 1024**3:
                        reason.append("영상 작업에 메모리를 남기기 위해 도우미를 중지했습니다.")
                    if reason:
                        if process.poll() is None: process.terminate()
                        return
            threading.Thread(target=monitor, daemon=True).start()
            base = f"http://127.0.0.1:{port}"
            ready = False
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError("CPU 도우미를 실행하지 못했습니다.")
                try:
                    with urllib.request.urlopen(base + "/health", timeout=1) as response:
                        ready = response.status == 200
                except urllib.error.URLError:
                    pass
                if ready: break
                time.sleep(.5)
            if not ready: raise RuntimeError("CPU 도우미 준비 시간이 초과됐습니다.")
            with self.lock: self.job["state"] = "generating"
            editing="existing" in request
            if request.get("review_only"):
                draft={"review_only":True,"f":{}}
            else:
                model_request=dict(request)
                if editing and "manual_prompt" in model_request: model_request.pop("existing")
                schema=json.loads(json.dumps(EDIT_SCHEMA if editing else SCHEMA))
                if editing:
                    schema["properties"]["edits"]["items"]["properties"]["target"]["enum"] = ["prompt"] if "manual_prompt" in request else [*FIELDS,"shot_text","shot_time"]
                system=(EDIT_SYSTEM if editing else SYSTEM)+(STORY_SYSTEM if "story_context" in request else "")
                if self.active_engine == "dutchit":
                    system=DUTCHIT_SYSTEM+"\n"+system.replace("about 60-150 English words", "about 80-240 English words, scaled to the requested action without padding")
                    system=system.replace("Start the requested movement at time 0, rather than\nspending the first phase standing still.", "Respect an opening hold or delayed movement already specified in fixed fields.\nOtherwise start the requested movement at time 0.")
                output=self._complete(base,system,model_request,schema,1600 if editing else 1900,.1 if editing else .2 if self.active_engine == "dutchit" else .25)
                draft=apply_edits(output,request) if editing else validate_draft(output,request["duration"])
                # 상세 보강은 분량을 늘리며 외모·소품을 지어내는 주원인이라 자동으로 하지 않는다(detail=true 일 때만)
                if not editing and request.get("detail") and sum(len(text.split()) for _,text in draft["shots"])<180:
                    with self.lock: self.job["state"]="enriching"
                    keys=[f"beat_{i+1}" for i in range(len(draft["shots"]))]
                    detail_schema={"type":"object","properties":{key:{"type":"string"} for key in keys},"required":keys,"additionalProperties":False}
                    beats={key:{"start":when,"end":draft["shots"][i+1][0] if i+1<len(keys) else request["duration"],
                        "action":text.removeprefix(REFERENCE_APPEARANCE).strip()} for i,(key,(when,text)) in enumerate(zip(keys,draft["shots"]))}
                    try:
                        response=self._complete(base,DETAIL_SYSTEM,{"idea":request["idea"],"duration":request["duration"],"fixed":request.get("fixed",{}),"beats":beats},detail_schema,1900,.2)
                        expanded=[response.get(key) for key in keys] if isinstance(response,dict) else []
                        if len(expanded)!=len(keys) or not all(isinstance(value,str) and len(value.split())>=24 for value in expanded):
                            raise ValueError("상세 보강 응답을 확인하지 못했습니다.")
                        if sum(len(text.split()) for text in expanded)>sum(len(text.split()) for _,text in draft["shots"]):
                            draft["shots"]=[[when,text.strip()] for (when,_),text in zip(draft["shots"],expanded)]
                            if not draft["shots"][0][1].startswith(REFERENCE_APPEARANCE): draft["shots"][0][1]=REFERENCE_APPEARANCE+" "+draft["shots"][0][1]
                    except (OSError,ValueError,KeyError,IndexError,TypeError):
                        if reason or self.cancel_event.is_set(): raise RuntimeError("상세 보강을 중지했습니다.")
                        # A failed optional expansion must not discard an otherwise usable draft.
                        pass
            if self.cancel_event.is_set(): raise RuntimeError("작성을 취소했습니다.")
            enforce_dutchit_constraints(draft, request)
            notes=[]
            if not request.get("review_only"):
                notes=flag_edit_terms(draft,request) if editing else ground_draft(draft,request)
                if notes: draft["unrequested"]=notes
                if not editing: draft["shots"]=spread_times(draft["shots"],request["duration"])
            with self.lock: self.job["state"]="reviewing"
            content=review_candidate(request,draft)
            try:
                model_content=json.loads(json.dumps(content))
                if "shots" in model_content["candidate"]:
                    model_content["candidate"]["shots"]=[{"time":when,"text":text} for when,text in model_content["candidate"]["shots"]]
                review=self._complete(base,REVIEW_SYSTEM,model_content,REVIEW_SCHEMA,1400,.05)
                draft["review"]=validate_review(review,content)
                if notes:
                    draft["review"]["issues"]=unrequested_issues(notes)+draft["review"]["issues"]
                    if draft["review"]["status"] in ("ok","unavailable"): draft["review"]["status"]="caution"
            except (OSError,ValueError,KeyError,IndexError,TypeError):
                if reason or self.cancel_event.is_set(): raise RuntimeError("검토를 중지했습니다.")
                draft["review"]={"status":"unavailable","summary":"동작·시간 검토를 완료하지 못했습니다. 현재 내용 검토 버튼으로 다시 요청해 주세요.","issues":unrequested_issues(notes)}
            if reason or self.cancel_event.is_set(): raise RuntimeError("검토를 중지했습니다.")
            draft["engine"] = self.active_engine
            if self.active_engine == "dutchit": draft["policy_version"] = DUTCHIT_POLICY
            final = {"state":"done","draft":draft}
        except (OSError, ValueError, KeyError, IndexError, TypeError, RuntimeError) as exc:
            message = reason[0] if reason else str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "CPU 도우미가 응답하지 못했습니다. 다시 시도해 주세요."
            final = {"state": "cancelled" if self.cancel_event.is_set() else "error", "error": message}
        finally:
            stop_monitor.set()
            if process and process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            with self.lock: self.job.update(final)
