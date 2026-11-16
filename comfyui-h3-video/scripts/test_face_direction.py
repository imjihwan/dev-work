"""얼굴 방향 판정 규칙(코끝이 두 눈 가운데에서 치우친 정도)만 합성 랜드마크로 시험한다. 사진·모델을 쓰지 않는다."""
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "simple_ui"))
import face_references as fr  # noqa: E402


def face(eye_a, eye_b, nose):
    # YuNet: x,y,w,h, 눈1(x,y), 눈2(x,y), 코끝(x,y), 입꼬리 둘, 점수
    return [0, 0, 100, 100, eye_a, 40, eye_b, 40, nose, 60, 40, 80, 60, 80, 0.99]


class FaceDirectionTest(unittest.TestCase):
    def judge(self, landmarks):
        with mock.patch.object(fr, "_largest_face", return_value=(landmarks, None)):
            return fr.face_direction(b"synthetic", "unused.onnx")

    def test_nose_left_of_eye_center_faces_frame_left(self):
        self.assertEqual(self.judge(face(30, 70, 40))["side"], "left")   # 코끝 -10 / 눈 사이 40 = -0.25

    def test_nose_right_of_eye_center_faces_frame_right(self):
        self.assertEqual(self.judge(face(30, 70, 60))["side"], "right")

    def test_small_offsets_count_as_front(self):
        self.assertEqual(self.judge(face(30, 70, 51))["side"], "front")  # +0.025
        self.assertEqual(self.judge(face(30, 70, 48))["side"], "front")

    def test_threshold_boundary_and_missing_face(self):
        self.assertEqual(self.judge(face(30, 70, 50 - 40 * (fr.FRONT_OFFSET + 0.005)))["side"], "left")
        self.assertIsNone(self.judge(None))
        self.assertIsNone(self.judge(face(50, 52, 51)))  # 눈 사이가 너무 좁으면 판정하지 않는다


if __name__ == "__main__":
    unittest.main()
