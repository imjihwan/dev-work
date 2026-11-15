"""Prepend the approved opening action; emit counts only and never read media."""
import argparse
import copy
import json
import re

from scripts import apply_queued_style as helper


STYLE_FILE = helper.PROJECT / "logs/queue-style-waist45-anchored-motion.txt"
PREFIX_FILE = helper.PROJECT / "logs/queue-zero-second-waist45.txt"


def literal_pattern(text):
    return r"\s+".join(re.escape(part) for part in text.split())


def prepend_action(text, prefix):
    if re.match(r"\s*" + literal_pattern(prefix), text):
        return text
    return prefix + ("\n\n" + text if text else "")


def prepend_prompt(text, style, prefix):
    section = re.search(r"(?m)^detailed_description:[ \t]*", text)
    if section is None:
        raise helper.StyleMismatch("missing_description")
    following = re.search(r"(?m)^(?:" + helper.SECTIONS + r"):", text[section.end():])
    end = section.end() + following.start() if following else len(text)
    body = text[section.end():end]
    common = re.match(literal_pattern(style), body)
    if common is None:
        raise helper.StyleMismatch("custom_description_prefix")
    tail = body[common.end():]
    if not tail.strip():
        changed = body[:common.end()] + " " + prefix + tail
    else:
        start = common.end() + len(tail) - len(tail.lstrip())
        marker = re.match(r"\[Shot 1\][ \t]*", body[start:])
        if marker:
            start += marker.end()
        if re.match(r"\s*" + literal_pattern(prefix), body[start:]):
            return text
        changed = body[:start] + prefix + "\n\n" + body[start:]
    return text[:section.end()] + changed + text[end:]


def prepare_opening(entry, item, style, env, prefix=None):
    prefix = prefix or PREFIX_FILE.read_text(encoding="utf-8-sig").strip()
    if entry.get("mode") != "REF2VA" or entry.get("anchor") is not True:
        raise helper.StyleMismatch("not_anchored_reference")
    ui = entry.get("ui") or {}
    if ui.get("f", {}).get("style") != style:
        raise helper.StyleMismatch("different_common_style")
    shots = ui.get("shots")
    if (not isinstance(shots, list) or not shots or not isinstance(shots[0], list)
            or len(shots[0]) != 2 or not isinstance(shots[0][1], str)
            or float(shots[0][0] or 0) != 0):
        raise helper.StyleMismatch("missing_zero_second_action")
    new_shots = copy.deepcopy(shots)
    new_shots[0][1] = prepend_action(shots[0][1], prefix)
    text = prepend_prompt(entry["prompt"], style, prefix)
    expected = helper.patch_graph(item[2], env["DIRECTOR"], entry["prompt"], text)
    env["object_options"] = lambda kind, field: [entry["model"]] if kind == "UNETLoader" else [lora["name"] for lora in entry.get("loras", [])]
    values = dict(entry, prompt=text, count=1, photo_sequence=False, edit_id=None)
    candidate = env["build_and_queue"](values, reference={"entry": entry, "prompt": item[2]}, prepare_only=True)["prompt"]
    if helper.semantic_graph(candidate) != helper.semantic_graph(expected):
        raise helper.StyleMismatch("other_graph_settings_would_change")
    incoming = {"f": {}, "shots": new_shots}
    if "final" in ui:
        incoming["final"] = text if isinstance(ui["final"], str) else None
    return {"edit_ids": [entry["id"]], "bulk_fields": ["content"], "prompt": text, "ui": incoming}, expected


def run(apply=False):
    style = STYLE_FILE.read_text(encoding="utf-8-sig").strip()
    prefix = PREFIX_FILE.read_text(encoding="utf-8-sig").strip()
    before = helper.entries()
    queue = helper.request("http://127.0.0.1:8188/queue")
    running = {item[1]: item for item in queue["queue_running"]}
    def prepare(entry, item, replacement, env):
        return prepare_opening(entry, item, replacement, env, prefix)
    counts = helper.run(style, apply=apply, expected_style=style, prepare_fn=prepare)
    print(json.dumps({"application": counts}), flush=True)
    if not apply:
        return not any(counts[key] for key in ("unmatched", "failed", "different_style"))
    saved = helper.entries()
    live = helper.request("http://127.0.0.1:8188/queue")
    env = helper.dry_builder(helper.HOME)
    audit = {"pending_owned": 0, "opening_and_graph_match": 0, "common_style_unchanged": 0,
             "other_text_and_settings_preserved": 0, "anchor_preserved": 0,
             "original_running_active": 0, "original_running_unchanged": 0, "unmatched": 0}
    keys = ("seed", "mode", "model", "steps", "sampler", "scheduler", "shift_video", "shift_audio",
            "loras", "aspect", "resolution", "duration", "width", "height", "anchor", "images", "sequence_index")
    for item in live["queue_pending"]:
        entry = saved.get(item[1])
        if entry is None:
            continue
        audit["pending_owned"] += 1
        old = before.get(item[1])
        try:
            body, expected = prepare(entry, item, style, env)
            audit["opening_and_graph_match"] += (body["prompt"] == entry["prompt"] and body["ui"]["shots"] == entry["ui"]["shots"]
                and helper.semantic_graph(expected) == helper.semantic_graph(item[2]))
            if old is not None:
                audit["common_style_unchanged"] += entry["ui"]["f"] == old["ui"]["f"]
                expected_ui = copy.deepcopy(old["ui"])
                expected_ui["shots"][0][1] = prepend_action(old["ui"]["shots"][0][1], prefix)
                expected_prompt = prepend_prompt(old["prompt"], style, prefix)
                if isinstance(expected_ui.get("final"), str):
                    expected_ui["final"] = expected_prompt
                audit["other_text_and_settings_preserved"] += (entry["ui"] == expected_ui and entry["prompt"] == expected_prompt
                    and all(entry.get(key) == old.get(key) for key in keys))
                audit["anchor_preserved"] += old.get("anchor") is True and entry.get("anchor") is True
        except (ValueError, KeyError, TypeError):
            audit["unmatched"] += 1
    for item in live["queue_running"]:
        if item[1] in running:
            audit["original_running_active"] += 1
            audit["original_running_unchanged"] += item == running[item[1]]
    print(json.dumps({"verification": audit}), flush=True)
    return (not any(counts[key] for key in ("unmatched", "failed", "different_style", "changed_before_update"))
        and not audit["unmatched"] and all(audit[key] == audit["pending_owned"] for key in
            ("opening_and_graph_match", "common_style_unchanged", "other_text_and_settings_preserved", "anchor_preserved"))
        and audit["original_running_active"] == audit["original_running_unchanged"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        ok = run(args.apply)
    except Exception:
        print(json.dumps({"error": "stopped_without_exposing_private_data"}))
        ok = False
    raise SystemExit(0 if ok else 1)
