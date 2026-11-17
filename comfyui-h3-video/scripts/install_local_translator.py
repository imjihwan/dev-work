"""Install a separate CPU-only English/Korean runtime; no ComfyUI dependency changes."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def download(spec, destination):
    destination = destination.resolve()
    target = (destination / spec["path"]).resolve()
    if not target.is_relative_to(destination):
        raise ValueError("Unsafe translator model path")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == spec["size"] and sha256(target) == spec["sha256"]:
        return
    temporary = target.with_suffix(target.suffix + ".download")
    request = urllib.request.Request(spec["url"], headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=90) as response, temporary.open("wb") as output:
        for block in iter(lambda: response.read(1024 * 1024), b""):
            output.write(block)
    if temporary.stat().st_size != spec["size"] or sha256(temporary) != spec["sha256"]:
        raise ValueError("Translator model verification failed: " + spec["path"])
    temporary.replace(target)


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy", type=Path, default=root / "ComfyUI")
    args = parser.parse_args()
    home = args.comfy.resolve().parent / "local-translator"
    home.mkdir(parents=True, exist_ok=True)
    spec = json.loads((root / "models.json").read_text(encoding="utf-8-sig"))["local_translation"]
    python = home / ".venv/Scripts/python.exe"
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(home / ".venv")], check=True)
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *spec["runtime"]], check=True)
    for item in spec["files"]:
        download(item, home / "models" / spec["model_dir"])
    for item in spec["quality"]["files"]:
        download(item, home / "models" / spec["quality"]["model_dir"])
    helper = home.parent / "local-prompt-helper"
    if not (helper / "runtime/llama-server.exe").is_file() or not (helper / "Qwen3.5-2B-Q4_K_M.gguf").is_file():
        subprocess.run([sys.executable, str(root / "scripts/install_prompt_helper.py"), "--comfy", str(args.comfy)], check=True)
    print("CPU-only English-to-Korean translator is ready. ComfyUI packages and models were not changed.")


if __name__ == "__main__":
    main()
