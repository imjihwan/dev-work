"""Install only our two extension sources; never reads queue or user media."""
import argparse
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def install(comfy):
    comfy=Path(comfy).resolve()
    if not (comfy/'server.py').is_file():raise ValueError('ComfyUI directory not found')
    target=(comfy/'custom_nodes/H3VideoQueuePause').resolve()
    if not target.is_relative_to(comfy):raise ValueError('Extension path leaves ComfyUI')
    target.mkdir(parents=True,exist_ok=True)
    for name in ('__init__.py','control.py'):
        path=target/name
        if path.is_symlink():raise ValueError('Extension source must not be a symlink')
        temporary=path.with_name(name+'.installing')
        temporary.write_bytes((ROOT/'extensions/h3-video-queue-pause'/name).read_bytes())
        os.replace(temporary,path)
    print('Installed queue pause extension; activation requires a ComfyUI restart. No process was restarted.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--comfy',type=Path,default=ROOT/'ComfyUI')
    install(parser.parse_args().comfy)
