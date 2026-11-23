"""Fake conversations and temporary paths only. Never reads live transcripts."""
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simple_ui'))
from production_chat import ProductionChat,display_plan,clean_messages,LEGACY_COMMON_ERROR
from production_assistant import ProductionAssistant


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'production-chat.json';self.chat=ProductionChat(self.path)

    def test_atomic_import_once_and_private_fields_removed(self):
        old=[{'role':'user','text':'Synthetic question','images':['PRIVATE_IMAGE'],'token':'PRIVATE_TOKEN'},
            {'role':'assistant','text':'Synthetic reply','plan':{'state':'확인 대기','plan_id':'PRIVATE_EXECUTION_ID',
                'steps':[{'label':'Synthetic edit','changes':[{'before':'before','after':'after'}],'target':'PRIVATE_TARGET'}]}}]
        value=self.chat.import_once(0,old)
        self.assertNotIn('PRIVATE',json.dumps(value));self.assertIn('읽기 전용',value['messages'][1]['plan']['state'])
        self.assertEqual(ProductionChat(self.path).snapshot(),value)
        with self.assertRaises(ValueError):self.chat.import_once(value['revision'],old)
        with self.assertRaises(ValueError):self.chat.clear(0)
        cleared=self.chat.clear(value['revision']);self.assertEqual(cleared['messages'],[])
        with self.assertRaises(ValueError):self.chat.import_once(cleared['revision'],old)

    def test_late_reply_survives_browser_closure_and_request_history_is_server_owned(self):
        first=self.chat.begin(0,'synthetic-one','First synthetic question')
        self.assertEqual(first['conversation'],[])
        with self.assertRaises(ValueError):self.chat.clear(first['revision'])
        self.chat.progress('synthetic-one','model',1)
        done=self.chat.complete('synthetic-one','First synthetic answer')
        second=self.chat.begin(done['revision'],'synthetic-two','Second synthetic question')
        self.assertEqual([row['text'] for row in second['conversation']],['First synthetic question','First synthetic answer'])
        self.assertIsNone(self.chat.complete('synthetic-one','Duplicate late answer'))
        self.chat.complete('synthetic-two','Second synthetic answer')
        self.assertEqual(len(ProductionChat(self.path).snapshot()['messages']),4)

    def test_concurrent_device_revision_prevents_overwriting(self):
        barrier=threading.Barrier(2);accepted=[]
        def begin(number):
            barrier.wait()
            try:self.chat.begin(0,str(number),'Synthetic');accepted.append(number)
            except ValueError:pass
        workers=[threading.Thread(target=begin,args=(n,)) for n in range(2)]
        for thread in workers:thread.start()
        for thread in workers:thread.join()
        self.assertEqual(len(accepted),1);self.assertEqual(len(self.chat.snapshot()['messages']),1)

    def test_restart_marks_interrupted_requests_readonly_and_never_replays(self):
        self.chat.begin(0,'synthetic-job','Synthetic question')
        restored=ProductionChat(self.path).snapshot()
        self.assertIsNone(restored['active']);self.assertIn('자동 재실행하지',restored['messages'][-1]['text'])
        self.assertEqual(len(restored['messages']),2)
        self.assertEqual(ProductionChat(self.path).snapshot(),restored)

    def test_unchanged_poll_omits_message_text_and_session_switch_fetches_full_state(self):
        value=self.chat.import_once(0,[{'role':'user','text':'Synthetic shared question'}])
        short=self.chat.snapshot(str(value['revision']),value['session_id'])
        self.assertTrue(short['unchanged']);self.assertNotIn('messages',short)
        self.assertNotIn('Synthetic shared question',json.dumps(short))
        self.assertIn('messages',self.chat.snapshot(value['revision'],'another-session'))

    def test_live_activity_is_shared_without_disk_writes_or_message_revisions(self):
        self.chat.begin(0,'synthetic-live','Synthetic question');self.chat.progress('synthetic-live','model',1)
        old=self.path.read_bytes();state=self.chat.snapshot()
        self.chat.activity('synthetic-live',{'cli_stage':'thinking','cli_signals':42,'cli_idle_s':.1,'thought':'PRIVATE'})
        value=self.chat.snapshot(state['revision'],state['session_id'])
        self.assertTrue(value['unchanged']);self.assertNotIn('messages',value);self.assertNotIn('PRIVATE',json.dumps(value))
        self.assertEqual(value['active']['cli_signals'],42);self.assertEqual(self.path.read_bytes(),old)
        self.chat.activity('stale-job',{'cli_stage':'answer'});self.assertEqual(self.chat.snapshot()['active']['cli_stage'],'thinking')
        self.chat.progress('synthetic-live','model',2);self.assertNotIn('cli_stage',self.chat.snapshot()['active'])
        self.chat.complete('synthetic-live','Synthetic reply');self.chat.activity('synthetic-live',{'cli_stage':'answer'})
        self.assertIsNone(self.chat.snapshot()['active'])

    def test_corrupt_file_and_failed_atomic_write_do_not_erase_history(self):
        self.path.write_text('{invalid',encoding='utf-8')
        with self.assertRaises(ValueError):self.chat.snapshot()
        self.assertEqual(self.path.read_text(encoding='utf-8'),'{invalid')
        self.path.unlink();old=self.chat.import_once(0,[{'role':'user','text':'Synthetic preserved'}])
        raw=self.path.read_bytes()
        with patch('production_chat.os.replace',side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError):self.chat.clear(old['revision'])
        self.assertEqual(self.path.read_bytes(),raw);self.assertEqual(self.chat.snapshot(),old)

    def test_corruption_and_failed_save_do_not_replace_existing_data(self):
        self.path.write_text('{broken',encoding='utf-8')
        with self.assertRaises(ValueError):self.chat.snapshot()
        self.assertEqual(self.path.read_text(),'{broken')
        self.path.unlink();self.chat=ProductionChat(self.path)
        self.chat.import_once(0,[{'role':'user','text':'Synthetic'}]);before=self.path.read_bytes()
        with patch('production_chat.os.replace',side_effect=OSError('Synthetic disk failure')):
            with self.assertRaises(OSError):self.chat.clear(1)
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(self.chat.snapshot()['revision'],1)

    def test_restart_records_interruption_without_replaying(self):
        self.chat.begin(0,'synthetic','Question')
        state=ProductionChat(self.path).snapshot()
        self.assertIsNone(state['active']);self.assertIn('자동 재실행하지',state['messages'][-1]['text'])

    def test_display_plan_has_no_executable_details_and_limits_history(self):
        plan=display_plan([{'kind':'api','label':'Synthetic','path':'PRIVATE_PATH','args':json.dumps({'id':'PRIVATE_ID','edits':[{'before':'Old','after':'New'}]})}])
        self.assertNotIn('PRIVATE',json.dumps(plan));self.assertEqual(plan['steps'][0]['changes'][0]['after'],'New')
        self.assertLessEqual(len(clean_messages([{'role':'user','text':str(n)} for n in range(150)])),100)
        self.assertLess(len(json.dumps(clean_messages([{'role':'user','text':'x'*8000}]*100))),760000)


