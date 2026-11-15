"""Resume public model downloads in verified HTTP ranges, then check SHA256."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 32 * 1024 * 1024
WORKERS = 24
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--manifest", type=Path, default=ROOT / "setup" / "models.json")
parser.add_argument("--verified", type=Path, default=ROOT / "setup" / "verified-models.json")
args = parser.parse_args()
models = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
verified = []

for model in models:
    destination = ROOT / model["path"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + ".part")
    state_path = part.with_name(part.name + ".json")
    if not destination.exists():
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
        else:
            state = {"prefix": part.stat().st_size if part.exists() else 0, "done": []}
            state_path.write_text(json.dumps(state), encoding="utf-8")
        prefix = state["prefix"]
        if prefix > model["bytes"]:
            raise RuntimeError(f"Invalid partial size: {part}")
        with part.open("ab") as handle:
            handle.truncate(model["bytes"])
        ranges = [(start, min(start + CHUNK, model["bytes"]) - 1) for start in range(prefix, model["bytes"], CHUNK)]
        done = set(state["done"])
        pending = [item for item in ranges if item[0] not in done]
        lock = threading.Lock()
        counters = {"bytes": prefix + sum(end - start + 1 for start, end in ranges if start in done), "last": 0.0}
        started = time.monotonic()
        initial = counters["bytes"]
        print(f"Downloading {model['name']}: {initial / 1e9:.2f}/{model['bytes'] / 1e9:.2f} GB", flush=True)

        def download_range(item):
            start, end = item
            for attempt in range(7):
                try:
                    request = urllib.request.Request(
                        model["url"] + f"?download=true&range_start={start}",
                        headers={"Range": f"bytes={start}-{end}", "User-Agent": "RemixLocalSetup/1.0"},
                    )
                    with urllib.request.urlopen(request, timeout=60) as response:
                        expected = f"bytes {start}-{end}/{model['bytes']}"
                        if response.status != 206 or response.headers.get("Content-Range") != expected:
                            raise RuntimeError(f"Unexpected range response: {response.status}, {response.headers.get('Content-Range')}")
                        remaining = end - start + 1
                        with part.open("r+b", buffering=0) as handle:
                            handle.seek(start)
                            while remaining:
                                data = response.read(min(1024 * 1024, remaining))
                                if not data:
                                    raise RuntimeError("Truncated HTTP range")
                                handle.write(data)
                                remaining -= len(data)
                    with lock:
                        done.add(start)
                        counters["bytes"] += end - start + 1
                        state["done"] = sorted(done)
                        temporary = state_path.with_suffix(".tmp")
                        temporary.write_text(json.dumps(state), encoding="utf-8")
                        os.replace(temporary, state_path)
                        now = time.monotonic()
                        if now - counters["last"] >= 15:
                            rate = (counters["bytes"] - initial) / max(now - started, 1) / 1e6
                            print(f"{model['name']}: {counters['bytes']/1e9:.2f}/{model['bytes']/1e9:.2f} GB, {rate:.1f} MB/s", flush=True)
                            counters["last"] = now
                    return
                except Exception as exc:
                    if attempt == 6:
                        raise
                    if attempt == 0:
                        print(f"Retrying range {start}: {type(exc).__name__}", flush=True)
                    time.sleep(min(2 ** attempt, 20))

        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for _ in pool.map(download_range, pending):
                pass
        source = part
    else:
        source = destination
    print(f"Verifying {model['name']}", flush=True)
    with source.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if source.stat().st_size != model["bytes"] or digest != model["sha256"]:
        raise RuntimeError(f"Checksum mismatch: {source}")
    if source != destination:
        source.replace(destination)
    state_path.unlink(missing_ok=True)
    verified.append({"name": model["name"], "path": model["path"], "sha256": digest, "verified_utc": datetime.now(timezone.utc).isoformat()})
    args.verified.write_text(json.dumps(verified, indent=2), encoding="utf-8")
    print(f"Ready: {model['name']}", flush=True)
