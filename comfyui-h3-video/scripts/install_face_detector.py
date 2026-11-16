"""Install the small CPU detector with SHA256 verification, without touching ComfyUI jobs."""
import argparse
import hashlib
import os
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
NAME = 'face_detection_yunet_2026may.onnx'
SHA256 = 'ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0'
URL = 'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/' + NAME


def install(comfy):
    target = comfy / 'models' / 'face_detection' / NAME
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == SHA256:
        print('CPU face detector verified.')
        return
    data = urllib.request.urlopen(URL, timeout=45).read(1_000_000)
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('Detector download failed SHA256 verification.')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.download.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, target)
    print('CPU face detector installed and verified (MIT, OpenCV Zoo).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy', type=Path, default=None)
    comfy = parser.parse_args().comfy
    if comfy is None:
        local = ROOT / 'ComfyUI'
        comfy = local if local.is_dir() else Path.home() / 'ComfyUI'
    install(comfy)
