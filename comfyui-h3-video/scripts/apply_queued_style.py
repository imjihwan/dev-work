"""Replace only saved style text in pending UI jobs. Print counts, never task data."""
import argparse
import ast
import copy
import json
import os
from pathlib import Path
import random
import re
import urllib.error
import urllib.request
import uuid


PROJECT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("QUEUE_STYLE_HOME", PROJECT / "ComfyUI/simple_ui"))
SECTIONS = "subject_definitions|summary|retention_analysis|detailed_description|integrated_multimodal_description|overall_soundscape|non_diegetic_music"
LEGACY_ONE_TAKE_KEEP = "One continuous take: the background, camera position and framing stay exactly the same as in <Picture 1> for the whole video, with no cuts, no scene changes and no new locations."
PREVIOUS_ONE_TAKE_KEEP = "One continuous take: keep the camera viewpoint, position and framing established at the start of this video stable throughout the shot, with no cuts, no scene changes and no new locations. Preserve the same environment as <Picture 1>, allowing its perspective and occlusion to match the chosen viewpoint."
REFERENCE_BACKGROUND = "Create a new, coherent background with a similar atmosphere, setting character, palette and lighting mood to <Picture 1>, without copying its exact layout, furniture placement or perspective. Keep this newly established environment consistent throughout the video."
REFERENCE_SUBJECT_APPEARANCE = "<Subject 1> is the person from <Picture 1>. Preserve this person's identity, face, hairstyle, body shape, outfit and existing accessories. Use <Picture 1> as an appearance reference; follow the described pose and background instead of copying the source composition."
REFERENCE_SUBJECT_OLD_SINGLE = "<Picture 1> shows the main subject. Copy the face, hairstyle, outfit and background from <Picture 1>."
REFERENCE_SUBJECT_OLD_MULTI = "<Picture 1> is the main reference for the whole video: copy the face, hairstyle, outfit, body shape and background from <Picture 1>, and the video starts in the scene of <Picture 1>."
REFERENCE_POSE_SCOPE = "Reference preservation applies to the person's appearance, head direction and upper-body orientation. Replace the reference pelvis and leg facing direction with the approximately 45-degree lower-body orientation described below. Establish new foot positions appropriate to that opening pose, then keep that pose through the final frame. Appearance preservation must not restore the original lower-body direction."


def refresh_reference_subject(text):
    start = len(text) - len(text.lstrip())
    for previous in (REFERENCE_SUBJECT_OLD_SINGLE, REFERENCE_SUBJECT_OLD_MULTI):
        pattern = r"\s+".join(re.escape(part) for part in previous.split())
        match = re.match(pattern, text[start:])
        if match:
            return text[:start] + REFERENCE_SUBJECT_APPEARANCE + text[start + match.end():]
    return text


def refresh_reference_roles(text):
    """Only replace known auto-generated subject text and append an explicit pose exception."""
    if not all(re.search(r"(?m)^" + section + r":", text) for section in ("subject_definitions", "retention_analysis")):
        raise StyleMismatch("missing_reference_sections")
    section_end = r"(?=\n(?:" + SECTIONS + r"):|\Z)"
    text = re.sub(r"(^subject_definitions:[ \t]*)([\s\S]*?)" + section_end,
                  lambda match: match[1] + refresh_reference_subject(match[2]), text, count=1, flags=re.M)
    def retention(match):
        body = match[2]
        if REFERENCE_POSE_SCOPE in body:
            return match[0]
        stripped = body.rstrip()
        return match[1] + stripped + " " + REFERENCE_POSE_SCOPE + body[len(stripped):]
    return re.sub(r"(^retention_analysis:[ \t]*)([\s\S]*?)" + section_end, retention, text, count=1, flags=re.M)


def refresh_reference_background(keep):
    """Modify only reference-background retention clauses, without exposing their text."""
    if keep.rstrip().endswith(REFERENCE_BACKGROUND):
        return keep
    text = keep
    # Remove the background from a combined appearance list, leaving every person detail intact.
    text = re.sub(r"(?i)(?:,?\s+and|,)\s+(?:the\s+)?(?:original\s+)?background(?=\s+(?:exactly|as\b|from\b|unchanged)|[,.])", "", text)
    # Standalone environment instructions are authorized to change; never drop a person instruction.
    pieces = re.split(r"(?<=[.!?])(?=\s|$)|\n+", text)
    changed = text != keep
    for i, sentence in enumerate(pieces):
        if (re.search(r"\b(?:background|environment)\b|배경", sentence, re.I)
                and not re.search(r"\b(?:person|face|head|hair|body|outfit|cloth\w*|accessor\w*|skin|hand|arm|leg|hip|knee|foot|feet|pose)\b", sentence, re.I)
                and re.search(r"\b(?:keep|preserve|maintain|retain|same|unchanged|original|reference|match|consistent)\b|유지|원본|동일", sentence, re.I)):
            pieces[i] = ""
            changed = True
    if not changed:
        return keep
    return " ".join(piece.strip() for piece in pieces if piece.strip()).rstrip() + " " + REFERENCE_BACKGROUND


