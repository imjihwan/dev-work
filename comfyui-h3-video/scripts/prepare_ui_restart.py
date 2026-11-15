"""Prepare UI progress metadata only; never mutate the generation queue."""
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
HOME = PROJECT / "ComfyUI/simple_ui"


def read(path):
    with urllib.request.urlopen(path, timeout=8) as response:
        return json.load(response)


story_home = HOME / "story_data"
if story_home.is_dir():
    for state_file in story_home.glob("*/project.json"):
        if json.loads(state_file.read_text(encoding="utf-8")).get("active"):
            raise SystemExit("A UI-owned story operation is still active; no process was stopped.")
history = json.loads((HOME / "history.json").read_text(encoding="utf-8"))
own_ids = {entry["id"] for entry in history}
live = read("http://127.0.0.1:8188/queue")
jobs = [item for item in live["queue_running"] + live["queue_pending"] if item[1] in own_ids]
progress, clients = {}, []
for item in jobs:
    identity, graph, extra = item[1], item[2], item[3]
    status = read("http://127.0.0.1:8190/api/status?id=" + urllib.parse.quote(identity))
    progress[identity] = {"classes": {key: node["class_type"] for key, node in graph.items()},
                          "pct": status.get("pct", 0), "label": status.get("label", "대기")}
    client = extra.get("client_id")
    if client and client not in clients:
        clients.append(client)
destination = HOME / "ui-restart-state.tmp"
assert destination.resolve().is_relative_to(HOME.resolve())
temporary = destination.with_suffix(".writing.tmp")
temporary.write_text(json.dumps({"client_id": clients[-1] if clients else None, "client_ids": clients, "progress": progress}), encoding="utf-8")
os.replace(temporary, destination)
print("Prepared progress metadata; no prompts, photos or result paths were included.")
