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
from grok_cli import GrokCLI, PROFILE, TIMEOUT_SECONDS
import subprocess


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

    def test_late_response_after_old_three_minute_limit_can_complete(self):
        c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=0;process.returncode=0
        clock=[0];calls=[];updates=[]
        def communicate(**kwargs):
            calls.append(1)
            if len(calls)==1:
                clock[0]=181
                raise subprocess.TimeoutExpired('synthetic',.2)
            return wire({'reply':'Synthetic late reply'}),None
        process.communicate.side_effect=communicate
        with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.time.monotonic',side_effect=lambda:clock[0]),patch('grok_cli.subprocess.Popen',return_value=process):
            value=c.complete('Static',{'idea':'PRIVATE_REQUEST'},helper.GROK_REPLY_SCHEMA,threading.Event(),effort='medium',on_progress=updates.append)
        self.assertEqual(value['reply'],'Synthetic late reply');self.assertEqual(record.call_args.args[0]['outcome'],'ok')
        self.assertEqual(record.call_args.args[0]['limit_s'],300);self.assertEqual(updates[-1]['cli_elapsed_s'],181)
        self.assertNotIn('PRIVATE',json.dumps(record.call_args.args[0]));self.assertNotIn('PRIVATE',json.dumps(updates))
        process.terminate.assert_not_called()

    def test_per_effort_timeout_is_bounded_and_does_not_retry(self):
        for effort,limit in TIMEOUT_SECONDS.items():
            c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=None;process.returncode=-15
            clock=[0];calls=[]
            def communicate(**kwargs):
                calls.append(1);clock[0]=limit+1
                raise subprocess.TimeoutExpired('synthetic',.2)
            process.communicate.side_effect=communicate
            with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.time.monotonic',side_effect=lambda:clock[0]),patch('grok_cli.subprocess.Popen',return_value=process):
                with self.assertRaisesRegex(RuntimeError,str(limit)):c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event(),effort=effort)
            self.assertEqual(len(calls),1);self.assertEqual(record.call_args.args[0]['outcome'],'timeout');process.terminate.assert_called_once()

    def test_remaining_request_budget_overrides_long_effort(self):
        c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=None;process.returncode=-15
        clock=[0]
        def communicate(**kwargs):clock[0]=41;raise subprocess.TimeoutExpired('synthetic',.2)
        process.communicate.side_effect=communicate
        with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.time.monotonic',side_effect=lambda:clock[0]),patch('grok_cli.subprocess.Popen',return_value=process):
            with self.assertRaisesRegex(RuntimeError,'40'):c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event(),effort='xhigh',timeout_s=40)
        self.assertEqual(record.call_args.args[0]['limit_s'],40)

    def test_numeric_diagnostics_and_disk_failure_cannot_expose_text(self):
        with tempfile.TemporaryDirectory() as directory:
            c=GrokCLI(directory);process=MagicMock();process.poll.return_value=0;process.returncode=0
            process.communicate.return_value=(wire({'reply':'PRIVATE_REPLY'}),None)
            with patch.object(c,'ready',return_value=True),patch('grok_cli.subprocess.Popen',return_value=process):
                self.assertEqual(c.complete('PRIVATE_SYSTEM',{'idea':'PRIVATE_REQUEST'},helper.GROK_REPLY_SCHEMA,threading.Event())['reply'],'PRIVATE_REPLY')
            path=Path(directory)/'grok-timings.jsonl';text=path.read_text(encoding='utf-8');self.assertNotIn('PRIVATE',text);self.assertEqual(json.loads(text)['outcome'],'ok')
            path.unlink();path.mkdir()
            with patch.object(c,'ready',return_value=True),patch('grok_cli.subprocess.Popen',return_value=process):
                self.assertEqual(c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event())['reply'],'PRIVATE_REPLY')

    def test_restart_preparation_refuses_active_shared_request_without_printing_text(self):
        with tempfile.TemporaryDirectory() as directory:
            comfy=Path(directory)/'ComfyUI';ui=comfy/'simple_ui';ui.mkdir(parents=True)
            (ui/'production-chat.json').write_text(json.dumps({'active':{'id':'PRIVATE_ID'},'messages':[{'text':'PRIVATE_WORK'}]}),encoding='utf-8')
            result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/prepare_ui_restart.py')],env={**os.environ,'SIMPLEUI_COMFY':str(comfy)},capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('assistant operation',result.stderr+result.stdout);self.assertNotIn('PRIVATE',result.stderr+result.stdout)


if __name__ == "__main__": unittest.main()
