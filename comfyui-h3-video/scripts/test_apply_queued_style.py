"""Style-only queue changes against synthetic templates and a fake queue."""
import ast
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from scripts import apply_queued_style as helper


class StyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        source = (helper.PROJECT / "simple_ui/server.py").read_text(encoding="utf-8-sig")
        (self.home / "server.py").write_text(source, encoding="utf-8")
        self.env = helper.dry_builder(self.home)
        e = self.env
        self.old = "Synthetic original camera."
        self.new = "Synthetic 30-degree camera.\n\nNatural perspective."
        self.text = "subject_definitions: Synthetic identity.\n\nsummary: Synthetic action.\n\nretention_analysis: Keep synthetic clothing.\n\ndetailed_description: " + self.old + " A synthetic movement.\n\noverall_soundscape: Synthetic sound.\n\nnon_diegetic_music: N/A"
        timeline = {"items": [{"value": "synthetic-photo.png", "source_width": 640, "source_height": 384, "slot": 0, "order": 0, "start": 0}],
                    "builder_state": {}, "continuity": {}, "resolution": {}}
        graph = {}
        for node in e["LOADERS"]:
            graph[node] = {"class_type": "UNETLoader", "inputs": {"unet_name": "synthetic-model"}}
        for name in ("SEED", "SCHED", "SAMPLER", "SHIFT", "LORA"):
            graph[e[name]] = {"class_type": "Synthetic", "inputs": {}}
        graph[e["SCHED"]]["inputs"]["steps"] = 4
        graph[e["SAMPLER"]]["inputs"]["sampler_name"] = "euler"
        graph[e["DIRECTOR"]] = {"class_type": "SyntheticDirector", "inputs": {"timeline_data": json.dumps(timeline), "builder_state": "{}"}}
        graph[e["GUIDE"]] = {"class_type": "MiniMaxH3DirectorGuide", "inputs": {}}
        graph[e["GUIDER"]] = {"class_type": "SyntheticGuider", "inputs": {"conditioning": [e["GUIDE"], 0]}}
        graph[e["SAVE"]] = {"class_type": "SyntheticSaver", "inputs": {"unchanged": "synthetic-output-setting"}}
        (self.home / "template_api.json").write_text(json.dumps(graph), encoding="utf-8")
        self.entry = {"id": "owned", "t": 1, "state": "queued", "prompt": self.text, "images": ["synthetic-photo.png"],
                      "mode": "REF2VA", "model": "synthetic-model", "steps": 4, "sampler": "euler", "scheduler": "simple",
                      "shift_video": 5, "shift_audio": 5, "loras": [], "seed": 123, "duration": 5, "aspect": "auto", "resolution": "draft", "anchor": True,
                      "ui": {"f": {"style": self.old, "summary": "Synthetic action.", "keep": "Synthetic clothing.", "subject": "Synthetic identity."},
                             "shots": [[0, "A synthetic movement."]], "final": None, "oneTake": True}}
        e["object_options"] = lambda kind, field: ["synthetic-model"] if kind == "UNETLoader" else []
        result = e["build_and_queue"](dict(self.entry, count=1), reference={"entry": self.entry, "prompt": graph}, prepare_only=True)
        self.entry.update(width=result["width"], height=result["height"])
        self.item = [7, "owned", result["prompt"], {"client_id": "synthetic-client"}, []]

    def test_only_style_changes_in_all_prompt_copies_and_other_settings_match(self):
        original = copy.deepcopy(self.item)
        body, expected = helper.prepare(self.entry, self.item, self.new, self.env)
        self.assertEqual(self.item, original)
        self.assertEqual(body["ui"], {"f": {"style": self.new}, "final": None})
        self.assertEqual(body["prompt"], self.text.replace(self.old, self.new))
        self.assertEqual(body["bulk_fields"], ["content"])
        director = self.env["DIRECTOR"]
        for node in self.item[2]:
            if node != director:
                self.assertEqual(expected[node], self.item[2][node])
        for preserved in ("Synthetic identity.", "Synthetic action.", "Keep synthetic clothing.", "A synthetic movement.", "Synthetic sound."):
            self.assertIn(preserved, body["prompt"])

    def test_manual_final_edits_outside_style_are_kept(self):
        manual = self.text.replace("A synthetic movement.", "A manually edited synthetic movement.")
        self.item[2] = helper.patch_graph(self.item[2], self.env["DIRECTOR"], self.text, manual)
        self.entry["prompt"] = manual
        self.entry["ui"]["final"] = manual
        body, _ = helper.prepare(self.entry, self.item, self.new, self.env)
        self.assertIn("manually edited", body["prompt"])
        self.assertEqual(body["ui"]["final"], body["prompt"])

    def test_disabled_anchor_only_removes_frame_zero_nodes_and_keeps_reference(self):
        body,expected=helper.prepare(self.entry,self.item,self.new,self.env,disable_anchor=True)
        self.assertEqual(body["bulk_fields"],["content","anchor"])
        self.assertFalse(body["anchor"])
        self.assertNotIn(self.env["ANCHOR"],expected)
        self.assertNotIn(self.env["ANCHOR_IMG"],expected)
        self.assertEqual(expected[self.env["GUIDER"]]["inputs"]["conditioning"],[self.env["GUIDE"],0])
        before=json.loads(self.item[2][self.env["DIRECTOR"]]["inputs"]["timeline_data"])
        after=json.loads(expected[self.env["DIRECTOR"]]["inputs"]["timeline_data"])
        self.assertEqual(before["items"],after["items"])
        self.assertEqual(expected[self.env["SEED"]],self.item[2][self.env["SEED"]])

    def test_background_retention_changes_are_scoped_and_idempotent(self):
        keep="Keep the face, outfit and background exactly as in <Picture 1>. Preserve existing glasses. Keep the same environment, with natural perspective. No text."
        changed=helper.refresh_reference_background(keep)
        self.assertIn("Keep the face, outfit exactly as in <Picture 1>.",changed)
        self.assertIn("Preserve existing glasses.",changed)
        self.assertIn("No text.",changed)
        self.assertNotIn("Keep the same environment",changed)
        self.assertTrue(changed.endswith(helper.REFERENCE_BACKGROUND))
        self.assertEqual(helper.refresh_reference_background(changed),changed)
        self.assertEqual(helper.refresh_reference_background("Preserve face and outfit. No text."),"Preserve face and outfit. No text.")

    def test_previous_generated_rule_is_refreshed_without_dropping_user_content(self):
        old=self.text.replace("Keep synthetic clothing.","Keep synthetic clothing. "+helper.PREVIOUS_ONE_TAKE_KEEP)
        new=helper.refresh_common_rule(old,self.entry,"New synthetic continuity rule.")
        self.assertNotIn(helper.PREVIOUS_ONE_TAKE_KEEP,new)
        self.assertIn("Keep synthetic clothing. New synthetic continuity rule.",new)

    def test_reference_role_refresh_changes_only_generated_subject_and_adds_pose_exception(self):
        original=self.text.replace("Synthetic identity.",helper.REFERENCE_SUBJECT_OLD_MULTI+" Other synthetic reference roles.")
        original=original.replace("Keep synthetic clothing.","Keep synthetic clothing.\nKeep synthetic accessories.")
        changed=helper.refresh_reference_roles(original)
        self.assertIn(helper.REFERENCE_SUBJECT_APPEARANCE+" Other synthetic reference roles.",changed)
        self.assertIn("Keep synthetic accessories. "+helper.REFERENCE_POSE_SCOPE,changed)
        self.assertIn("summary: Synthetic action.",changed)
        self.assertIn("A synthetic movement.",changed)
        self.assertEqual(helper.refresh_reference_roles(changed),changed)
        self.assertEqual(helper.refresh_reference_subject("Synthetic identity."),"Synthetic identity.")
        with self.assertRaises(helper.StyleMismatch):
            helper.refresh_reference_roles("detailed_description: A custom manual prompt.")

    def test_role_refresh_saves_subject_and_all_final_copies_preserving_manual_actions(self):
        old=self.text.replace("Synthetic identity.",helper.REFERENCE_SUBJECT_OLD_SINGLE+" Synthetic identity.")
        self.item[2]=helper.patch_graph(self.item[2],self.env["DIRECTOR"],self.text,old)
        self.entry["prompt"]=old
        self.entry["ui"]["f"]["subject"]=helper.REFERENCE_SUBJECT_OLD_SINGLE+" Synthetic identity."
        self.entry["ui"]["final"]=old
        body,expected=helper.prepare(self.entry,self.item,self.new,self.env,disable_anchor=True,reference_role=True)
        self.assertEqual(body["ui"]["f"]["subject"],helper.REFERENCE_SUBJECT_APPEARANCE+" Synthetic identity.")
        self.assertEqual(body["ui"]["final"],body["prompt"])
        self.assertIn(helper.REFERENCE_POSE_SCOPE,body["prompt"])
        self.assertIn("A synthetic movement.",body["prompt"])
        self.assertNotIn("keep",body["ui"]["f"])
        self.assertEqual(expected[self.env["SEED"]],self.item[2][self.env["SEED"]])

    def test_whitespace_variation_and_repeated_action_text_do_not_change_actions(self):
        text = self.text.replace(self.old, "Synthetic\n original   camera.")
        text = text.replace("A synthetic movement.", self.old + " A synthetic movement.")
        changed = helper.replace_style(text, self.old, self.new)
        self.assertIn(self.new + " " + self.old + " A synthetic movement.", changed)

    def test_missing_or_ambiguous_style_and_unrelated_graph_drift_are_skipped(self):
        with self.assertRaises(helper.StyleMismatch):
            helper.replace_style(self.text, "Missing old style.", self.new)
        self.item[2][self.env["SAVE"]]["inputs"]["unchanged"] = "A custom setting that must not be lost"
        with self.assertRaisesRegex(helper.StyleMismatch, "other_graph_settings"):
            helper.prepare(self.entry, self.item, self.new, self.env)

    def test_empty_style_is_inserted_without_removing_action_or_other_sections(self):
        text = self.text.replace(self.old + " ", "")
        self.assertEqual(helper.replace_style(text, "", self.new), self.text.replace(self.old, self.new))

    def test_common_rule_changes_only_generated_retention_suffix(self):
        rule = "One continuous take: preserve the newly established camera viewpoint."
        old = self.text.replace("Keep synthetic clothing.", "Keep synthetic clothing. " + helper.LEGACY_ONE_TAKE_KEEP)
        old = old.replace("A synthetic movement.", "A synthetic movement. " + helper.LEGACY_ONE_TAKE_KEEP)
        changed = helper.refresh_common_rule(old, self.entry, rule)
        self.assertIn("retention_analysis: Keep synthetic clothing. " + rule, changed)
        self.assertIn("A synthetic movement. " + helper.LEGACY_ONE_TAKE_KEEP, changed)
        self.assertEqual(helper.refresh_common_rule(changed, self.entry, rule), changed)
        self.assertEqual(self.entry["ui"]["f"]["keep"], "Synthetic clothing.")

    def test_common_rule_preserves_user_retention_and_manual_final_edits(self):
        rule = "One continuous take: preserve the newly established camera viewpoint."
        old = self.text.replace("Keep synthetic clothing.", "Manual synthetic retention. " + helper.LEGACY_ONE_TAKE_KEEP)
        self.assertIn("Manual synthetic retention. " + rule, helper.refresh_common_rule(old, self.entry, rule))
        self.entry["ui"]["f"]["keep"] = helper.LEGACY_ONE_TAKE_KEEP
        self.assertEqual(helper.refresh_common_rule(old, self.entry, rule), old, "Saved user retention is outside the generated suffix migration")

    def test_prepare_refreshes_all_final_copies_without_touching_settings(self):
        rule = "One continuous take: preserve the newly established camera viewpoint."
        old = self.text.replace("Keep synthetic clothing.", "Keep synthetic clothing. " + helper.LEGACY_ONE_TAKE_KEEP)
        self.item[2] = helper.patch_graph(self.item[2], self.env["DIRECTOR"], self.text, old)
        self.entry["prompt"] = old
        self.entry["ui"]["final"] = old
        body, expected = helper.prepare(self.entry, self.item, self.new, self.env, rule)
        self.assertNotIn(helper.LEGACY_ONE_TAKE_KEEP, body["prompt"])
        self.assertIn(rule, body["prompt"])
        self.assertEqual(body["ui"]["final"], body["prompt"])
        self.assertEqual(body["ui"]["f"], {"style": self.new})
        self.assertEqual(expected[self.env["SEED"]], self.item[2][self.env["SEED"]])
        (self.home / "index.html").write_text("const ONE_TAKE_KEEP = " + json.dumps(rule) + ";\n", encoding="utf-8")
        self.assertEqual(helper.one_take_rule(self.home), rule)

    def test_expected_style_limits_changes_and_excludes_running_jobs(self):
        other = copy.deepcopy(self.entry)
        other["id"] = "different-style"
        other["ui"]["f"]["style"] = "A separately customized style."
        current = copy.deepcopy(self.entry)
        current["id"] = "already-updated"
        current["prompt"] = self.text.replace(self.old, self.new)
        current["ui"]["f"]["style"] = self.new
        running = copy.deepcopy(self.entry)
        running["id"] = "running"
        pending = [copy.deepcopy(self.item), [8, other["id"], {}, {}, []],
                   [9, current["id"], helper.patch_graph(self.item[2], self.env["DIRECTOR"], self.text, current["prompt"]), {}, []]]
        history = {entry["id"]: entry for entry in (self.entry, other, current, running)}
        queue = {"queue_pending": pending, "queue_running": [[6, running["id"], {}, {}, []]]}
        with patch.object(helper, "HOME", self.home), patch.object(helper, "entries", return_value=history), patch.object(helper, "request", return_value=queue) as request:
            counts = helper.run(self.new, expected_style=self.old)
        request.assert_called_once_with("http://127.0.0.1:8188/queue")
        self.assertEqual(counts["pending_targets"], 3)
        self.assertEqual(counts["prepared"], 1)
        self.assertEqual(counts["different_style"], 1)
        self.assertEqual(counts["already_current"], 1)
        self.assertEqual(counts["unmatched"], 0)
        self.assertFalse((self.home / "queue-style-backups").exists())

    def test_apply_uses_existing_bulk_api_preserves_position_and_never_reads_media(self):
        env = self.env
        rule = "One continuous take: preserve the newly established camera viewpoint."
        old = self.text.replace("Keep synthetic clothing.", "Keep synthetic clothing. " + helper.LEGACY_ONE_TAKE_KEEP)
        self.item[2] = helper.patch_graph(self.item[2], env["DIRECTOR"], self.text, old)
        self.entry["prompt"] = old
        (self.home / "index.html").write_text("const ONE_TAKE_KEEP = " + json.dumps(rule) + ";\n", encoding="utf-8")
        history = [copy.deepcopy(self.entry)]
        pending = [copy.deepcopy(self.item), [8, "foreign", {"untouched": True}, {}, []]]
        before_foreign = copy.deepcopy(pending[1])
        calls = []
        from simple_ui.bulk_progress import BulkProgress
        from simple_ui.queue_bulk import BuildCache
        from types import SimpleNamespace
        env.update(BULK_PROGRESS=BulkProgress(),BuildCache=BuildCache,HIST_DB=history, HLOCK=threading.Lock(), PLOCK=threading.Lock(), HIST=str(self.home / "history.json"),
                   PROGRESS={}, time=time)
        def save(path, value):
            Path(path).write_text(json.dumps(value), encoding="utf-8")
        save(env["HIST"], history)
        env["_save_json"] = save
        env["comfy"] = lambda path: io.BytesIO(json.dumps({"queue_running": [], "queue_pending": pending}).encode())
        def replace(identity, graph):
            item = next(item for item in pending if item[1] == identity)
            item[2] = copy.deepcopy(graph)
            return {"prompt_id": identity,"prompt_verified":True}
        env["replace_queued_prompt"] = replace
        tree = ast.parse((self.home / "server.py").read_text(encoding="utf-8"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ("bulk_edit_queue","commit_bulk_history")]
        exec(compile(ast.Module(body=functions, type_ignores=[]), "synthetic-bulk", "exec"), env)
        def apply(changes):
            for change in changes:replace(change['id'],change['prompt'])
            env['commit_bulk_history'](changes)
            return changes,[]
        env['bulk_queue_editor']=lambda:SimpleNamespace(apply=apply)
        def request(url, body=None):
            calls.append((url, body is not None))
            if url.endswith("/queue"):
                return copy.deepcopy({"queue_pending": pending, "queue_running": []})
            self.assertTrue(url.endswith("/api/queue/bulk-edit"))
            return env["bulk_edit_queue"](body)
        with patch.object(helper, "HOME", self.home), patch.object(helper, "request", request):
            counts = helper.run(self.new, apply=True, refresh_common=True, expected_style=self.old, disable_anchor=True)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(counts["verified"], 1)
        self.assertEqual(counts["failed"], 0)
        self.assertEqual(pending[0][0:2], [7, "owned"])
        self.assertEqual(pending[1], before_foreign)
        self.assertEqual(history[0]["ui"]["shots"], self.entry["ui"]["shots"])
        self.assertEqual(history[0]["ui"]["f"]["keep"], self.entry["ui"]["f"]["keep"])
        self.assertIn(rule, history[0]["prompt"])
        self.assertFalse(history[0]["anchor"])
        self.assertNotIn(env["ANCHOR"],pending[0][2])
        self.assertNotIn(helper.LEGACY_ONE_TAKE_KEEP, history[0]["prompt"])
        self.assertTrue(all("/view" not in url and "/history/" not in url and "/interrupt" not in url for url, _ in calls))
        self.assertTrue(all(isinstance(value, int) for value in counts.values()))
        from scripts.restore_anchored_reference import prepare_restore
        def anchored(entry,item,style,env):
            return prepare_restore(entry,item,style,env,self.entry,(self.new,))
        with patch.object(helper,"HOME",self.home),patch.object(helper,"request",request):
            restored=helper.run(self.old,apply=True,prepare_fn=anchored)
        self.assertEqual(restored['updated'],1)
        self.assertEqual(restored['verified'],1)
        self.assertEqual(restored['failed'],0)
        self.assertTrue(history[0]['anchor'])
        self.assertIn(env['ANCHOR'],pending[0][2])
        self.assertEqual(pending[0][0:2],[7,'owned'])
        self.assertEqual(pending[1],before_foreign)

        # Exercise opening-scene edits through the same real bulk handler.
        from scripts.add_queued_opening_pose import prepare_opening
        prefix = "Synthetic opening pose instruction."
        original_shots = copy.deepcopy(history[0]["ui"]["shots"])
        original_form = copy.deepcopy(history[0]["ui"]["f"])
        def opening(entry, item, style, env):
            return prepare_opening(entry, item, style, env, prefix)
        with patch.object(helper, "HOME", self.home), patch.object(helper, "request", request):
            inserted = helper.run(self.old, apply=True, prepare_fn=opening)
            repeated = helper.run(self.old, apply=True, prepare_fn=opening)
        self.assertEqual(inserted["updated"], 1)
        self.assertEqual(inserted["verified"], 1)
        self.assertEqual(inserted["failed"], 0)
        self.assertEqual(repeated["already_current"], 1)
        self.assertEqual(repeated["updated"], 0)
        self.assertEqual(history[0]["ui"]["shots"][0], [original_shots[0][0], prefix + "\n\n" + original_shots[0][1]])
        self.assertEqual(history[0]["ui"]["f"], original_form)
        self.assertTrue(history[0]["anchor"])
        self.assertEqual(pending[0][0:2], [7, "owned"])
        self.assertEqual(pending[1], before_foreign)


if __name__ == "__main__":
    unittest.main()
