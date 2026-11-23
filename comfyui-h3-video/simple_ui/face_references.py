"""CPU-only reference crops. Never stores source photos or sends them over a network."""
import hashlib
import io
import math
import os
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


def _largest_face(raw, model_path):
    """가장 큰 얼굴의 YuNet 결과(원본 좌표)와 원본 사진. 얼굴이 없으면 (None, image)."""
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
            return None, image
    face = select_face(faces)
    if face is None:
        return None, image
    face = face.copy()
    face[:14] /= scale
    return face, image


# 얼굴 방향: 코끝이 두 눈 가운데에서 눈 사이 거리의 몇 배만큼 옆으로 치우쳤는지(화면 기준, 음수 = 화면 왼쪽).
# 이 값보다 작게 치우치면 정면으로 본다. 실제로 쓴 사진들로 맞춘 값.
FRONT_OFFSET = 0.06


def facing_offset(face):
    """YuNet 랜드마크(눈 둘·코끝)로 얼굴이 화면 어느 쪽을 보는지 수치로. 눈 사이가 너무 좁으면 None."""
    eye_a, eye_b, nose = float(face[4]), float(face[6]), float(face[8])
    distance = abs(eye_b - eye_a)
    if distance < 4:
        return None
    return (nose - (eye_a + eye_b) / 2) / distance


def face_direction(raw, model_path):
    """사진 1의 가장 큰 얼굴이 화면 왼쪽·오른쪽·정면 중 어디를 보는지. 얼굴을 못 찾으면 None."""
    face, _ = _largest_face(raw, model_path)
    offset = None if face is None else facing_offset(face)
    if offset is None:
        return None
    side = 'left' if offset <= -FRONT_OFFSET else 'right' if offset >= FRONT_OFFSET else 'front'
    return {'side': side, 'offset': round(offset, 3)}


def crop_limit():
    """보조 얼굴 크롭의 긴 변 상한(화소). 환경 변수 SIMPLEUI_FACE_CROP_MAX 로 정하고, 없거나 0 이면 줄이지 않는다(기본).

    참조 사진은 생성 화소 면적까지만 쓰이고(Director 의 ref_image_size=match) 그보다 작은 사진은 그대로 쓰인다. 그래서 크롭을 더 작게
    줄이면 보조 사진마다 드는 토큰이 줄어 스텝이 빨라진다(실측은 docs/PERFORMANCE.md). 256 보다 작은 값은 256 으로 본다."""
    try:
        value = int(os.environ.get('SIMPLEUI_FACE_CROP_MAX', '0').strip() or 0)
    except ValueError:
        return 0
    return 0 if value <= 0 else max(256, value)


def crop_reference(raw, model_path):
    face, image = _largest_face(raw, model_path)
    if face is None:
        return None
    width, height = image.size
    box = crop_box(image.size, face)
    if box is None or box == (0, 0, width, height):
        return None
    crop, limit = image.crop(box), crop_limit()
    if limit and max(crop.size) > limit:
        scale = limit / max(crop.size)
        crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    crop.save(output, format='PNG')
    return output.getvalue(), crop.size
