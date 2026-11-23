"""Separate four-clip workflow policy. Never modifies the single-video template."""
import copy
import json
import math

CLIP_COUNT = 4
CLIP_SECONDS = 5
OVERLAP_FRAMES = 22
DIRECTOR, GUIDE, GUIDER, SAVE = "2730", "1512:2701", "1512:2592", "2568"


def compose_prompt(common, clip, index, boundaries):
    draft = clip.get("draft") or {}
    fields, shots = draft.get("f") or {}, draft.get("shots") or []
    if not str(fields.get("summary", "")).strip() or not shots:
        raise ValueError("각 편의 프롬프트를 작성하고 적용해 주세요.")
    detail = []
    for position, shot in enumerate(shots):
        if not isinstance(shot,list) or len(shot)!=2 or not isinstance(shot[1],str):
            raise ValueError("장면 설명을 확인해 주세요.")
        when = float(shot[0] or 0)
        if not math.isfinite(when) or not 0 <= when < CLIP_SECONDS:
            raise ValueError("장면 시각은 5초보다 앞이어야 합니다.")
        if shot[1].strip():
            window_time=when+(OVERLAP_FRAMES/24 if index else 0)
            prefix=("After the hidden overlap, " if index and not position else "")
            detail.append(prefix+(f"At {window_time:.3f} seconds, " if position or index else "")+shot[1])
    if not detail: raise ValueError("장면별 동작을 작성해 주세요.")
    identity = ("<Picture 1> is the original appearance reference for all four clips. "
        "Preserve the subject's identity, face, hairstyle, body and outfit from it. "
        "It is not a request to reset the opening pose or repeat a previous action.")
    if common.get("reference_count",1)>1:
        identity += " Other reference pictures supply facial identity only. Do not copy their clothing, pose, background, lighting, text or logos."
    seam = ("Begin from the preceding video's actual ending: preserve positions, pose, "
        "motion direction, camera, lighting, environment and sound at the seam. "
        "Continue forward without restarting or repeating the preceding action.") if index else "Begin from the original reference picture."
    boundary = []
    if boundaries[index].strip(): boundary.append("Opening state: " + boundaries[index])
    if boundaries[index+1].strip(): boundary.append("Ending state: " + boundaries[index+1])
    return "\n\n".join([
        "subject_definitions: " + identity + " " + common.get("subject", ""),
        "summary: " + ("[video continuation + reference generation] " if index else "[keyframe completion + reference generation] ") + fields["summary"],
        "retention_analysis: " + common.get("keep", "") + " " + seam,
        "detailed_description: " + " ".join([common.get("style", ""), "[Shot 1]", *boundary, *detail]),
        "overall_soundscape: " + fields.get("sound", ""),
        "non_diegetic_music: " + fields.get("music", "N/A")])


def continuation_graph(prepared, session, index, parent, prompt):
    graph = copy.deepcopy(prepared)
    required = {"DaSiWaH3ContinuitySegmentPrepare", "DaSiWaH3ContinuitySegmentDecode", "DaSiWaH3ContinuityPublish"}
    if not required.issubset({node["class_type"] for node in graph.values()}):
        raise ValueError("이 환경의 별도 이어 생성 워크플로 구성을 확인해야 합니다.")
    # 업스케일 화질은 이어 붙는 편에서 검증하지 않았다(각 편의 크기와 이어받는 잠재의 크기가 달라진다)
    if any(node["class_type"] == "DaSiWaH3TiledUpscale" for node in graph.values()):
        raise ValueError("이어 만들기에서는 업스케일 화질을 쓸 수 없습니다. 화질을 바꿔 주세요.")
    director = graph[DIRECTOR]["inputs"]
    timeline = json.loads(director["timeline_data"])
    # Preserve original reference images; only the AV tail sets later opening states.
    timeline["continuity"] = {"version":3,"capture":True,"session":session,
        "source_kind":"checkpoint","source_id":parent or "","source_video_id":"",
        "use_references":True,"output_mode":"segment","overlap_frames":OVERLAP_FRAMES,
        "duration_seconds":CLIP_SECONDS,"continuation_prompt":prompt,"idea":""}
    timeline["refmods"] = []
    timeline["prompt_blocks"] = []
    director.update(mode="REF2VA", duration=CLIP_SECONDS, frame_rate=24,
        prompt=prompt,external_prompt_overwrite=prompt,timeline_data=json.dumps(timeline,ensure_ascii=False))
    exporter=graph[SAVE]["inputs"]
    exporter.update(frame_rate=24,pingpong=False,crop_to_audio=False,save_metadata=False,save_output=True,
        save_first_frame=False,save_last_frame=False,filename_prefix=f"story/{session}/part-{index+1}")
    if index and graph[GUIDER]["inputs"].get("conditioning") != [GUIDE,0]:
        raise ValueError("후속 영상에는 원본 사진의 첫 장면 고정을 중복 적용할 수 없습니다.")
    return graph