class StyleMismatch(ValueError):
    pass


def one_take_rule(home):
    page = (home / "index.html").read_text(encoding="utf-8-sig")
    match = re.search(r'^const ONE_TAKE_KEEP = ("(?:\\.|[^"\\])*");$', page, re.M)
    if match is None:
        raise StyleMismatch("missing_common_rule")
    return json.loads(match[1])


def refresh_common_rule(text, entry, replacement):
    ui = entry.get("ui") or {}
    keep = str((ui.get("f") or {}).get("keep") or "").strip()
    if entry.get("mode") != "REF2VA" or ui.get("oneTake") is False or re.search("no cuts", keep, re.I):
        return text
    # Replace only the known generated suffix; saved user retention instructions stay intact.
    section = re.search(r"(?m)^retention_analysis:[ \t]*", text)
    if section is None:
        return text
    following = re.search(r"(?m)^(?:" + SECTIONS + r"):", text[section.end():])
    end = section.end() + following.start() if following else len(text)
    body = text[section.end():end]
    generated = body.rstrip()
    previous = next((rule for rule in (LEGACY_ONE_TAKE_KEEP, PREVIOUS_ONE_TAKE_KEEP) if generated.endswith(rule)), None)
    if previous is None:
        return text
    start = section.end() + len(generated) - len(previous)
    stop = section.end() + len(generated)
    return text[:start] + replacement + text[stop:]


def replace_style(text, previous, replacement):
    section = re.search(r"(?m)^[ \t]*(detailed_description|integrated_multimodal_description):[ \t]*", text)
    if not section:
        raise StyleMismatch("missing_description")
    following = re.search(r"(?m)^[ \t]*(?:" + SECTIONS + r"):", text[section.end():])
    end = section.end() + following.start() if following else len(text)
    body = text[section.end():end]
    if previous.strip():
        pattern = r"\s+".join(re.escape(part) for part in previous.split())
        matches = list(re.finditer(pattern, body))
        first = re.match(pattern, body)
        match = first or (matches[0] if len(matches) == 1 else None)
        if match is None:
            raise StyleMismatch("ambiguous_style")
        start, stop = section.end() + match.start(), section.end() + match.end()
        return text[:start] + replacement + text[stop:]
    return text[:section.end()] + replacement + " " + text[section.end():]


def patch_graph(graph, director, previous, replacement):
    result = copy.deepcopy(graph)
    inputs = result[director]["inputs"]
    timeline = json.loads(inputs["timeline_data"])
    builder = json.loads(inputs["builder_state"])
    slots = [(inputs, "prompt"), (timeline, "resolved_prompt"),
             (timeline["builder_state"], "simple_prompt"), (timeline["continuity"], "continuation_prompt"),
             (builder, "simple_prompt")]
    if any(owner.get(key) != previous for owner, key in slots):
        raise StyleMismatch("inconsistent_prompt_copies")
    for owner, key in slots:
        owner[key] = replacement
    inputs["timeline_data"] = json.dumps(timeline, ensure_ascii=False)
    inputs["builder_state"] = json.dumps(builder, ensure_ascii=False)
    return result


def semantic_graph(graph):
    result = copy.deepcopy(graph)
    for node in result.values():
        for key in ("timeline_data", "builder_state", "stack_data"):
            value = node.get("inputs", {}).get(key)
            if isinstance(value, str):
                node["inputs"][key] = json.loads(value)
    return result


def dry_builder(home):
    tree = ast.parse((home / "server.py").read_text(encoding="utf-8-sig"))
    wanted = {"DIRECTOR", "SEED", "SAVE", "LOADERS", "SCHED", "SAMPLER", "SHIFT", "LORA", "GUIDE", "GUIDER", "VIDEO_VAE", "ANCHOR_IMG", "ANCHOR", "LORA_SLOTS", "MULT", "RES_MP"}
    env = {"json": json, "os": os, "random": random, "uuid": uuid, "TEMPLATE": str(home / "template_api.json"),
           "card_for": lambda kind, name: {"auto": {}}}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in wanted:
                env[target.id] = ast.literal_eval(node.value)
            elif isinstance(target, ast.Tuple) and all(isinstance(part, ast.Name) and part.id in wanted for part in target.elts):
                env.update(zip((part.id for part in target.elts), ast.literal_eval(node.value)))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ("snap", "canvas", "add_anchor", "build_and_queue")]
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<queue-style-dry-builder>", "exec"), env)
    return env


