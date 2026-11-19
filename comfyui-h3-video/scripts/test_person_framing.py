"""Known synthetic person bounds and optional blank-image CPU inference only."""
import io
from pathlib import Path
import sys
import unittest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simple_ui'))
from person_framing import protected_bounds,crop_contains,detect_bounds,MODEL_NAME


class PersonFramingTests(unittest.TestCase):
    def test_centered_person_fits_but_wide_arms_or_off_center_person_do_not(self):
        target=(736,1280);size=(1200,1600)
        self.assertTrue(crop_contains(size,target,protected_bounds([[.35,.15,.65,.85,.9]])))
        self.assertFalse(crop_contains(size,target,protected_bounds([[.03,.15,.97,.85,.9]])))
        self.assertFalse(crop_contains(size,target,protected_bounds([[.01,.1,.38,.9,.95]])))

    def test_all_detected_people_are_protected_including_smaller_low_score_people(self):
        bounds=protected_bounds([[.35,.1,.6,.8,.95],[.82,.2,.95,.7,.3]])
        self.assertGreater(bounds[2],.95)
        self.assertFalse(crop_contains((1200,1600),(736,1280),bounds))

    def test_missing_uncertain_and_invalid_boxes_never_authorize_a_crop(self):
        for boxes in ([],[[.3,.1,.7,.9,.45]],[[float('nan'),0,1,1,.95]],[[.7,0,.3,1,.95]]):
            self.assertIsNone(protected_bounds(boxes))
        for bounds in (None,[],[0,0,1,float('nan')],[1,0,0,1]):
            self.assertFalse(crop_contains((1200,1600),(736,1280),bounds))

    def test_landscape_target_does_not_cut_head_or_feet(self):
        bounds=protected_bounds([[.3,.02,.7,.98,.95]])
        self.assertFalse(crop_contains((1200,1600),(1280,736),bounds))
        self.assertTrue(crop_contains((1200,1600),(768,1024),bounds))

    def test_installed_detector_runs_on_a_blank_synthetic_image_without_any_media_access(self):
        path=ROOT/'ComfyUI/models/person_detection'/MODEL_NAME
        if not path.exists():self.skipTest('Optional CPU person detector not installed')
        try:import cv2
        except ImportError:self.skipTest('Optional OpenCV not installed')
        out=io.BytesIO();Image.new('RGB',(160,120),(180,180,180)).save(out,format='PNG')
        self.assertIsNone(detect_bounds(out.getvalue(),path))
        self.assertEqual(cv2.getNumThreads(),1)


if __name__=='__main__':unittest.main()
