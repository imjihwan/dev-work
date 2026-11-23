"""Install the CPU-only framing detector; never touches jobs, photos or video models."""
import argparse
import hashlib
import os
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
NAME='object_detection_yolox_2022nov.onnx'
SHA256='c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'
SIZE=35858002
URL='https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/object_detection_yolox/'+NAME


def default_comfy():
    """README 의 위치 규칙: 이 프로젝트 안의 ComfyUI 폴더가 있으면 그것, 없으면 %USERPROFILE%\\ComfyUI."""
    local = ROOT / 'ComfyUI'
    return local if local.is_dir() else Path.home() / 'ComfyUI'


def install(comfy):
    # 엉뚱한 곳에 ComfyUI 폴더를 새로 만들면 다른 스크립트가 그 빈 폴더를 설치본으로 잘못 고른다
    if not (comfy/'main.py').is_file():raise SystemExit(f'ComfyUI 폴더를 찾지 못했습니다: {comfy} (--comfy 로 지정해 주세요)')
    target=comfy/'models'/'person_detection'/NAME
    license_file=ROOT/'third_party/person-framing/LICENSE.txt'
    if license_file.is_file():
        target.parent.mkdir(parents=True,exist_ok=True)
        (target.parent/'LICENSE.txt').write_bytes(license_file.read_bytes())
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==SHA256:
        print('CPU person detector verified.');return
    data=urllib.request.urlopen(URL,timeout=60).read(SIZE+1)
    if len(data)!=SIZE or hashlib.sha256(data).hexdigest()!=SHA256:
        raise ValueError('Person detector download failed SHA256 verification.')
    target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix('.download.tmp');temp.write_bytes(data);os.replace(temp,target)
    print('CPU person detector installed and verified (Apache-2.0, OpenCV Zoo).')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy',type=Path,default=None)
    install(parser.parse_args().comfy or default_comfy())
