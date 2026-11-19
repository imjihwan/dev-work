"""CPU-only person bounds for conservative framing; never saves photos or crops."""
import hashlib
import io
import math
from pathlib import Path
import threading
from PIL import Image, ImageOps

MODEL_NAME = 'object_detection_yolox_2022nov.onnx'
MODEL_SHA256 = 'c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063'
MODEL_SIZE = 35858002
MODEL_URL = 'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/object_detection_yolox/' + MODEL_NAME
# YOLOX/OpenCV Zoo, Apache-2.0. Pre/postprocessing follows the official model card.
_LOCK = threading.Lock()
_NET = None
_NET_PATH = None


def protected_bounds(boxes):
    """Union all plausible people; uncertainty means keep the original canvas."""
    valid = [b for b in boxes if len(b)==5 and all(math.isfinite(float(v)) for v in b)
             and b[4]>=0.25 and 0<=b[0]<b[2]<=1 and 0<=b[1]<b[3]<=1]
    if not valid or max(b[4] for b in valid)<0.6:
        return None
    left,top=min(b[0] for b in valid),min(b[1] for b in valid)
    right,bottom=max(b[2] for b in valid),max(b[3] for b in valid)
    mx,my=max(0.035,(right-left)*0.15),max(0.025,(bottom-top)*0.1)
    return [max(0,left-mx),max(0,top-my),min(1,right+mx),min(1,bottom+my)]


def crop_contains(size, target, bounds):
    """Keep a small motion reserve beyond the stored detection safety margin."""
    if not isinstance(bounds,(list,tuple)) or len(bounds)!=4:
        return False
    if not all(type(v) in (int,float) and math.isfinite(v) for v in bounds):
        return False
    left,top,right,bottom=bounds
    if not 0<=left<right<=1 or not 0<=top<bottom<=1:
        return False
    # Apply at crop time so cached bounds also get the reserve without another
    # image read/detection. Do not mutate them or accumulate margins on reuse.
    mx,my=max(0.025,(right-left)*0.05),max(0.015,(bottom-top)*0.04)
    left,right=max(0,left-mx),min(1,right+mx)
    top,bottom=max(0,top-my),min(1,bottom+my)
    sw,sh=size;tw,th=target
    ratio=tw/th
    crop_w,crop_h=min(sw,sh*ratio),min(sh,sw/ratio)
    x,y=(sw-crop_w)/2,(sh-crop_h)/2
    return left*sw>=x and right*sw<=x+crop_w and top*sh>=y and bottom*sh<=y+crop_h


def detect_bounds(raw, model_path):
    """Return normalized protected bounds, or None. Inference uses one CPU thread."""
    import cv2
    import numpy as np
    global _NET,_NET_PATH
    path=str(Path(model_path).resolve())
    with _LOCK:
        if _NET is None or _NET_PATH!=path:
            data=Path(path).read_bytes()
            if len(data)!=MODEL_SIZE or hashlib.sha256(data).hexdigest()!=MODEL_SHA256:
                raise ValueError('인물 검출 모델 검증에 실패했습니다.')
            cv2.setNumThreads(1);cv2.ocl.setUseOpenCL(False)
            net=cv2.dnn.readNetFromONNX(path)
            net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            _NET,_NET_PATH=net,path
        with Image.open(io.BytesIO(raw)) as source:
            image=ImageOps.exif_transpose(source).convert('RGB')
        width,height=image.size;scale=min(640/width,640/height)
        small=cv2.resize(np.asarray(image),(max(1,int(width*scale)),max(1,int(height*scale))))
        padded=np.full((640,640,3),114,dtype=np.float32)
        padded[:small.shape[0],:small.shape[1]]=small
        _NET.setInput(padded.transpose(2,0,1)[None])
        rows=_NET.forward(_NET.getUnconnectedOutLayersNames())[0][0]
    grids=[];strides=[]
    for stride in (8,16,32):
        yy,xx=np.meshgrid(np.arange(640//stride),np.arange(640//stride),indexing='ij')
        grids.append(np.stack((xx,yy),axis=-1).reshape(-1,2))
        strides.append(np.full((xx.size,1),stride))
    grid=np.concatenate(grids);stride=np.concatenate(strides)
    if rows.shape!=(len(grid),85):
        raise ValueError('인물 검출 출력 형식을 확인하지 못했습니다.')
    scores=rows[:,4]*rows[:,5]
    keep=(scores>=0.25)&(rows[:,5:].argmax(axis=1)==0)
    centers=(rows[keep,:2]+grid[keep])*stride[keep]/scale
    sizes=np.exp(np.clip(rows[keep,2:4],-20,20))*stride[keep]/scale
    boxes=[]
    for center,size,score in zip(centers,sizes,scores[keep]):
        left,top=center-size/2;right,bottom=center+size/2
        if not (0<=center[0]<=width and 0<=center[1]<=height):continue
        boxes.append([max(0,float(left/width)),max(0,float(top/height)),
                      min(1,float(right/width)),min(1,float(bottom/height)),float(score)])
    return protected_bounds(boxes)
