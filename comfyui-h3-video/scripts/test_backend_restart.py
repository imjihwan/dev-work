"""Synthetic restart protection tests; no live queue or personal files."""
import ast
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(os.environ.get('BACKEND_RESTART_TEST_SOURCE',ROOT/'simple_ui'))
TREE=ast.parse((SOURCE/'server.py').read_text(encoding='utf-8-sig'))
spec=importlib.util.spec_from_file_location('restart_backend',ROOT/'scripts/restart_backend.py')
RESTART=importlib.util.module_from_spec(spec);spec.loader.exec_module(RESTART)

def item(number,index):
    return [number,f'00000000-0000-4000-8000-{index:012d}',{'1':{'class_type':'SyntheticOutput','inputs':{'value':f'fixture-{index}'}}},{'client_id':'fixture-client','create_time':123},['1']]

class RestartGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.marker=Path(self.temp.name)/'backend-restart.tmp'
        self.env={'os':os,'json':json,'BACKEND_RESTART_HOLD':str(self.marker)}
        function=next(node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name=='backend_restart_hold')
        exec(compile(ast.Module(body=[function],type_ignores=[]),'<guard>','exec'),self.env)
        self.guard=self.env['backend_restart_hold']

    def test_absent_marker_keeps_normal_status(self):
        self.assertIsNone(self.guard());self.assertIsNone(self.guard('fixture'))

    def test_only_held_id_has_queued_status(self):
        self.marker.write_text(json.dumps({'jobs':{'fixture':2}}))
        self.assertTrue(self.guard());self.assertEqual(self.guard('fixture')['position'],2)
        self.assertEqual(self.guard('fixture')['state'],'queued');self.assertEqual(self.guard('fixture')['pct'],0)
        self.assertIsNone(self.guard('completed-old-item'))

    def test_invalid_marker_fails_closed(self):
        self.marker.write_text('not valid json')
        self.assertTrue(self.guard());self.assertEqual(self.guard('fixture')['state'],'queued')

    def test_status_hold_avoids_backend_queries_and_resets_old_progress(self):
        self.marker.write_text(json.dumps({'jobs':{'fixture':1}}))
        function=next(node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name=='_status')
        self.env.update(PLOCK=threading.Lock(),PROGRESS={'fixture':{'pct':91}},comfy=lambda *a: self.fail('Must not query backend'))
        exec(compile(ast.Module(body=[function],type_ignores=[]),'<status>','exec'),self.env)
        self.assertEqual(self.env['_status']('fixture')['state'],'queued')
        self.assertEqual(self.env['PROGRESS']['fixture']['pct'],0)

    def test_execution_start_resets_monotonic_old_progress(self):
        functions=[node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name in ('_bump','_on_message')]
        self.env.update(time=time,HLOCK=threading.Lock(),HIST_DB=[],PLOCK=threading.Lock(),PROGRESS={'fixture':{'pct':91,'classes':{}}})
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<progress>','exec'),self.env)
        self.env['_on_message']({'type':'execution_start','data':{'prompt_id':'fixture'}})
        self.assertEqual(self.env['PROGRESS']['fixture']['pct'],1)

    def test_mutating_post_rejected_before_parsing_input(self):
        handler=next(node for node in TREE.body if isinstance(node,ast.ClassDef) and node.name=='H')
        self.env.update(BaseHTTPRequestHandler=BaseHTTPRequestHandler,backend_restart_hold=lambda:True)
        exec(compile(ast.Module(body=[handler],type_ignores=[]),'<handler>','exec'),self.env)
        h=self.env['H'].__new__(self.env['H']);h.path='/api/generate';h.rfile=io.BytesIO(b'not inspected')
        h._json=lambda value,code=200:setattr(h,'result',(value,code))
        h.do_POST();self.assertEqual(h.result[1],503);self.assertEqual(h.rfile.tell(),0)

class ReplayTests(unittest.TestCase):
    def test_queue_and_interrupt_endpoints_allow_empty_success_responses(self):
        for data,expected in ((b'',{}),(b'  ',{}),(b'{"ok":true}',{'ok':True})):
            with patch.object(RESTART.urllib.request,'urlopen',return_value=io.BytesIO(data)):
                self.assertEqual(RESTART.api('http://synthetic.invalid','/queue',{'delete':[]}),expected)

    def test_running_first_and_heap_pending_sorted(self):
        running=item(9,1);low=item(-3,2);later=item(4,3)
        self.assertEqual(RESTART.ordered_items({'queue_running':[running],'queue_pending':[later,low]}),[running,low,later])

    def test_replay_preserves_payload_but_lets_append_counter_advance(self):
        original=item(91,1);before=copy.deepcopy(original);payload=RESTART.replay_body(original)
        self.assertNotIn('number',payload);self.assertEqual(payload['prompt_id'],original[1])
        self.assertEqual(payload['extra_data'],original[3]);self.assertEqual(payload['partial_execution_targets'],original[4])
        payload['prompt']['1']['inputs']['value']='changed fixture'
        self.assertEqual(original,before)

    def test_exact_replay_accepts_only_new_creation_timestamp(self):
        original=item(91,1);actual=copy.deepcopy(original);actual[0]=0;actual[3]['create_time']=456
        self.assertEqual(RESTART.verify_replay([original],{'queue_running':[actual],'queue_pending':[]},{}),(1,0))
        actual[2]['1']['inputs']['value']='unexpected alteration'
        with self.assertRaises(ValueError):RESTART.verify_replay([original],{'queue_running':[actual],'queue_pending':[]},{})

    def test_wrong_order_missing_or_foreign_job_is_rejected(self):
        a=item(0,1);b=item(1,2)
        for actual in ([b,a],[a],[a,b,item(2,3)]):
            with self.subTest(count=len(actual)),self.assertRaises(ValueError):
                RESTART.verify_replay([a,b],{'queue_running':actual[:1],'queue_pending':actual[1:]},{})

    def test_completed_prefix_during_restore_keeps_coverage(self):
        a=item(0,1);b=item(1,2)
        history={a[1]:{'status':{'status_str':'success'},'prompt':a}}
        self.assertEqual(RESTART.verify_replay([a,b],{'queue_running':[b],'queue_pending':[]},history),(1,1))

    def test_backend_output_target_reordering_is_not_a_workflow_change(self):
        a=item(0,1);a[4]=['1','2'];b=copy.deepcopy(a);b[4]=['2','1']
        self.assertEqual(RESTART.verify_replay([a],{'queue_running':[b],'queue_pending':[]},{}),(1,0))
        b[4]=['2']
        with self.assertRaises(ValueError):RESTART.verify_replay([a],{'queue_running':[b],'queue_pending':[]},{})

    def test_duplicate_or_invalid_identity_is_rejected(self):
        a=item(0,1)
        with self.assertRaises(ValueError):RESTART.ordered_items({'queue_running':[a],'queue_pending':[a]})
        a[1]='invalid'
        with self.assertRaises(ValueError):RESTART.ordered_items({'queue_running':[a],'queue_pending':[]})

if __name__=='__main__':unittest.main()
