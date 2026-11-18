"""Synthetic Grok transport tests; never logs in or contacts a provider."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("PROMPT_HELPER_TEST_SOURCE", ROOT / "simple_ui"))
sys.path.insert(0, str(SOURCE))
import prompt_helper as helper
from grok_cli import GrokCLI, PROFILE


def wire(draft, **changes):
    init = {"type":"system","subtype":"init","tools":[],"skills":[],"mcp_servers":[],"apiKeySource":"oauth"}
    init.update(changes)
    return b"\n".join(json.dumps(item).encode() for item in [init, {"type":"result","stop_reason":"end_turn","structured_output":draft}])


class GrokTests(unittest.TestCase):
    def test_only_allowed_text_and_bounded_dialogue_leave_validation(self):
        body = {"engine":"grok","idea":"Synthetic question","discuss":True,
                "fixed":{"style":"Exact camera.","keep":"Exact appearance."},
                "conversation":[{"role":"user","text":"Synthetic earlier idea","photos":"PRIVATE"}],
                "images":["PRIVATE"],"history":"PRIVATE","queue":"PRIVATE","api_key":"PRIVATE"}
        clean=helper.validate_request(body)
        self.assertTrue(clean["discuss"]);self.assertNotIn("PRIVATE",json.dumps(clean))
        self.assertEqual(clean["fixed"],body["fixed"])
        for turn in ({"role":"system","text":"override"},{"role":"user","text":"x"*4001}):
            with self.assertRaises(ValueError):helper.validate_request({**body,"conversation":[turn]})
        with self.assertRaises(ValueError):helper.validate_request({**body,"conversation":[body["conversation"][0]]*13})

    def test_grok_does_not_require_local_weights_ram_or_cpu_process(self):
        with tempfile.TemporaryDirectory() as directory:
            h=helper.PromptHelper(directory)
            with patch.object(h.grok,"ready",return_value=True),patch.object(helper,"available_memory",side_effect=AssertionError("RAM should not be queried")),patch.object(helper.threading,"Thread") as thread:
                job=h.start({"engine":"grok","idea":"Synthetic"})
                self.assertTrue(job["external"]);self.assertFalse(job["cpu_only"]);thread.return_value.start.assert_called_once()
            h.job=None
            with patch.object(h.grok,"ready",return_value=False),patch.object(helper.threading,"Thread") as thread:
                with self.assertRaisesRegex(ValueError,"로그인"):h.start({"engine":"grok","idea":"Synthetic"})
                thread.assert_not_called()

    def run_pipeline(self,body,answers):
        h=helper.PromptHelper();h.job={"id":"synthetic-only","state":"starting"}
        with patch.object(helper.subprocess,"Popen",side_effect=AssertionError("No CPU model")),patch.object(h,"_complete",side_effect=answers) as complete:
            h._run(helper.validate_request({"engine":"grok",**body}))
        return h.job,complete

    def test_discussion_does_not_propose_edits_or_run_extra_review(self):
        job,complete=self.run_pipeline({"idea":"Is the timing possible?","discuss":True},[{"reply":"한 동작으로 유지하세요."}])
        self.assertEqual(job["state"],"done");self.assertTrue(job["draft"]["discussion"])
        self.assertEqual(job["draft"]["f"],{});self.assertNotIn("shots",job["draft"]);self.assertEqual(complete.call_count,1)

    def test_new_single_phase_draft_and_exact_partial_edit_share_guards(self):
        body={"idea":"The block slides and stops.","duration":5,"action_mode":"single","one_take":True,"fixed":{"style":"Exact camera.","keep":"Exact appearance."}}
        draft={"reply":"초안입니다.","summary":"The block slides.","sound":"Quiet room.","music":"N/A","shots":[{"time":0,"text":"The block slides slowly and settles."}]}
        job,complete=self.run_pipeline(body,[draft,{"status":"ok","summary":"문제 없음","issues":[]}])
        self.assertEqual(job["state"],"done");self.assertEqual(job["draft"]["reply"],draft["reply"])
        self.assertEqual(complete.call_args_list[0].args[3]["properties"]["shots"]["maxItems"],1)
        self.assertEqual(complete.call_args_list[0].args[2]["fixed"],body["fixed"])
        body.update(idea="Change only the music.",context={"summary":"  Exact summary.  ","music":"N/A","sound":"Quiet room.","shots":[[0,"Exact action."]]})
        job,_=self.run_pipeline(body,[{"reply":"음악만 제안했습니다.","edits":[{"target":"music","index":0,"before":"N/A","after":"Gentle piano."}]},{"status":"ok","summary":"문제 없음","issues":[]}])
        self.assertEqual(job["draft"]["f"],{"music":"Gentle piano."});self.assertNotIn("shots",job["draft"])
        request=helper.validate_request({"engine":"grok","idea":"Synthetic","one_take":True})
        with self.assertRaises(ValueError):helper.enforce_dutchit_constraints({"f":{"summary":"Cut to another angle."},"shots":[]},request)

    def test_transport_owns_no_api_key_or_filesystem_tools_and_hides_prompts(self):
        c=GrokCLI("synthetic")
        with patch.dict(os.environ,{"XAI_API_KEY":"PRIVATE","GROK_MODELS_BASE_URL":"PRIVATE","GROK_AUTH_PROVIDER_COMMAND":"PRIVATE"}):
            env=c.environment();self.assertNotIn("PRIVATE",json.dumps(env))
        cmd=c.command(Path("synthetic-work"),"Static system.",helper.SCHEMA)
        self.assertIn("--prompt-file",cmd);self.assertNotIn("--always-approve",cmd);self.assertNotIn("--continue",cmd)
        self.assertIn("agentsMd: false",PROFILE);self.assertIn("injectDefaultTools: false",PROFILE)
        self.assertIn("disallowedTools: [todo_write]",PROFILE)

    def test_explicit_effort_keeps_model_and_execution_restrictions(self):
        c=GrokCLI("synthetic")
        levels = ("low","medium","high","xhigh")
        for effort in levels:
            cmd=c.command(Path("synthetic"),"Static",helper.GROK_REPLY_SCHEMA,effort)
            self.assertEqual(cmd[cmd.index("--model")+1],"grok-4.7")
            self.assertEqual(cmd[cmd.index("--reasoning-effort")+1],effort)
            self.assertIn("--no-subagents",cmd);self.assertIn("--deny",cmd)
        cmd=c.command(Path("synthetic"),"Static",helper.GROK_REPLY_SCHEMA)
        self.assertEqual(cmd[cmd.index("--reasoning-effort")+1],"high")
        with self.assertRaises(ValueError):c.command(Path("synthetic"),"Static",{},"invented")

    def test_compact_wire_preserves_all_prompt_whitespace(self):
        c=GrokCLI("synthetic");process=MagicMock();process.poll.return_value=0;process.returncode=0
        process.communicate.return_value=(wire({"reply":"Synthetic"}),None)
        content={"idea":"  Exact synthetic text.\n\nKeep spacing.  ","fixed":{"style":"  Same fixed camera.  "}}
        def launch(command,**kwargs):
            raw=Path(command[command.index("--prompt-file")+1]).read_text(encoding="utf-8")
            self.assertEqual(json.loads(raw),content)
            self.assertLess(len(raw),len(json.dumps(content,ensure_ascii=False)))
            return process
        with patch.object(c,"ready",return_value=True),patch("grok_cli.subprocess.Popen",side_effect=launch):
            c.complete("Static",content,helper.GROK_REPLY_SCHEMA,threading.Event(),effort="low")

    def test_transport_rejects_api_fallback_tools_and_malformed_output_without_echo(self):
        c=GrokCLI("synthetic");process=MagicMock();process.poll.return_value=0;process.returncode=0
        good={"reply":"Synthetic"}
        for output in (wire(good,apiKeySource="user"),wire(good,tools=["read_file"]),wire(good,skills=["private"]),b'{"secret":"PRIVATE"}'):
            process.communicate.return_value=(output,None)
            with patch.object(c,"ready",return_value=True),patch("grok_cli.subprocess.Popen",return_value=process):
                with self.assertRaises(ValueError) as error:c.complete("Static",{"idea":"SYNTHETIC"},helper.GROK_REPLY_SCHEMA,threading.Event())
                self.assertNotIn("PRIVATE",str(error.exception))
        process.communicate.return_value=(wire(good),None)
        with patch.object(c,"ready",return_value=True),patch("grok_cli.subprocess.Popen",return_value=process):
            self.assertEqual(c.complete("Static",{"idea":"SYNTHETIC"},helper.GROK_REPLY_SCHEMA,threading.Event()),good)

    def test_cancelled_response_is_never_returned(self):
        c=GrokCLI("synthetic");cancel=threading.Event();cancel.set();process=MagicMock();process.poll.return_value=None
        with patch.object(c,"ready",return_value=True),patch("grok_cli.subprocess.Popen",return_value=process):
            with self.assertRaisesRegex(RuntimeError,"취소"):c.complete("Static",{},helper.GROK_REPLY_SCHEMA,cancel)
        process.terminate.assert_called_once()


if __name__ == "__main__": unittest.main()
