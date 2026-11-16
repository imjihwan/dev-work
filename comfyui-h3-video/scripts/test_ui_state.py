"""화면 상태 동기화 서버 부분(ui_state_get/ui_state_save)만 떼어 임시 폴더에서 시험한다. 앱·ComfyUI 에 연결하지 않는다."""
import ast
import json
import os
import pathlib
import tempfile
import threading
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "simple_ui" / "server.py"
NAMES = {"_load_json", "_save_json", "UI_STATE_LOCK", "UI_STATE_PARTS", "_ui_state", "_ui_state_data", "ui_state_get", "ui_state_save"}


def load(here):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in NAMES:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in NAMES for t in node.targets):
            nodes.append(node)
    env = {"json": json, "os": os, "threading": threading, "HERE": here}
    env["UI_STATE"] = os.path.join(here, "ui-state.json")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "ui_state", "exec"), env)
    return env


class UiStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = load(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_server_returns_revision_zero_without_content(self):
        out = self.env["ui_state_get"]({"form": -1, "images": -1})
        self.assertEqual(out, {"form_rev": 0, "form": None, "images_rev": 0, "images": None})

    def test_saving_a_part_bumps_only_its_revision_and_persists(self):
        form = {"f": {"summary": "synthetic"}, "shots": [], "seed": "", "final": None, "model": {"anchor": True}}
        self.assertEqual(self.env["ui_state_save"]({"part": "form", "value": form}), {"rev": 1})
        self.assertEqual(self.env["ui_state_save"]({"part": "form", "value": form}), {"rev": 2})
        out = self.env["ui_state_get"]({"form": -1, "images": -1})
        self.assertEqual(out["form_rev"], 2); self.assertEqual(out["form"], form); self.assertEqual(out["images_rev"], 0)
        reloaded = load(self.tmp.name)   # 서버를 다시 켜도 남는다
        self.assertEqual(reloaded["ui_state_get"]({"form": -1, "images": -1})["form"], form)

    def test_window_with_current_revision_gets_numbers_only(self):
        self.env["ui_state_save"]({"part": "images", "value": ["data:image/png;base64,AAA"]})
        out = self.env["ui_state_get"]({"form": 0, "images": 1})
        self.assertEqual(out, {"form_rev": 0, "images_rev": 1})

    def test_invalid_parts_are_rejected(self):
        save = self.env["ui_state_save"]
        for body in ({"part": "other", "value": {}}, {"part": "form", "value": []}, {"part": "form", "value": {"f": "x"}},
                     {"part": "images", "value": ["https://example.invalid/x.png"]}, {"part": "images", "value": ["data:image/png;base64,A"] * 10}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                save(body)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "ui-state.json")))


if __name__ == "__main__":
    unittest.main()
