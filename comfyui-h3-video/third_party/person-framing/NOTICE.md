# CPU person framing detector

The optional YOLOX-S ONNX model is published by OpenCV Zoo under Apache-2.0.
Upstream model, preprocessing and postprocessing reference:
https://github.com/opencv/opencv_zoo/tree/main/models/object_detection_yolox

Original YOLOX project: https://github.com/Megvii-BaseDetection/YOLOX
Model size and SHA256 are pinned in models.json and the installer.
Weights are downloaded separately and are never included in this repository.
The app uses OpenCV CPU inference and a conservative union of detected people;
this is a framing hint, not a guarantee of detector accuracy.
