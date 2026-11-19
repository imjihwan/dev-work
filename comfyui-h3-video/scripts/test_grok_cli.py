"""Synthetic Grok transport tests; never logs in or contacts a provider."""
import importlib.util
import io
import io
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
from grok_cli import GrokCLI, PROFILE, TIMEOUT_SECONDS, clean_progress
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
        process.stdout=io.BytesIO(wire({"reply":"Synthetic"}))
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
            process.stdout=io.BytesIO(output)
            with patch.object(c,"ready",return_value=True),patch("grok_cli.subprocess.Popen",return_value=process):
                with self.assertRaises(ValueError) as error:c.complete("Static",{"idea":"SYNTHETIC"},helper.GROK_REPLY_SCHEMA,threading.Event())
                self.assertNotIn("PRIVATE",str(error.exception))
        process.stdout=io.BytesIO(wire(good))
        with patch.object(c,"ready",return_value=True),patch("grok_cli.subprocess.Popen",return_value=process):
            self.assertEqual(c.complete("Static",{"idea":"SYNTHETIC"},helper.GROK_REPLY_SCHEMA,threading.Event()),good)

    def test_empty_init_variants_and_identical_duplicate_notices_are_compatible(self):
        init={'type':'system','subtype':'init','apiKeySource':'oauth','model':'grok-4.7'}
        result={'type':'result','stop_reason':'end_turn','structured_output':{'reply':'Synthetic'}}
        cases=[[init,result],[{**init,'tools':None,'skills':{},'mcp_servers':[]},result],
               [init,{**init,'tools':[],'skills':[],'mcp_servers':[]},result],
               [{k:v for k,v in init.items() if k!='model'},init,result]]
        for events in cases:
            c=GrokCLI('synthetic');process=MagicMock();process.stdout=io.BytesIO(b'\n'.join(json.dumps(e).encode() for e in events));process.poll.return_value=0;process.returncode=0
            with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.subprocess.Popen',return_value=process):
                self.assertEqual(c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event()),{'reply':'Synthetic'})
            self.assertEqual(record.call_args.args[0]['outcome'],'ok')

    def test_init_failure_has_exact_reason_without_auth_or_tool_details(self):
        first=json.loads(wire({}).splitlines()[0]);result=json.loads(wire({}).splitlines()[1])
        cases=[([{**first,'tools':['PRIVATE_TOOL']},result],'init_tools_present'),
               ([{**first,'skills':['PRIVATE_SKILL']},result],'init_skills_present'),
               ([{**first,'mcp_servers':[{'name':'PRIVATE_MCP'}]},result],'init_mcp_present'),
               ([{**first,'apiKeySource':'user'},result],'init_auth_source'),
               ([{**first,'model':'grok-4.7'},{**first,'model':'other-model'},result],'init_changed'),
               ([first,result,first],'init_after_result')]
        for events,reason in cases:
            c=GrokCLI('synthetic');process=MagicMock();process.stdout=io.BytesIO(b'\n'.join(json.dumps(e).encode() for e in events));process.poll.return_value=0;process.returncode=0
            with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.subprocess.Popen',return_value=process):
                with self.assertRaises(ValueError) as error:c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event())
            self.assertEqual(record.call_args.args[0]['failure_reason'],reason);self.assertNotIn('PRIVATE',str(error.exception));self.assertNotIn('PRIVATE',json.dumps(record.call_args.args[0]))

    def schema_events(self, *, partial=True, init_tools=None, result=True):
        init=json.loads(wire({}).splitlines()[0])
        if init_tools is not None:init['tools']=init_tools
        tool={'type':'tool_use','id':'synthetic-output-1','name':'StructuredOutput','input':{'reply':'PRIVATE_INPUT'}}
        events=[init]
        if partial:
            events.extend([
                {'type':'stream_event','event':{'type':'message_start'}},
                {'type':'stream_event','event':{'type':'content_block_start','index':1,'content_block':{**tool,'input':{}}}},
                {'type':'stream_event','event':{'type':'content_block_delta','index':1,'delta':{'type':'input_json_delta','partial_json':'{"reply":"PRIVATE_INPUT"}'}}},
                {'type':'stream_event','event':{'type':'content_block_stop','index':1}},
                {'type':'stream_event','event':{'type':'message_stop'}}])
        events.extend([{'type':'assistant','message':{'content':[tool]}},
            {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':tool['id'],'content':'PRIVATE_FORMATTER_RESULT'}]}}])
        if result:events.append({'type':'result','stop_reason':'end_turn','is_error':False,'structured_output':{'reply':'Synthetic final'}})
        return events

    def run_schema_events(self,events):
        c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=0;process.returncode=0
        process.stdout=io.BytesIO(b'\n'.join(json.dumps(e).encode() for e in events));updates=[]
        with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.subprocess.Popen',return_value=process) as launch:
            value=c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event(),on_progress=updates.append)
        self.assertNotIn('PRIVATE',json.dumps(record.call_args.args[0]));self.assertNotIn('PRIVATE',json.dumps(updates))
        self.assertEqual(launch.call_count,1)
        return value,record.call_args.args[0]

    def test_internal_formatter_stream_and_tool_result_reach_validated_final_without_echo(self):
        value,metrics=self.run_schema_events(self.schema_events())
        self.assertEqual(value,{'reply':'Synthetic final'});self.assertEqual(metrics['schema_output_calls'],1)
        self.assertEqual(metrics['outcome'],'ok')

    def test_internal_formatter_can_be_advertised_or_only_appear_as_assistant_frame(self):
        for tools in (None,['StructuredOutput']):
            value,metrics=self.run_schema_events(self.schema_events(partial=False,init_tools=tools))
            self.assertEqual(value,{'reply':'Synthetic final'});self.assertEqual(metrics['schema_output_calls'],1)

    def test_formatter_input_never_substitutes_for_missing_or_failed_final_result(self):
        for events in (self.schema_events(result=False),
                       self.schema_events()[:-1]+[{'type':'result','stop_reason':'end_turn','is_error':True,'structured_output':{'reply':'PRIVATE_INPUT'}}],
                       self.schema_events()[:-1]+[{'type':'result','stop_reason':'max_tokens','structured_output':{'reply':'PRIVATE_INPUT'}}]):
            with self.assertRaises(ValueError):self.run_schema_events(events)

    def test_formatter_does_not_allow_other_tools_server_tools_or_mixed_init(self):
        for variant in ('other_tool','server_tool','mixed_init'):
            events=self.schema_events(partial=False)
            if variant=='mixed_init':events[0]['tools']=['StructuredOutput','PRIVATE_FILE_TOOL']
            elif variant=='server_tool':events[1]['message']['content'][0]['type']='server_tool_use'
            else:events[1]['message']['content'][0]['name']='PRIVATE_FILE_TOOL'
            with self.assertRaises(ValueError) as error:self.run_schema_events(events)
            self.assertNotIn('PRIVATE',str(error.exception))

    def test_orphan_input_json_and_unrelated_user_messages_are_not_formatter_results(self):
        for extra in ({'type':'stream_event','event':{'type':'content_block_delta','index':9,'delta':{'type':'input_json_delta','partial_json':'PRIVATE'}}},
                      {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'unknown','content':'PRIVATE'}]}},
                      {'type':'user','message':{'content':[{'type':'text','text':'PRIVATE'}]}}):
            events=self.schema_events();events.insert(-1,extra)
            with self.assertRaises(ValueError) as error:self.run_schema_events(events)
            self.assertNotIn('PRIVATE',str(error.exception))

    def test_cli_formatter_correction_stays_in_one_process_and_only_final_object_is_returned(self):
        first=self.schema_events(result=False)
        second=self.schema_events(partial=False)[1:]
        second=json.loads(json.dumps(second).replace('synthetic-output-1','synthetic-output-2'))
        value,metrics=self.run_schema_events(first+second)
        self.assertEqual(value,{'reply':'Synthetic final'});self.assertEqual(metrics['schema_output_calls'],2)

    def test_web_search_is_off_for_app_plans_and_on_only_for_isolated_research(self):
        c=GrokCLI('synthetic')
        default=c.command(Path('synthetic'),'Static',helper.GROK_REPLY_SCHEMA)
        research=c.command(Path('synthetic'),'Static',helper.GROK_REPLY_SCHEMA,web_search=True)
        self.assertIn('--disable-web-search',default);self.assertNotIn('--disable-web-search',research)
        self.assertEqual(default[default.index('--max-turns')+1],'1');self.assertEqual(research[research.index('--max-turns')+1],'6')
        for command in (default,research):self.assertIn('--deny',command);self.assertIn('--no-subagents',command)

    def test_hosted_web_search_and_page_read_are_allowed_only_in_research_mode(self):
        init=json.loads(wire({}).splitlines()[0])
        search={'type':'server_tool_use','id':'synthetic-search','name':'web_search','input':{'query':'PRIVATE_QUERY'}}
        page={'type':'tool_use','id':'synthetic-page','name':'Web search:','input':{}}
        events=[init,{'type':'stream_event','event':{'type':'content_block_start','index':1,'content_block':search}},
            {'type':'stream_event','event':{'type':'content_block_delta','index':1,'delta':{'type':'input_json_delta','partial_json':'PRIVATE_QUERY'}}},
            {'type':'stream_event','event':{'type':'content_block_stop','index':1}},
            {'type':'assistant','message':{'content':[search,{'type':'web_search_tool_result','tool_use_id':'synthetic-search','content':[{'type':'web_search_result','url':'https://docs.python.org/3/','title':'Synthetic public docs'}]},page]}},
            {'type':'user','message':{'content':[{'type':'tool_result','tool_use_id':'synthetic-page','content':'PRIVATE_PAGE'}]}},
            {'type':'result','stop_reason':'end_turn','structured_output':{'reply':'Synthetic research'}}]
        c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=0;process.returncode=0
        for enabled in (False,True):
            process.stdout=io.BytesIO(b'\n'.join(json.dumps(e).encode() for e in events))
            with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.subprocess.Popen',return_value=process):
                if enabled:
                    self.assertEqual(c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event(),web_search=True),{'reply':'Synthetic research'})
                    self.assertEqual(record.call_args.args[0]['web_search_calls'],1);self.assertEqual(record.call_args.args[0]['web_search_results'],1)
                else:
                    with self.assertRaises(ValueError):c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event())
            self.assertNotIn('PRIVATE',json.dumps(record.call_args.args[0]))

    def test_failed_search_attempt_without_source_results_is_not_completed_research(self):
        init=json.loads(wire({}).splitlines()[0])
        events=[init,{'type':'assistant','message':{'content':[
            {'type':'server_tool_use','id':'synthetic-failed','name':'web_search','input':{}},
            {'type':'web_search_tool_result','tool_use_id':'synthetic-failed','content':{'type':'web_search_tool_result_error','error_code':'unavailable'}}]}},
            {'type':'result','stop_reason':'end_turn','structured_output':{'reply':'Synthetic reply'}}]
        c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=0;process.returncode=0
        process.stdout=io.BytesIO(b'\n'.join(json.dumps(e).encode() for e in events))
        with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.subprocess.Popen',return_value=process):
            with self.assertRaises(ValueError):c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event(),web_search=True)
        self.assertEqual(record.call_args.args[0]['failure_reason'],'missing_web_search')

    def test_research_without_actual_search_never_counts_as_searched(self):
        c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=0;process.returncode=0
        process.stdout=io.BytesIO(wire({'reply':'Synthetic unsearched reply'}))
        with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.subprocess.Popen',return_value=process):
            with self.assertRaises(ValueError):c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event(),web_search=True)
        self.assertEqual(record.call_args.args[0]['failure_reason'],'missing_web_search')

    def test_cancelled_response_is_never_returned(self):
        c=GrokCLI("synthetic");cancel=threading.Event();cancel.set();process=MagicMock();process.poll.return_value=None;process.stdout=io.BytesIO(b'')
        with patch.object(c,"ready",return_value=True),patch("grok_cli.subprocess.Popen",return_value=process):
            with self.assertRaisesRegex(RuntimeError,"취소"):c.complete("Static",{},helper.GROK_REPLY_SCHEMA,cancel)
        process.terminate.assert_called_once()

    def test_live_deltas_update_stages_before_exit_without_exposing_reasoning(self):
        c=GrokCLI('synthetic');updates=[]
        init=json.loads(wire({}).splitlines()[0])
        events=[init,{'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'thinking_delta','thinking':'PRIVATE_THOUGHT'}}},
                {'type':'stream_event','event':{'type':'content_block_delta','delta':{'type':'text_delta','text':'PRIVATE_PARTIAL_JSON'}}},
                {'type':'result','stop_reason':'end_turn','structured_output':{'reply':'Synthetic final'}}]
        # A real child process emits fragments before it exits; no network or auth.
        script="import json,time,sys;events=json.loads(sys.argv[1]);[(print(json.dumps(e),flush=True),time.sleep(.08)) for e in events]"
        command=[sys.executable,'-u','-c',script,json.dumps(events)]
        with patch.object(c,'ready',return_value=True),patch.object(c,'command',return_value=command),patch.object(c,'_record_metrics'):
            draft=c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event(),on_progress=updates.append)
        self.assertEqual(draft,{'reply':'Synthetic final'})
        self.assertTrue({'waiting','thinking','answer','check'}.issubset({u['cli_stage'] for u in updates}))
        self.assertEqual(max(u['cli_signals'] for u in updates),2)
        self.assertNotIn('PRIVATE',json.dumps(updates))

    def test_streaming_silence_is_cancellable_and_partial_text_never_becomes_a_reply(self):
        c=GrokCLI('synthetic');cancel=threading.Event();updates=[]
        init=json.loads(wire({}).splitlines()[0])
        script="import sys,time;print(sys.argv[1],flush=True);time.sleep(30)"
        command=[sys.executable,'-u','-c',script,json.dumps(init)]
        def progress(info):
            updates.append(info)
            if info['cli_stage']=='waiting':cancel.set()
        with patch.object(c,'ready',return_value=True),patch.object(c,'command',return_value=command),patch.object(c,'_record_metrics'):
            with self.assertRaisesRegex(RuntimeError,'취소'):c.complete('Static',{},helper.GROK_REPLY_SCHEMA,cancel,on_progress=progress)
        self.assertTrue(updates)

    def test_stream_limits_and_metadata_allowlist(self):
        from grok_cli import clean_progress
        self.assertEqual(clean_progress({'cli_stage':'thinking','cli_signals':3,'cli_idle_s':.2,'text':'PRIVATE','cli_elapsed_s':float('nan'),'cli_limit_s':True}),{'cli_stage':'thinking','cli_signals':3,'cli_idle_s':.2})
        self.assertEqual(clean_progress({'cli_stage':'PRIVATE','cli_signals':-1}),{})
        c=GrokCLI('synthetic')
        for output in (b'['*101,wire({})+b'\n'+wire({})):
            process=MagicMock();process.stdout=io.BytesIO(output);process.poll.return_value=0;process.returncode=0
            with patch.object(c,'ready',return_value=True),patch('grok_cli.MAX_EVENT_BYTES',100),patch('grok_cli.subprocess.Popen',return_value=process):
                with self.assertRaises(ValueError):c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event())

    def test_failure_stage_is_reported_without_response_or_task_text(self):
        init=json.loads(wire({}).splitlines()[0])
        cases=[({'type':'error','message':'PRIVATE_PROVIDER_TEXT'},'provider_error_event'),
               ({'type':'user','message':'PRIVATE_TASK_TEXT'},'unexpected_user_event'),
               ({'type':'stream_event','event':{'type':'content_block_start','content_block':{'type':'tool_use','name':'PRIVATE_TOOL'}}},'tool_event'),
               ({'type':'result','stop_reason':'end_turn'},'missing_structured_output')]
        for event,reason in cases:
            c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=0;process.returncode=0
            process.stdout=io.BytesIO(b'\n'.join(json.dumps(item).encode() for item in [init,event]))
            with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.subprocess.Popen',return_value=process):
                with self.assertRaises(ValueError) as error:c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event())
            self.assertEqual(record.call_args.args[0]['failure_reason'],reason)
            self.assertNotIn('PRIVATE',str(error.exception));self.assertNotIn('PRIVATE',json.dumps(record.call_args.args[0]))

    def test_late_response_after_old_three_minute_limit_can_complete(self):
        c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=0;process.returncode=0
        process.stdout=io.BytesIO(wire({'reply':'Synthetic late reply'}))
        clock=[0];updates=[]
        def progress(info):
            updates.append(info)
            if info.get('cli_stage')=='waiting':clock[0]=181
        with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.time.monotonic',side_effect=lambda:clock[0]),patch('grok_cli.subprocess.Popen',return_value=process):
            value=c.complete('Static',{'idea':'PRIVATE_REQUEST'},helper.GROK_REPLY_SCHEMA,threading.Event(),effort='medium',on_progress=progress)
        self.assertEqual(value['reply'],'Synthetic late reply');self.assertEqual(record.call_args.args[0]['outcome'],'ok')
        self.assertEqual(record.call_args.args[0]['limit_s'],300);self.assertEqual(updates[-1]['cli_elapsed_s'],181)
        self.assertNotIn('PRIVATE',json.dumps(record.call_args.args[0]));self.assertNotIn('PRIVATE',json.dumps(updates))
        process.terminate.assert_not_called()

    def assert_timeout(self,effort,limit,**kwargs):
        c=GrokCLI('synthetic');process=MagicMock();process.poll.return_value=None;process.returncode=-15
        process.stdout=io.BytesIO(b'');clock=[0];calls=[]
        def wait(timeout=None):
            if timeout==.2:
                calls.append(1);clock[0]=limit+1
                raise subprocess.TimeoutExpired('synthetic',.2)
            return -15
        process.wait.side_effect=wait
        with patch.object(c,'ready',return_value=True),patch.object(c,'_record_metrics') as record,patch('grok_cli.time.monotonic',side_effect=lambda:clock[0]),patch('grok_cli.subprocess.Popen',return_value=process):
            with self.assertRaisesRegex(RuntimeError,str(limit)):c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event(),effort=effort,**kwargs)
        self.assertEqual(len(calls),1);self.assertEqual(record.call_args.args[0]['outcome'],'timeout');process.terminate.assert_called_once()
        self.assertEqual(record.call_args.args[0]['limit_s'],limit)

    def test_per_effort_timeout_is_bounded_and_does_not_retry(self):
        for effort,limit in TIMEOUT_SECONDS.items():self.assert_timeout(effort,limit)

    def test_remaining_request_budget_overrides_long_effort(self):
        self.assert_timeout('xhigh',40,timeout_s=40)

    def test_numeric_diagnostics_and_disk_failure_cannot_expose_text(self):
        with tempfile.TemporaryDirectory() as directory:
            c=GrokCLI(directory);process=MagicMock();process.poll.return_value=0;process.returncode=0
            process.stdout=io.BytesIO(wire({'reply':'PRIVATE_REPLY'}))
            with patch.object(c,'ready',return_value=True),patch('grok_cli.subprocess.Popen',return_value=process):
                self.assertEqual(c.complete('PRIVATE_SYSTEM',{'idea':'PRIVATE_REQUEST'},helper.GROK_REPLY_SCHEMA,threading.Event())['reply'],'PRIVATE_REPLY')
            path=Path(directory)/'grok-timings.jsonl';text=path.read_text(encoding='utf-8');self.assertNotIn('PRIVATE',text);self.assertEqual(json.loads(text)['outcome'],'ok')
            path.unlink();path.mkdir()
            process.stdout=io.BytesIO(wire({'reply':'PRIVATE_REPLY'}))
            with patch.object(c,'ready',return_value=True),patch('grok_cli.subprocess.Popen',return_value=process):
                self.assertEqual(c.complete('Static',{},helper.GROK_REPLY_SCHEMA,threading.Event())['reply'],'PRIVATE_REPLY')

    def test_restart_preparation_refuses_active_shared_request_without_printing_text(self):
        with tempfile.TemporaryDirectory() as directory:
            comfy=Path(directory)/'ComfyUI';ui=comfy/'simple_ui';ui.mkdir(parents=True)
            (ui/'production-chat.json').write_text(json.dumps({'active':{'id':'PRIVATE_ID'},'messages':[{'text':'PRIVATE_WORK'}]}),encoding='utf-8')
            result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/prepare_ui_restart.py')],env={**os.environ,'SIMPLEUI_COMFY':str(comfy)},capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertIn('assistant operation',result.stderr+result.stdout);self.assertNotIn('PRIVATE',result.stderr+result.stdout)


if __name__ == "__main__": unittest.main()
