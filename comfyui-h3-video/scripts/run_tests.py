"""파이썬·Node 테스트를 한 번에 돌린다. 가짜 대기열·합성 데이터만 쓰는 기존 테스트를 그대로 실행할 뿐이다.

    <python> scripts/run_tests.py            # 전부
    <python> scripts/run_tests.py --python   # 파이썬만
    <python> scripts/run_tests.py --node     # Node 화면 테스트만
    <python> scripts/run_tests.py story gallery   # 이름에 이 낱말이 든 테스트 파일만

실패가 하나라도 있으면 종료 코드 1. ComfyUI·화면 서버(8190)·사용자 데이터에는 접근하지 않는다.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def selected(pattern, words):
    files = sorted(SCRIPTS.glob(pattern))
    return [path for path in files if not words or any(word.lower() in path.stem.lower() for word in words)]


def run_python(words):
    files = selected("test_*.py", words)
    if not files:
        return None
    if words:
        # 고른 파일만: discover 는 패턴 하나만 받으므로 파일마다 돌린다
        failed = []
        for path in files:
            code = subprocess.call([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "scripts", "-p", path.name], cwd=ROOT)
            if code:
                failed.append(path.name)
        return failed
    code = subprocess.call([sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_*.py"], cwd=ROOT)
    return ["python unittest"] if code else []


def run_node(words):
    files = selected("test_*.cjs", words)
    if not files:
        return None
    node = shutil.which("node")
    if not node:
        print("Node.js 를 찾지 못해 화면 테스트를 건너뜁니다.", flush=True)
        return ["node 없음"]
    failed = []
    for path in files:
        started = time.monotonic()
        done = subprocess.run([node, str(path)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        mark = "ok  " if done.returncode == 0 else "FAIL"
        print(f"{mark} {path.name} ({time.monotonic() - started:.1f}s)", flush=True)
        if done.returncode:
            failed.append(path.name)
            # 실패한 파일의 출력만 보여 준다
            print((done.stdout + done.stderr).strip()[-4000:], flush=True)
    return failed


def main():
    parser = argparse.ArgumentParser(description="comfyui-h3-video 테스트 실행")
    parser.add_argument("--python", action="store_true", help="파이썬 테스트만")
    parser.add_argument("--node", action="store_true", help="Node 화면 테스트만")
    parser.add_argument("words", nargs="*", help="테스트 파일 이름에 포함된 낱말(여러 개면 하나라도 맞는 파일)")
    args = parser.parse_args()
    both = not (args.python or args.node)
    results = {}
    if both or args.python:
        results["python"] = run_python(args.words)
    if both or args.node:
        results["node"] = run_node(args.words)
    ran = {name: failed for name, failed in results.items() if failed is not None}
    if not ran:
        print("조건에 맞는 테스트 파일이 없습니다.", flush=True)
        return 1
    print("\n=== 요약 ===", flush=True)
    for name, failed in ran.items():
        print(f"{name}: {'통과' if not failed else '실패 — ' + ', '.join(failed)}", flush=True)
    return 1 if any(ran.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
