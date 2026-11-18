"""Install the pinned official Grok binary locally; no model, auth or private work is read."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

VERSION = "1.0.89"
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy", type=Path)
    args = parser.parse_args()
    comfy = args.comfy or (ROOT / "ComfyUI" if (ROOT / "ComfyUI").is_dir() else Path.home() / "ComfyUI")
    home = comfy.resolve().parent / "local-prompt-helper"
    target = home / "grok-cli"
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    node = shutil.which("node")
    if os.name != "nt" or not npm or not node:
        raise SystemExit("Windows x64, Node.js 20+ and npm are required.")
    subprocess.run([npm, "install", "--prefix", str(target), "--ignore-scripts", "--no-audit", "--no-fund",
                    "--save-exact", "@xai-official/grok@" + VERSION], check=True)
    # The official Windows package ships Brotli-compressed bytes. Extract only
    # the pinned binary, avoiding the installer modifying the user's global CLI.
    source = target / "node_modules/@xai-official/grok-win32-x64/bin/grok.exe.br"
    dest = target / "bin/grok.exe"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file(): raise SystemExit("The pinned Windows x64 package is missing.")
    subprocess.run([node, "-e", "const f=require('fs'),z=require('zlib');f.writeFileSync(process.argv[2],z.brotliDecompressSync(f.readFileSync(process.argv[1])));", str(source), str(dest)], check=True)
    account = home / "grok-account"
    account.mkdir(exist_ok=True)
    config = account / "config.toml"
    if not config.exists():
        config.write_text('[cli]\nauto_update = false\nuse_leader = false\n[session]\nload_envrc = false\n[models]\ndefault = "grok-4.7"\n', encoding="utf-8")
    result = subprocess.run([str(dest), "--version"], capture_output=True, text=True, check=True)
    if not result.stdout.startswith("grok " + VERSION + " "):
        raise SystemExit("Unexpected CLI version.")
    print(json.dumps({"installed": True, "version": VERSION, "account_separate": True}))


if __name__ == "__main__": main()