class IntegrationTests(StoreTests):
    def manager(self):
        helper=MagicMock();helper.lock=threading.Lock();helper.job=None
        helper.grok.ready.return_value=True
        helper.grok.complete.return_value={'reply':'Synthetic answer','intent':'explain','reads':[],'actions':[]}
        manager=ProductionAssistant(helper,MagicMock(),lambda:{'items':[]},MagicMock(),chat=self.chat)
        return manager,helper

    def test_backend_persists_reply_without_a_browser_and_uses_shared_context(self):
        imported=self.chat.import_once(0,[{'role':'user','text':'Shared synthetic history'}])
        manager,helper=self.manager()
        body={'message':'New synthetic question','controls':[],'conversation':[{'role':'assistant','text':'UNTRUSTED_LOCAL_HISTORY'}],'chat_revision':imported['revision']}
        with patch('production_assistant.threading.Thread') as worker:
            started=manager.start(body)
        forwarded=worker.call_args.kwargs['args'][0]
        self.assertNotIn('UNTRUSTED',json.dumps(forwarded))
        record=self.chat.snapshot();self.assertIsNotNone(record['active'])
        manager._run(forwarded,started['id'],helper.cancel_event)
        self.assertEqual(self.chat.snapshot()['messages'][-1]['text'],'Synthetic answer')
        self.assertEqual(helper.job['chat_message_id'],self.chat.snapshot()['messages'][-1]['id'])

    def test_shared_followup_keeps_proposal_context_and_replans_common_edits(self):
        manager,helper=self.manager()
        manager.write_api=MagicMock()
        change={'kind':'set','target':'main:1','before':'Original','value':'Revised','label':'합성 공통 문구 수정','path':'','args':'{}'}
        helper.grok.complete.return_value={'reply':'이렇게 다듬겠습니다.','intent':'propose','reads':[],'actions':[change]}
        body={'message':'이 항목을 자연스럽게 다듬어줘','controls':[{'ref':'main:1','id':'style','value':'Original','type':'textarea'}],'chat_revision':0}
        with patch('production_assistant.threading.Thread') as worker:first=manager.start(body)
        manager._run(worker.call_args.kwargs['args'][0],first['id'],helper.cancel_event)
        old_plan=helper.job['production']['plan_id']
        self.assertEqual(helper.job['state'],'done')
        helper.grok.complete.return_value={'reply':'합성 변경안입니다.','intent':'execute','reads':[],'actions':[change]}
        follow={**body,'message':'응','chat_revision':self.chat.snapshot()['revision']}
        with patch('production_assistant.threading.Thread') as worker:second=manager.start(follow)
        forwarded=worker.call_args.kwargs['args'][0]
        self.assertIn('확인 대기',forwarded['conversation'][-1]['text'])
        manager._run(forwarded,second['id'],helper.cancel_event)
        self.assertTrue(helper.job['production']['auto_eligible']);helper.grok.complete.assert_called()
        with self.assertRaises(ValueError):manager.claim({'plan_id':old_plan,'index':0})
        self.assertNotEqual(old_plan,helper.job['production']['plan_id']);manager.write_api.assert_not_called()

    def test_old_app_error_is_omitted_only_from_forwarded_context(self):
        saved=self.chat.import_once(0,[{'role':'user','text':'Synthetic edit request'},{'role':'assistant','text':LEGACY_COMMON_ERROR}])
        self.chat.begin(saved['revision'],'synthetic-followup','다시 해줘')
        self.assertEqual(self.chat.snapshot()['messages'][1]['text'],LEGACY_COMMON_ERROR)
        self.chat.complete('synthetic-followup','Synthetic response')
        follow=self.chat.begin(self.chat.snapshot()['revision'],'synthetic-next','응')
        self.assertNotIn(LEGACY_COMMON_ERROR,json.dumps(follow['conversation'],ensure_ascii=False))

    def test_clear_invalidates_old_unclaimed_plans_and_receipts_are_shared(self):
        manager,helper=self.manager()
        action={'kind':'set','target':'main:1','before':'old','value':'new','label':'Synthetic edit','path':'','args':'{}'}
        helper.grok.complete.return_value={'reply':'Synthetic plan','intent':'execute','reads':[],'actions':[action]}
        body={'message':'문구를 바꿔줘','controls':[{'ref':'main:1','id':'summary','value':'old','type':'textarea','label':'Synthetic','page':'main'}],'chat_revision':0}
        with patch('production_assistant.threading.Thread'):
            started=manager.start(body)
        from production_assistant import validate_input
        request=validate_input(body);manager._run(request,started['id'],helper.cancel_event)
        pid=helper.job['production']['plan_id'];manager.claim({'plan_id':pid,'index':0});manager.finish({'plan_id':pid,'index':0,'ok':True})
        state=self.chat.snapshot();self.assertEqual(state['messages'][-2]['plan']['state'],'앱에 전달됨')
        self.assertTrue(manager.claim({'plan_id':pid,'index':0})['already_claimed'])
        # A second fresh plan becomes unclaimable after the common conversation is cleared.
        helper.job=None;body['chat_revision']=state['revision']
        with patch('production_assistant.threading.Thread'):
            started=manager.start(body)
        manager._run(validate_input(body),started['id'],helper.cancel_event);pid=helper.job['production']['plan_id']
        state=self.chat.snapshot();self.chat.clear(state['revision'])
        with self.assertRaises(ValueError):manager.claim({'plan_id':pid,'index':0})


    def test_briefly_locked_transcript_is_retried_and_a_lost_save_never_blocks_later_turns(self):
        real=os.replace;denied=[PermissionError(13,'synthetic scanner')]*3
        def flaky(source,target):
            if denied:raise denied.pop()
            return real(source,target)
        with patch('production_chat.os.replace',flaky),patch('production_chat.time.sleep'):
            started=self.chat.begin(0,'synthetic','Question')
        self.assertEqual(denied,[]);self.assertEqual(ProductionChat(self.path).snapshot()['messages'][0]['text'],'Question')
        # The lock outlasts every retry while the answer is stored: the answer is lost, the turn is not left open.
        with patch('production_chat.os.replace',side_effect=PermissionError(13,'synthetic scanner')),patch('production_chat.time.sleep'):
            with self.assertRaises(OSError):self.chat.complete('synthetic','Answer')
        self.assertIsNone(self.chat.snapshot()['active'])
        self.chat.begin(started['revision'],'synthetic-next','Next question')
        self.chat.complete('synthetic-next','Next answer')
        self.assertEqual([row['text'] for row in self.chat.snapshot()['messages']][-2:],['Next question','Next answer'])
        self.assertEqual([path.name for path in self.path.parent.iterdir()],[self.path.name])   # no temporary files left

    def test_shared_progress_or_receipt_write_failure_does_not_fail_the_request_or_strand_a_step(self):
        manager,helper=self.manager();manager.write_api=MagicMock()
        change={'kind':'set','target':'main:1','before':'Original','value':'Revised','label':'합성 문구 수정','path':'','args':'{}'}
        helper.grok.complete.return_value={'reply':'합성 변경안입니다.','intent':'propose','reads':[],'actions':[change]}
        body={'message':'다듬어줘','controls':[{'ref':'main:1','id':'style','value':'Original','type':'textarea'}],'chat_revision':0}
        with patch('production_assistant.threading.Thread') as worker:first=manager.start(body)
        with patch.object(self.chat,'progress',side_effect=PermissionError(13,'synthetic scanner')):
            manager._run(worker.call_args.kwargs['args'][0],first['id'],helper.cancel_event)
        self.assertEqual(helper.job['state'],'done');plan=helper.job['production']['plan_id']
        with patch.object(self.chat,'plan_state',side_effect=PermissionError(13,'synthetic scanner')):
            self.assertEqual(manager.claim({'plan_id':plan,'index':0})['action']['value'],'Revised')
            self.assertEqual(manager.finish({'plan_id':plan,'index':0,'ok':True})['state'],'done')

    def test_unexpected_failure_still_ends_the_job_instead_of_leaving_the_helper_busy(self):
        manager,helper=self.manager()
        for failure in (OverflowError('synthetic'),AttributeError('synthetic'),http.client.IncompleteRead(b'')):
            with self.subTest(failure=type(failure).__name__):
                helper.job=None;helper.grok.complete.side_effect=failure
                body={'message':'합성 질문','controls':[],'chat_revision':self.chat.snapshot()['revision']}
                with patch('production_assistant.threading.Thread') as worker:started=manager.start(body)
                manager._run(worker.call_args.kwargs['args'][0],started['id'],helper.cancel_event)
                self.assertEqual(helper.job['state'],'error');self.assertNotIn('synthetic',helper.job['error'])
                self.assertIsNone(self.chat.snapshot()['active'])


if __name__=='__main__':unittest.main()
