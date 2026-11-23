"""Shift Video must drive the video sigma schedule; fake queue, no live work or private media."""
import ast
import json
import unittest
from pathlib import Path

from scripts import test_settings_sequence_bulk as fixtures

ROOT = Path(__file__).resolve().parents[1]
SCHED, SHIFT, LORA = "1512:2590", "1512:2692", "2678"
SERVER = ROOT / "simple_ui/server.py"


def server_functions(*names):
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    wanted = [node for node in tree.body
              if isinstance(node, ast.FunctionDef) and node.name in names
              or isinstance(node, ast.Assign) and any(getattr(t, "id", "").startswith("LEGACY_") for t in node.targets)]
    env = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), "shift-test", "exec"), env)
    return env


class RecommendedShiftTests(unittest.TestCase):
    def setUp(self):
        self.env = server_functions("effective", "drop_legacy_shift", "applied_shift")

    def test_model_defaults_follow_dasiwa_author_table(self):
        turbo = self.env["effective"]("model", {"auto": {"turbo": True, "steps_hint": 8}})
        regular = self.env["effective"]("model", {"auto": {"turbo": False}})
        self.assertEqual(turbo, {"steps": 8, "sampler": "euler", "scheduler": "simple", "shift_video": 7.0, "shift_audio": 4.0})
        self.assertEqual(regular, {"steps": 25, "sampler": "res_multistep", "scheduler": "simple", "shift_video": 11.0, "shift_audio": 4.0})
        saved = self.env["effective"]("model", {"auto": {"turbo": False}, "user": {"shift_video": 12.0}})
        self.assertEqual(saved["shift_video"], 12.0, "a per-model value the user saved still wins")

    def test_only_the_old_global_default_pair_is_dropped(self):
        legacy = {"steps": 8, "shift_video": 10.0, "shift_audio": 3.0}
        self.assertTrue(self.env["drop_legacy_shift"](legacy))
        self.assertEqual(legacy, {"steps": 8})
        chosen = {"shift_video": 10.0, "shift_audio": 5.0}
        self.assertFalse(self.env["drop_legacy_shift"](chosen))
        self.assertEqual(chosen, {"shift_video": 10.0, "shift_audio": 5.0})
        self.assertFalse(self.env["drop_legacy_shift"](None))

    def test_history_before_the_fix_reports_the_shift_that_actually_ran(self):
        applied = self.env["applied_shift"]
        self.assertEqual(applied({"shift_video": 10.0, "shift_audio": 3.0}), {"shift_video": 12.0, "shift_audio": 3.0})
        self.assertEqual(applied({"shift_video": 7.0, "shift_audio": 4.0, "shift_applied": True}),
                         {"shift_video": 7.0, "shift_audio": 4.0})

    def test_seed_cards_and_presets_carry_no_legacy_shift(self):
        for name in ("cards.seed.json", "presets.seed.json"):
            data = json.loads((ROOT / "simple_ui" / name).read_text(encoding="utf-8-sig"))
            rows = [card.get("user") or {} for card in data["model"].values()] if name.startswith("cards") else data.values()
            for row in rows:
                self.assertNotIn("shift_video", row, name)
                self.assertNotIn("shift_audio", row, name)


class SavedSamplerTests(unittest.TestCase):
    def test_saved_default_with_a_sampler_that_breaks_on_h3_falls_back_to_the_recommended_one(self):
        tree = ast.parse((ROOT / "simple_ui/server.py").read_text(encoding="utf-8-sig"))
        scope = {}
        exec(compile(ast.Module([n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "effective"], []), "effective", "exec"), scope)
        for turbo, expected in ((True, "euler"), (False, "res_multistep")):
            card = {"auto": {"turbo": turbo}, "user": {"sampler": "euler_cfg_pp", "steps": 6}}
            value = scope["effective"]("model", card)
            self.assertEqual((value["sampler"], value["steps"]), (expected, 6))
        self.assertEqual(scope["effective"]("model", {"auto": {"turbo": True}, "user": {"sampler": "lcm"}})["sampler"], "lcm")


