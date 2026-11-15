"""CPU-only reference crops. Never stores source photos or sends them over a network."""
import hashlib
import io
import math
from pathlib import Path
import threading

from PIL import Image, ImageOps

MODEL_NAME = 'face_detection_yunet_2026may.onnx'
MODEL_SHA256 = 'ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0'
MODEL_URL = 'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/' + MODEL_NAME
_LOCK = threading.Lock()
_DETECTORS = {}


def select_face(faces):
    if faces is None:
        return None
    candidates = [f for f in faces if len(f) >= 15 and all(math.isfinite(float(v)) for v in f)
                  and float(f[14]) >= 0.9 and min(float(f[2]), float(f[3])) > 0]
    return max(candidates, key=lambda f: (float(f[2]) * float(f[3]), float(f[14])), default=None)


def crop_box(size, face):
    width, height = size
    x, y, fw, fh = (float(v) for v in face[:4])
    if min(fw, fh) < 32 or x < 0 or y < 0 or x + fw > width or y + fh > height:
        return None
    side = min(math.ceil(max(fw, fh) * 2), width, height)
    left = max(0, min(width - side, round(x + fw / 2 - side / 2)))
    top = max(0, min(height - side, round(y + fh / 2 - fh * 0.08 - side / 2)))
    box = (left, top, left + side, top + side)
    return box if left <= x and top <= y and box[2] >= x + fw and box[3] >= y + fh else None


def _detector(model_path):
    import cv2
    key = str(Path(model_path).resolve())
    if key not in _DETECTORS:
        try:
            data = Path(key).read_bytes()
        except OSError:
            raise ValueError('얼굴 검출 모델이 없습니다. scripts/install_face_detector.py를 실행해 주세요.') from None
        if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
            raise ValueError('얼굴 검출 모델 검증에 실패했습니다. scripts/install_face_detector.py를 다시 실행해 주세요.')
        cv2.setNumThreads(1)
        cv2.ocl.setUseOpenCL(False)
        _DETECTORS[key] = cv2.FaceDetectorYN_create(key, '', (640, 640), 0.9, 0.3, 5000,
                                                   cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU)
    return _DETECTORS[key]


def ensure_available(model_path):
    try:
        with _LOCK:
            _detector(model_path)
    except ImportError:
        raise ValueError('CPU 얼굴 검출에 OpenCV가 필요합니다. 설치 안내를 확인해 주세요.') from None


def crop_reference(raw, model_path):
    import cv2
    import numpy as np
    with Image.open(io.BytesIO(raw)) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
    width, height = image.size
    scale = min(1.0, 640 / max(width, height))
    preview = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)
    array = cv2.cvtColor(np.asarray(preview), cv2.COLOR_RGB2BGR)
    with _LOCK:
        detector = _detector(model_path)
        detector.setInputSize(preview.size)
        try:
            _, faces = detector.detect(array)
        except cv2.error:
            return None
    face = select_face(faces)
    if face is None:
        return None
    face = face.copy()
    face[:14] /= scale
    box = crop_box(image.size, face)
    if box is None or box == (0, 0, width, height):
        return None
    output = io.BytesIO()
    image.crop(box).save(output, format='PNG')
    return output.getvalue(), (box[2] - box[0], box[3] - box[1])