def prepare(entry, item, style, env, common_rule=None, disable_anchor=False, new_background=False, reference_role=False):
    old_style = entry.get("ui", {}).get("f", {}).get("style")
    old_prompt = entry.get("prompt")
    if not isinstance(old_style, str) or not isinstance(old_prompt, str):
        raise StyleMismatch("missing_saved_fields")
    text = replace_style(old_prompt, old_style, style)
    if common_rule is not None:
        text = refresh_common_rule(text, entry, common_rule)
    incoming = {"f": {"style": style}}
    if reference_role:
        if entry.get("mode") != "REF2VA":
            raise StyleMismatch("non_reference_mode")
        text = refresh_reference_roles(text)
        subject = (entry.get("ui", {}).get("f") or {}).get("subject")
        if isinstance(subject, str):
            changed_subject = refresh_reference_subject(subject)
            if changed_subject != subject:
                incoming["f"]["subject"] = changed_subject
    if new_background:
        keep = str((entry.get("ui", {}).get("f") or {}).get("keep") or "")
        changed_keep = refresh_reference_background(keep)
        if changed_keep != keep:
            section = re.search(r"(?m)^retention_analysis:[ \t]*", text)
            following = re.search(r"(?m)^(?:" + SECTIONS + r"):", text[section.end():]) if section else None
            end = section.end() + following.start() if following else len(text)
            if section is None or not keep.strip():
                raise StyleMismatch("missing_retention")
            pattern = r"\s+".join(re.escape(part) for part in keep.split())
            found = re.match(pattern, text[section.end():end])
            if found is None:
                raise StyleMismatch("retention_has_manual_edits")
            text = text[:section.end()] + changed_keep + text[section.end() + found.end():]
            incoming["f"]["keep"] = changed_keep
    expected = patch_graph(item[2], env["DIRECTOR"], old_prompt, text)
    values = dict(entry, prompt=text, count=1, photo_sequence=False, edit_id=None)
    if disable_anchor:
        if entry.get("mode") != "REF2VA":
            raise StyleMismatch("non_reference_mode")
        values["anchor"] = False
        anchor, image, guider, guide = (env[key] for key in ("ANCHOR", "ANCHOR_IMG", "GUIDER", "GUIDE"))
        if entry.get("anchor"):
            if (expected[anchor] != {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": [guide, 0], "latent": [guide, 1], "vae": [env["VIDEO_VAE"], 0], "image": [image, 0], "frame_idx": 0}}
                    or expected[image] != {"class_type": "LoadImage", "inputs": {"image": entry["images"][0]}}
                    or expected[guider]["inputs"]["conditioning"] != [anchor, 0]):
                raise StyleMismatch("custom_anchor_graph")
            del expected[anchor], expected[image]
            expected[guider]["inputs"]["conditioning"] = [guide, 0]
    env["object_options"] = lambda kind, field: [entry["model"]] if kind == "UNETLoader" else [lora["name"] for lora in entry.get("loras", [])]
    candidate = env["build_and_queue"](values, reference={"entry": entry, "prompt": item[2]}, prepare_only=True)["prompt"]
    if semantic_graph(candidate) != semantic_graph(expected):
        raise StyleMismatch("other_graph_settings_would_change")
    if "final" in entry.get("ui", {}):
        incoming["final"] = text if isinstance(entry["ui"]["final"], str) else None
    body = {"edit_ids": [entry["id"]], "bulk_fields": ["content"], "prompt": text, "ui": incoming}
    if disable_anchor:
        body.update(bulk_fields=["content", "anchor"], anchor=False)
    return body, expected


def request(url, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"} if data is not None else {})
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def entries():
    return {entry["id"]: entry for entry in json.loads((HOME / "history.json").read_text(encoding="utf-8"))}


def run(style, apply=False, refresh_common=False, expected_style=None, disable_anchor=False, new_background=False, reference_role=False, prepare_fn=None):
    source = Path(os.environ.get("QUEUE_STYLE_SOURCE", HOME))
    env = dry_builder(source)
    common_rule = one_take_rule(source) if refresh_common else None
    history = entries()
    queue = request("http://127.0.0.1:8188/queue")
    targets = [item for item in sorted(queue["queue_pending"], key=lambda item: item[0]) if item[1] in history]
    counts = {"pending_targets": len(targets), "prepared": 0, "already_current": 0, "different_style": 0, "unmatched": 0,
              "changed_before_update": 0, "started_or_removed": 0, "updated": 0, "verified": 0, "failed": 0}
    prepared = []
    for item in targets:
        entry = history[item[1]]
        if expected_style is not None and (entry.get("ui") or {}).get("f", {}).get("style") not in (expected_style, style):
            counts["different_style"] += 1
            continue
        try:
            body, expected = prepare_fn(entry, item, style, env) if prepare_fn else prepare(entry, item, style, env, common_rule, disable_anchor, new_background, reference_role)
            if (body["prompt"] == entry["prompt"] and entry.get("anchor") == body.get("anchor", entry.get("anchor"))
                    and all(entry.get("ui", {}).get("f", {}).get(key) == value for key, value in body["ui"]["f"].items())
                    and all(entry.get("ui", {}).get(key) == value for key, value in body["ui"].items() if key != "f")):
                counts["already_current"] += 1
                continue
            prepared.append((item, entry, body, expected))
            counts["prepared"] += 1
        except (StyleMismatch, KeyError, ValueError, TypeError):
            counts["unmatched"] += 1
    if not apply or not prepared:
        return counts
    backup_root = HOME / "queue-style-backups"
    backup_root.mkdir(exist_ok=True)
    backup = backup_root / (uuid.uuid4().hex + ".json")
    backup.write_text(json.dumps({"entries": [{"queue": item, "history": entry} for item, entry, _, _ in prepared]}, ensure_ascii=False), encoding="utf-8")
    for item, entry, body, expected in prepared:
        try:
            live = request("http://127.0.0.1:8188/queue")
            pending = next((value for value in live["queue_pending"] if value[1] == item[1]), None)
            if pending is None:
                counts["started_or_removed"] += 1
                continue
            if pending != item or entries().get(item[1]) != entry:
                counts["changed_before_update"] += 1
                continue
            response = request("http://127.0.0.1:8190/api/queue/bulk-edit", body)
            if not response.get("jobs"):
                latest = request("http://127.0.0.1:8188/queue")
                if any(value[1] == item[1] for value in latest["queue_pending"]):
                    counts["failed"] += 1
                    break
                counts["started_or_removed"] += 1
                continue
            counts["updated"] += 1
            current = entries().get(item[1])
            preserved = copy.deepcopy(entry)
            preserved["prompt"] = body["prompt"]
            preserved["ui"]["f"].update(body["ui"]["f"])
            if "anchor" in body.get("bulk_fields", []):
                preserved["anchor"] = body["anchor"]
            for key, value in body["ui"].items():
                if key != "f":
                    preserved["ui"][key] = copy.deepcopy(value)
            # Queue edits refresh bookkeeping, while these generation values must match.
            keys = ("prompt", "ui", "seed", "mode", "model", "steps", "sampler", "scheduler", "shift_video", "shift_audio", "loras", "aspect", "resolution", "duration", "width", "height", "anchor", "images", "sequence_index")
            if current is None or any(current.get(key) != preserved.get(key) for key in keys):
                raise StyleMismatch("history_verification_failed")
            live = request("http://127.0.0.1:8188/queue")
            active = next((value for value in live["queue_pending"] + live["queue_running"] if value[1] == item[1]), None)
            if active is not None and (active[0] != item[0] or semantic_graph(active[2]) != semantic_graph(expected)):
                raise StyleMismatch("queue_verification_failed")
            counts["verified"] += 1
            if counts["verified"] % 25 == 0:
                print(json.dumps({"updated": counts["updated"], "verified": counts["verified"]}), flush=True)
        except (OSError, ValueError, KeyError, TypeError):
            counts["failed"] += 1
            # Do not retry a request whose outcome could be ambiguous.
            break
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("style_file", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--refresh-common-rule", action="store_true")
    parser.add_argument("--expected-style-file", type=Path)
    parser.add_argument("--disable-anchor", action="store_true")
    parser.add_argument("--new-background", action="store_true")
    parser.add_argument("--refresh-reference-role", action="store_true")
    args = parser.parse_args()
    try:
        replacement = args.style_file.read_text(encoding="utf-8-sig").strip()
        if not replacement:
            raise ValueError()
        expected_style = args.expected_style_file.read_text(encoding="utf-8-sig").strip() if args.expected_style_file else None
        print(json.dumps(run(replacement, args.apply, args.refresh_common_rule, expected_style, args.disable_anchor, args.new_background, args.refresh_reference_role)))
    except Exception:
        print(json.dumps({"error": "operation_stopped_without_exposing_private_data"}))
        raise SystemExit(1)