class ModelDefaultsTests(unittest.TestCase):
    def test_catalog_default_follows_the_default_models_recommendation(self):
        # The story page starts new projects from catalog.default; it must match what the main page uses for the same model.
        tree = ast.parse((ROOT / "simple_ui/server.py").read_text(encoding="utf-8-sig"))
        wanted = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("template_defaults", "model_defaults")]
        scope = {"json": json, "TEMPLATE": str(ROOT / "simple_ui/template_api.json"), "LORA": LORA, "SCHED": SCHED, "SHIFT": SHIFT,
                 "LOADERS": ("1512:2586", "1512:2588"), "SAMPLER": "1512:2598", "DIRECTOR": "2730"}
        exec(compile(ast.Module(wanted, []), "defaults", "exec"), scope)
        template = scope["template_defaults"]()
        scope["card_for"] = lambda kind, name: {"effective": {"steps": 8, "sampler": "euler", "scheduler": "simple", "shift_video": 7.0, "shift_audio": 4.0}}
        value = scope["model_defaults"]()
        self.assertEqual((value["model"], value["mode"]), (template["model"], template["mode"]))
        self.assertEqual((value["shift_video"], value["shift_audio"], value["steps"]), (7.0, 4.0, 8))

        def unreadable(kind, name):
            raise OSError("model file missing")
        scope["card_for"] = unreadable
        self.assertEqual(scope["model_defaults"](), template)


class SigmaShiftWiringTests(unittest.TestCase):
    def test_template_scheduler_reads_shift_patched_model(self):
        graph = json.loads((ROOT / "simple_ui/template_api.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(graph[SCHED]["inputs"]["model"], [SHIFT, 0])
        self.assertEqual(graph[SHIFT]["inputs"]["model"], [LORA, 0])
        self.assertEqual(graph[SHIFT]["class_type"], "MiniMaxH3SigmaShift")

    def test_template_does_not_pay_for_a_preview_nobody_sees(self):
        # The simple UI never shows sampler previews. With a tiny VAE and 120 preview frames the node decoded the
        # whole clip at every step: measured 19.83 -> 19.12 s per step with these two values, identical output frames.
        graph = json.loads((ROOT / "simple_ui/template_api.json").read_text(encoding="utf-8-sig"))
        preview = graph["2737"]
        self.assertEqual(preview["class_type"], "ModelPreviewOverrideKJ")
        self.assertEqual((preview["inputs"]["tiny_vae"], preview["inputs"]["preview_frames"]), ("none", 1))
        self.assertEqual(graph["1512:2592"]["inputs"]["model"], ["2737", 0], "the node stays wired; only its values changed")

    def test_template_saves_at_the_node_default_quality(self):
        # quality 25 lost fine skin texture (45.9 dB against a near-lossless encode); 20 is the save node's own default (47.1 dB).
        graph = json.loads((ROOT / "simple_ui/template_api.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(graph["2568"]["inputs"]["quality"], 20)
        self.assertEqual((graph["2568"]["inputs"]["codec"], graph["2568"]["inputs"]["bit_depth"]), ("Auto", "Auto"))

    def test_built_graph_uses_requested_shift_even_from_old_template_wiring(self):
        fixture = fixtures.FeatureTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        old = json.loads((ROOT / "simple_ui/template_api.json").read_text(encoding="utf-8-sig"))
        old[SCHED]["inputs"]["model"] = [LORA, 0]
        path = Path(fixture.env["HERE"]) / "old_template_api.json"
        path.write_text(json.dumps(old), encoding="utf-8")
        fixture.env["TEMPLATE"] = str(path)
        result = fixture.env["build_and_queue"](
            fixture.request(images=fixture.photos[:1], shift_video=7.5, shift_audio=4.0),
            prepare_only=True)
        graph = result["prompt"]
        self.assertEqual(graph[SCHED]["inputs"]["model"], [SHIFT, 0])
        self.assertEqual(graph[SHIFT]["inputs"]["shift_video"], 7.5)
        self.assertEqual(graph[SHIFT]["inputs"]["shift_audio"], 4.0)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), old, "template file must stay untouched")

    def test_new_history_entries_are_marked_as_shift_applied(self):
        fixture = fixtures.FeatureTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.env["build_and_queue"](fixture.request(images=fixture.photos[:1], shift_video=7.0, shift_audio=4.0))
        entry = fixture.env["HIST_DB"][-1]
        self.assertTrue(entry["shift_applied"])
        self.assertEqual((entry["shift_video"], entry["shift_audio"]), (7.0, 4.0))


if __name__ == "__main__":
    unittest.main()
