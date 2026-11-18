"""Copy an explicit source allowlist; never enumerate runtime or media directories."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    ".gitignore", "AGENTS.md", "README.md", "CHANGELOG.md", "TODO.md",
    "models.json", "versions.json", "requirements-test.txt",
    "Start-H3-Video.ps1", "Stop-H3-Video.ps1", "Restart-H3-UI.ps1", "Complete-Models.ps1", "Connect-Grok.ps1",
)
UI_FILES = (
    "server.py", "index.html", "start.bat", "template_api.json",
    "cards.seed.json", "presets.seed.json", "prompt_helper.py", "grok_cli.py", "production_assistant.py", "production_assistant.js", "local_translate.py", "translation_worker.py",
    "story.py", "story_workflow.py", "story.html", "gallery.py", "gallery.html", "face_references.py",
)
THIRD_PARTY_FILES = ("third_party/dutchit/NOTICE.md", "third_party/dutchit/LICENSE.txt", "third_party/dutchit/Modelfile.ref.txt")
DOC_FILES = (
    "MODELS.md", "PROMPT_HELPER.md", "GROK_CLI.md", "PRODUCTION_ASSISTANT.md", "STORY.md", "UI.md",
    "ARCHITECTURE.md", "TESTING.md", "SOURCE_RELEASE.md", "FACE_REFERENCES.md", "LOCAL_TRANSLATION.md",
)
SCRIPT_FILES = (
    "setup.ps1", "start_comfyui.bat", "get_models.py", "download-ranges.py",
    "install_prompt_helper.py", "install_grok_cli.py", "install_face_detector.py", "install_local_translator.py", "test_face_references.py", "prepare_ui_restart.py", "prepare_source_release.py", "restart_backend.py", "test_backend_restart.py",
    "apply_queued_style.py", "add_queued_opening_pose.py", "restore_anchored_reference.py",
    "test_gallery.py", "test_apply_queued_style.py", "test_add_queued_opening_pose.py",
    "test_prompt_helper.py", "test_grok_cli.py", "test_action_editor.cjs", "test_production_assistant.py", "test_production_assistant.cjs", "test_local_translate.py", "test_translation_preview.cjs", "test_photo_batch_ui.cjs", "test_folder_photos.cjs", "test_opening_pose.cjs",
    "test_input_thumbnail.py", "test_history_ui.cjs", "test_history_media.cjs",
    "test_history_delete.py", "test_gallery_ui.cjs", "test_gallery_thumbnails.cjs", "test_gallery_navigation.cjs", "test_gallery_regenerate.py",
    "test_gallery_progress.py", "test_settings_sequence_bulk.py",
    "test_restore_anchored_reference.py", "test_restart_running.py",
    "test_reference_restore.cjs", "test_queue_edit.py", "test_prompt_sync.cjs", "test_priority_queue.py",
    "test_ui_features.cjs", "test_story_ui.cjs", "test_story_routes.py", "test_story.py", "test_reference_images.cjs", "test_playback_preferences.cjs",
)
PUBLIC_FILES = tuple(ROOT_FILES) + THIRD_PARTY_FILES + tuple("simple_ui/"+name for name in UI_FILES) + tuple(
    "docs/"+name for name in DOC_FILES) + tuple("scripts/"+name for name in SCRIPT_FILES)
ALLOWED_SUFFIXES = {".md", ".py", ".js", ".cjs", ".html", ".ps1", ".bat", ".json", ".txt"}
SECRET = re.compile(r"(?:xai-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)")


def prepare(destination):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Release destination already exists; choose a new directory.")
    if destination == ROOT or ROOT.is_relative_to(destination) or destination.is_relative_to(ROOT / "ComfyUI"):
        raise ValueError("Release destination must be separate from the source and installed runtime.")
    payload = {}
    for relative in PUBLIC_FILES:
        path = ROOT / relative
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("A source allowlist path resolves outside this project.")
        if path.name != ".gitignore" and path.suffix not in ALLOWED_SUFFIXES:
            raise ValueError("Unexpected file extension in source allowlist.")
        data = path.read_bytes()
        if len(data) > 2_000_000 or SECRET.search(data.decode("utf-8-sig")):
            raise ValueError("Source release failed its size or credential check.")
        payload[relative] = data
    template = json.loads(payload["simple_ui/template_api.json"].decode("utf-8-sig"))
    directors = [node for node in template.values() if node.get("class_type") == "MiniMaxH3Director"]
    if not directors:
        raise ValueError("Expected a Director in the public template.")
    for node in directors:
        inputs = node.get("inputs", {})
        if inputs.get("prompt", "").strip() or json.loads(inputs["timeline_data"]).get("items"):
            raise ValueError("Public template must have no prompt or reference-image items.")
    manifest = []
    for relative, data in payload.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest_path = destination.parent / (destination.name + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"source_files": len(manifest), "bytes": sum(item["bytes"] for item in manifest),
                      "template_prompt_empty": True, "template_references_empty": True,
                      "runtime_or_media_directories_read": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "logs/source-release/comfyui-h3-video")
    args = parser.parse_args()
    prepare(args.destination)
