"""Synthetic images and fake detections; no network, user files or generation jobs."""
import importlib.util
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('FACE_REFERENCE_SOURCE', ROOT / 'simple_ui'))
spec = importlib.util.spec_from_file_location('face_crop_under_test', SOURCE / 'face_references.py')
face = importlib.util.module_from_spec(spec)
spec.loader.exec_module(face)


def detection(x=40, y=20, w=40, h=40, score=0.99):
    return np.array([x,y,w,h,x+w*.3,y+h*.3,x+w*.7,y+h*.3,
                     x+w*.5,y+h*.5,x+w*.3,y+h*.7,x+w*.7,y+h*.7,score],dtype=np.float32)


class CropTests(unittest.TestCase):
    def raw(self, size=(160,80), exif=None):
        output=io.BytesIO()
        image=Image.new('RGB',size,'red')
        if exif:image.save(output,'JPEG',exif=exif)
        else:image.save(output,'PNG')
        return output.getvalue()

    def fake_detector(self, faces):
        class Fake:
            def setInputSize(self,size): self.size=size
            def detect(self,array): return 1,faces
        return Fake()

    def test_largest_area_wins_over_confidence_or_order(self):
        small=detection(w=32,h=32,score=.999)
        big=detection(w=60,h=50,score=.91)
        self.assertIs(face.select_face([small,big]),big)
        self.assertIs(face.select_face([big,small]),big)
        self.assertIsNone(face.select_face(None))
        self.assertIsNone(face.select_face([detection(score=.8)]))

    def test_generous_crop_and_original_bytes_unchanged(self):
        raw=self.raw();before=bytes(raw)
        detector=self.fake_detector(np.array([detection()]))
        with patch.object(face,'_detector',return_value=detector):
            result=face.crop_reference(raw,'unused')
        self.assertEqual(raw,before)
        self.assertEqual(result[1],(80,80))
        with Image.open(io.BytesIO(result[0])) as image:
            self.assertEqual(image.size,(80,80))
            self.assertEqual(image.getpixel((0,0)),(255,0,0))

    def test_optional_limit_shrinks_large_crops_only_and_reports_the_saved_size(self):
        # SIMPLEUI_FACE_CROP_MAX: 보조 얼굴 크롭의 긴 변 상한(선택). 기본은 줄이지 않는다
        detector=self.fake_detector(np.array([detection(x=160,y=120,w=200,h=200)]))      # 검출은 640 으로 줄인 미리보기 좌표(원본에서는 500 화소 얼굴)
        raw=self.raw((1600,1200))
        def crop(**env):
            with patch.dict(os.environ,env),patch.object(face,'_detector',return_value=detector):
                data,size=face.crop_reference(raw,'unused')
            with Image.open(io.BytesIO(data)) as image:self.assertEqual(image.size,size)
            return size
        os.environ.pop('SIMPLEUI_FACE_CROP_MAX',None)
        self.assertEqual(crop(),(1000,1000))
        self.assertEqual(crop(SIMPLEUI_FACE_CROP_MAX='640'),(640,640))
        self.assertEqual(crop(SIMPLEUI_FACE_CROP_MAX='2000'),(1000,1000),'작은 크롭은 키우지 않는다')
        self.assertEqual(crop(SIMPLEUI_FACE_CROP_MAX='0'),(1000,1000))
        self.assertEqual(crop(SIMPLEUI_FACE_CROP_MAX='100'),(256,256),'너무 작은 값은 256 으로 본다')
        self.assertEqual(crop(SIMPLEUI_FACE_CROP_MAX='big'),(1000,1000),'읽을 수 없는 값은 줄이지 않는다')

    def test_exif_orientation_is_applied_before_detection(self):
        exif=Image.Exif();exif[274]=6
        detector=self.fake_detector(np.array([detection(x=20,y=10,w=32,h=32)]))
        with patch.object(face,'_detector',return_value=detector):
            result=face.crop_reference(self.raw((60,100),exif),'unused')
        self.assertEqual(detector.size,(100,60))
        self.assertEqual(result[1],(60,60))

    def test_failed_small_or_outside_detection_keeps_original(self):
        for detections in [None,np.array([detection(w=20,h=20)]),np.array([detection(x=-2)])]:
            with patch.object(face,'_detector',return_value=self.fake_detector(detections)):
                self.assertIsNone(face.crop_reference(self.raw(),'unused'))

    def test_safe_bounds_at_all_edges(self):
        for width,height in [(320,640),(640,320),(512,512)]:
            for x in [0,width//2,width-64]:
                for y in [0,height//2,height-64]:
                    box=face.crop_box((width,height),detection(x,y,64,64))
                    self.assertIsNotNone(box)
                    self.assertLessEqual(box[0],x);self.assertLessEqual(box[1],y)
                    self.assertGreaterEqual(box[2],x+64);self.assertGreaterEqual(box[3],y+64)
                    self.assertTrue(0<=box[0]<box[2]<=width and 0<=box[1]<box[3]<=height)


if __name__=='__main__':unittest.main()
