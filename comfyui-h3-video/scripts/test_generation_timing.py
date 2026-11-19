"""Synthetic native timestamps and history only; never reads user media or jobs."""
import ast
import io
import json
import math
from pathlib import Path
import threading
import time
import unittest
import urllib.parse
from unittest.mock import MagicMock

ROOT=Path(__file__).resolve().parents[1]
TREE=ast.parse((ROOT/'simple_ui/server.py').read_text(encoding='utf-8-sig'))


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.row={'id':'synthetic','state':'queued','t':1,'images':['synthetic-reference.png']}
        self.save=MagicMock();self.gallery=MagicMock()
        self.env={'json':json,'math':math,'time':time,'urllib':__import__('urllib'),'HLOCK':threading.Lock(),'HIST_DB':[self.row],
                  'HIST':'synthetic-only','_save_json':self.save,'GALLERY':self.gallery,'backend_restart_hold':lambda pid:None,
                  'video_of':lambda entry:{'filename':'synthetic.mp4'},'PROGRESS':{},'PLOCK':threading.Lock()}
        functions=[n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name in ('execution_timing','hist_result','_status','_queue_state','_on_message','_bump')]
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<synthetic timing>','exec'),self.env)

    def entry(self,terminal='execution_success',end=85000):
        return {'status':{'status_str':'success' if terminal=='execution_success' else 'error','messages':[
            ['execution_start',{'timestamp':1000000}],['execution_cached',{'timestamp':1001000}],
            [terminal,{'timestamp':1000000+end}]]}}

    def test_generation_time_excludes_queue_wait_and_survives_ui_restarts(self):
        entry=self.entry(end=85123)
        self.env['comfy']=lambda path:io.BytesIO(json.dumps({'synthetic':entry}).encode())
        status=self.env['_status']('synthetic');self.env['hist_result']('synthetic',status)
        self.assertEqual(self.row['generation_seconds'],85.123)
        self.assertEqual(self.row['generation_started_at'],1000)
        self.assertEqual(self.row['generation_finished_at'],1085.123)
        self.assertNotEqual(self.row['generation_seconds'],self.row['t_end']-self.row['t'])
        self.assertEqual(self.gallery.remember.call_args.args[0][0]['generation_seconds'],85.123)

    def test_old_work_without_native_timestamps_is_not_estimated(self):
        for entry in ({},{'status':{'messages':[]}}, {'status':{'messages':[['execution_start',{'timestamp':1000}]]}}):
            self.assertEqual(self.env['execution_timing'](entry),{})

    def test_error_and_interruption_include_actual_execution_time(self):
        for event in ('execution_error','execution_interrupted'):
            self.assertEqual(self.env['execution_timing'](self.entry(event))['generation_seconds'],85)

    def test_invalid_or_reversed_timestamps_are_ignored(self):
        for stamp in (-1,True,float('nan'),float('inf'),'1000'):
            entry={'status':{'messages':[['execution_start',{'timestamp':stamp}],['execution_success',{'timestamp':2000}]]}}
            self.assertEqual(self.env['execution_timing'](entry),{})
        self.assertEqual(self.env['execution_timing'](self.entry(end=-10)),{})

    def test_latest_attempt_and_subsecond_values(self):
        entry=self.entry();entry['status']['messages'] += [['execution_start',{'timestamp':2000000}],['execution_success',{'timestamp':2000250}]]
        self.assertEqual(self.env['execution_timing'](entry)['generation_seconds'],.25)

    def test_late_timing_enriches_done_history_once(self):
        self.row.update(state='done',video={'filename':'synthetic.mp4'})
        status={'state':'done','video':self.row['video'],**self.env['execution_timing'](self.entry())}
        self.env['hist_result']('synthetic',status);self.env['hist_result']('synthetic',status)
        self.assertEqual(self.row['generation_seconds'],85);self.save.assert_called_once()

    def test_execution_start_is_recorded_before_registration_and_does_not_change_on_progress(self):
        self.env['_on_message']({'type':'execution_start','data':{'prompt_id':'synthetic','timestamp':1000000}})
        self.assertEqual(self.row['generation_started_at'],1000);self.assertFalse(self.env['PROGRESS']['synthetic']['elapsed_estimated'])
        self.save.assert_called_once()
        status=self.env['_queue_state']('synthetic',{'queue_running':[[1,'synthetic']],'queue_pending':[]})
        self.assertEqual(status['generation_started_at'],1000)
        self.env['stage_of']=lambda value:(15,82,'Synthetic')
        self.env['_on_message']({'type':'progress','data':{'prompt_id':'synthetic','node':'n','value':1,'max':2}})
        self.assertEqual(self.env['PROGRESS']['synthetic']['generation_started_at'],1000)

    def test_start_event_resets_an_observed_or_previous_attempt_clock(self):
        self.env['PROGRESS']['synthetic']={'classes':{},'pct':80,'generation_started_at':10,'elapsed_estimated':True,'elapsed_only':True}
        self.row.update(generation_seconds=99,generation_finished_at=100)
        self.env['_on_message']({'type':'execution_start','data':{'prompt_id':'synthetic','timestamp':2000000}})
        self.assertEqual(self.env['PROGRESS']['synthetic']['generation_started_at'],2000)
        self.assertNotIn('generation_seconds',self.row);self.assertNotIn('elapsed_only',self.env['PROGRESS']['synthetic'])


if __name__=='__main__':unittest.main()
