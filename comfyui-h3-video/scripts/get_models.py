"""모델·LoRA 받기/검증 도구 (표준 라이브러리만 사용).

  python scripts/get_models.py --comfy C:\\ComfyUI            # 필수 파일만
  python scripts/get_models.py --comfy C:\\ComfyUI --all      # 선택 파일까지
  python scripts/get_models.py --comfy C:\\ComfyUI --check    # 받지 않고 상태만 확인
  python scripts/get_models.py --comfy C:\\ComfyUI --only base_ref2va_int8 lora_ref2v_turbo_4step

- source=hf      : Hugging Face 에서 바로 받는다(이어받기 지원). 받은 뒤 sha256 확인.
- source=civitai : use a pinned, hash-matching public mirror when configured;
                   otherwise import the file downloaded by the user from Civitai.
"""
import argparse, hashlib, json, os, shutil, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(os.path.dirname(HERE), "models.json")
UA = {"User-Agent": "comfyui-h3-video/get_models"}


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f}{u}" if u != "B" else f"{n}B"
        n /= 1024


def sha256(path, label):
    h, done, size, t0, shown = hashlib.sha256(), 0, os.path.getsize(path), time.time(), False
    with open(path, "rb") as f:
        while chunk := f.read(16 << 20):
            h.update(chunk)
            done += len(chunk)
            if time.time() - t0 > 1:
                shown = True
                print(f"\r  검증 중 {label[:48]}: {done * 100 // size}%", end="", flush=True)
    if shown:
        print()
    return h.hexdigest()


def ok_file(path, spec, verify):
    if not os.path.isfile(path) or os.path.getsize(path) != spec["size"]:
        return False
    return not verify or sha256(path, spec["filename"]) == spec["sha256"].lower()


def download_hf(spec, dest_path):
    url = f"https://huggingface.co/{spec['repo']}/resolve/{spec.get('revision','main')}/{spec['path']}"
    part = dest_path + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if have == spec["size"] and ok_file(part, spec, True):
        os.replace(part, dest_path)
        return
    if have >= spec["size"]:
        have = 0
    hdr = dict(UA, **({"Range": f"bytes={have}-"} if have else {}))
    r = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=60)
    if have and r.status != 206:      # 서버가 이어받기를 거부하면 처음부터
        have = 0
    total = spec["size"]
    t0, last = time.time(), 0
    with open(part, "ab" if have else "wb") as f:
        while chunk := r.read(8 << 20):
            f.write(chunk)
            have += len(chunk)
            if time.time() - last > 1:
                last = time.time()
                speed = have / max(1, last - t0)
                print(f"\r  받는 중 {spec['filename'][:48]}: {have * 100 // total}% "
                      f"({human(have)}/{human(total)}, {human(speed)}/s)", end="", flush=True)
    print()
    if not ok_file(part, spec, True):
        raise ValueError("Downloaded model failed size/SHA256 verification; existing model was not replaced")
    os.replace(part, dest_path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comfy", required=True, help="ComfyUI 폴더 경로")
    ap.add_argument("--all", action="store_true", help="선택(optional) 파일까지")
    ap.add_argument("--only", nargs="*", help="models.json 의 id 만 골라서")
    ap.add_argument("--check", action="store_true", help="받지 않고 상태만 확인")
    ap.add_argument("--fast", action="store_true", help="sha256 대신 크기만 확인(빠름)")
    ap.add_argument("--downloads", default=os.path.join(os.path.expanduser("~"), "Downloads"),
                    help="Civitai 파일을 브라우저로 받은 폴더")
    a = ap.parse_args()

    with open(MANIFEST, encoding="utf-8") as manifest:
        files = json.load(manifest)["files"]
    if a.only:
        files = [f for f in files if f["id"] in a.only]
    elif not a.all:
        files = [f for f in files if f["required"]]
    verify = not a.fast
    result = []
    for spec in files:
        dest_dir = os.path.join(a.comfy, *spec["dest"].split("/"))
        dest = os.path.join(dest_dir, spec["filename"])
        print(f"- {spec['id']}  ({human(spec['size'])})  {spec['role']}")
        if ok_file(dest, spec, verify):
            result.append((spec, "있음(확인됨)"))
            continue
        if os.path.exists(dest):
            print(f"  ! 크기 또는 sha256 이 다름: {dest}")
        if a.check:
            result.append((spec, "없음" if not os.path.exists(dest) else "불일치"))
            continue
        os.makedirs(dest_dir, exist_ok=True)
        if spec["source"] == "hf":
            try:
                download_hf(spec, dest)
                result.append((spec, "받음(확인됨)"))
            except Exception as e:  # noqa: BLE001
                result.append((spec, f"실패: {e}"))
        else:
            cand = os.path.join(a.downloads, spec["filename"])
            if os.path.isfile(cand):
                if ok_file(cand, spec, verify):
                    shutil.move(cand, dest)
                    result.append((spec, "다운로드 폴더에서 옮김(확인됨)"))
                else:
                    result.append((spec, f"다운로드 폴더 파일이 다름(받는 중이거나 손상): {cand}"))
            else:
                mirrors = [m for m in spec.get("mirrors", []) if m.get("source") == "hf"]
                if mirrors:
                    mirror = mirrors[0]
                    # Keep the canonical size/hash. A mirror cannot redefine them.
                    via = dict(spec, **{key: mirror[key] for key in ("repo", "path", "revision") if key in mirror})
                    try:
                        download_hf(via, dest)
                        result.append((spec, "받음(확인됨)"))
                    except Exception as e:
                        result.append((spec, f"미러 다운로드 실패: {e}"))
                else:
                    result.append((spec, "직접 받기 필요"))

    print("\n=== 결과 ===")
    manual = []
    for spec, st in result:
        print(f"{st:<28} {spec['dest']}/{spec['filename']}")
        if st == "직접 받기 필요":
            manual.append(spec)
    if manual:
        print("\nCivitai 파일은 로그인 후 브라우저로 받아야 합니다. 받은 뒤 이 스크립트를 다시 실행하면 옮기고 검증합니다.")
        for s in manual:
            print(f"  · {s['filename']}\n    페이지: {s['page']}\n    바로 받기: {s['url']}")
    bad = [r for r in result if not r[1].startswith(("있음", "받음(", "다운로드 폴더에서"))]
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
