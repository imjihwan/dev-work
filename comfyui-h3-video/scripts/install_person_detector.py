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


def install(comfy):
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
    parser.add_argument('--comfy',type=Path,default=ROOT/'ComfyUI')
    install(parser.parse_args().comfy)
