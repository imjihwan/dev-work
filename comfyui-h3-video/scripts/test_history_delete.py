"""History deletion against a fake queue; no real jobs or result files are touched."""
import ast
import copy
import io
import json
from pathlib import Path
import threading
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
TREE = ast.parse((ROOT / "simple_ui/server.py").read_text(encoding="utf-8"))
FUNCTION = next(node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name=="delete_history")


class HistoryDeleteTests(unittest.TestCase):
    def setUp(self):
        self.entries=[{"id":"waiting","state":"queued"},{"id":"running","state":"queued"},{"id":"done","state":"done"}]
        self.pending=[[1,"waiting"],[2,"foreign-waiting"]]
        self.running=[[0,"running"]]
        self.calls=[];self.saved=[];self.fail=None;self.race=False;self.add_new=False
        self.env={"json":json,"HIST_DB":self.entries,"HIST":"unused","HLOCK":threading.Lock(),
            "QUEUE_EDIT_LOCK":threading.Lock(),"comfy":self.comfy,"_save_json":lambda _,data:self.saved.append(copy.deepcopy(data))}
        exec(compile(ast.Module(body=[FUNCTION],type_ignores=[]),"history-delete","exec"),self.env)

    def comfy(self,path,data=None,headers=None):
        body=json.loads(data) if data else None
        self.calls.append((path,body))
        if self.fail==path: raise urllib.error.URLError("offline")
        if path=="/queue" and body is None:
            return io.BytesIO(json.dumps({"queue_pending":self.pending,"queue_running":self.running}).encode())
        if path=="/queue":
            if self.race:
                self.running.append([1,"waiting"])
            self.pending=[item for item in self.pending if item[1] not in body["delete"]]
            if self.add_new: self.entries.append({"id":"newly-added","state":"queued"})
        elif path=="/interrupt":
            self.running=[item for item in self.running if item[1]!=body["prompt_id"]]
        else: raise AssertionError(path)
        return io.BytesIO(b"")

    def delete(self,body): return self.env["delete_history"](body)

    def test_selected_waiting_item_removed_from_both_places(self):
        result=self.delete({"ids":["waiting"]})
        self.assertEqual(result["ids"],["waiting"])
        self.assertEqual([e["id"] for e in self.entries],["running","done"])
        self.assertEqual(self.pending,[[2,"foreign-waiting"]])
        self.assertEqual(self.running,[[0,"running"]])
        self.assertEqual(self.calls[-1],("/interrupt",{"prompt_id":"waiting"}))

    def test_running_item_only_is_interrupted(self):
        self.delete({"ids":["running"]})
        self.assertEqual(self.running,[])
        self.assertEqual(self.pending,[[1,"waiting"],[2,"foreign-waiting"]])
        self.assertEqual(self.calls[-1],("/interrupt",{"prompt_id":"running"}))

    def test_clear_all_preserves_foreign_queue_and_newly_added_history(self):
        self.add_new=True
        result=self.delete({"all":True})
        self.assertEqual(result["total"],1)
        self.assertEqual(self.entries,[{"id":"newly-added","state":"queued"}])
        self.assertEqual(self.pending,[[2,"foreign-waiting"]])
        self.assertEqual(self.running,[])
        self.assertEqual([b for p,b in self.calls if p=="/interrupt"],[{"prompt_id":"waiting"},{"prompt_id":"running"}])

    def test_start_race_is_targeted_and_stopped(self):
        self.race=True
        self.delete({"ids":["waiting"]})
        self.assertEqual(self.running,[[0,"running"]])

    def test_completed_history_does_not_mutate_queue(self):
        self.delete({"ids":["done"]})
        self.assertEqual(self.calls,[("/queue",None)])
        self.assertEqual(len(self.saved),1)

    def test_queue_or_interrupt_failure_keeps_history_for_retry(self):
        for failure in ("/queue","/interrupt"):
            with self.subTest(failure=failure):
                self.setUp();self.fail=failure
                with self.assertRaises(urllib.error.URLError): self.delete({"ids":["waiting"]})
                self.assertEqual(len(self.entries),3)
                self.assertEqual(self.saved,[])

    def test_foreign_or_missing_id_never_mutates_queue(self):
        result=self.delete({"ids":["foreign-waiting","missing"]})
        self.assertEqual(result["ids"],[])
        self.assertEqual(self.calls,[])


if __name__=="__main__":unittest.main()
