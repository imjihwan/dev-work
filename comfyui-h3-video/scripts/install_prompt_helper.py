"""Install the pinned CPU-only runtime and prompt model; no user data is read."""
import hashlib
import json
import os
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = None  # main 에서 정함: ComfyUI 폴더와 같은 위치(simple_ui/prompt_helper.py 가 찾는 곳)


def default_comfy(project):
    """ComfyUI 위치: <저장소>/ComfyUI 가 있으면 그것, 없으면 setup.ps1 기본값 %USERPROFILE%\\ComfyUI."""
    local = project / "ComfyUI"
    return local if local.is_dir() else Path.home() / "ComfyUI"


def download(spec):
    path = DEST / spec["filename"]
    if not path.exists():
        partial = path.with_suffix(path.suffix + ".part")
        offset = partial.stat().st_size if partial.exists() else 0
        req = urllib.request.Request(spec["url"], headers={"Range": f"bytes={offset}-"} if offset else {})
        with urllib.request.urlopen(req, timeout=60) as response:
            if response.status != 206: offset = 0
            reported = time.monotonic()
            with partial.open("ab" if offset else "wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    offset += len(chunk)
                    if time.monotonic() - reported > 10:
                        print(f'{spec["filename"]}: {offset}/{spec["size"]}', flush=True)
                        reported = time.monotonic()
        partial.replace(path)
    if path.stat().st_size != spec["size"]:
        raise ValueError(f"Unexpected file size: {path.name}")
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != spec["sha256"]: raise ValueError(f"SHA256 mismatch: {path.name}")
    print(f"Verified: {path.name}", flush=True)
    return path


if __name__ == "__main__":
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy", type=Path, default=None, help="ComfyUI 폴더(기본: 저장소\\ComfyUI 또는 %%USERPROFILE%%\\ComfyUI)")
    comfy = (parser.parse_args().comfy or default_comfy(ROOT)).resolve()
    DEST = comfy.parent / "local-prompt-helper"
    print(f"Install location: {DEST}", flush=True)
    DEST.mkdir(exist_ok=True)
    specs = json.loads((ROOT / "models.json").read_text(encoding="utf-8"))["prompt_helper"]
    runtime = download(specs["runtime"])
    with zipfile.ZipFile(runtime) as archive:
        archive.extractall(DEST / "runtime")
    download(specs["model"])
    print("CPU prompt helper installation complete.", flush=True)
