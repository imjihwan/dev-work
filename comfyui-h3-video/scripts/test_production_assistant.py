"""Synthetic web-assistant plans, app reads and exactly-once execution. No live work."""
import ast
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
import urllib
import urllib.parse
import urllib.request
from unittest.mock import MagicMock,patch

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(os.environ.get('PRODUCTION_TEST_SOURCE',ROOT/'simple_ui'))
sys.path.insert(0,str(SOURCE))
import production_assistant as P


def control(ref='main:1',value='Original synthetic action.',type='textarea',**extra):
    return dict(ref=ref,id='summary',type=type,value=value,label='Synthetic field',page='main',disabled=False,readonly=False,**extra)


def action(kind='set',**extra):
    return {**dict(kind=kind,target='main:1',before='Original',value='Revised',path='',args='{}',label='합성 문구 수정'),**extra}


def plan(actions=None,reads=None,intent='execute'):
    return dict(reply='합성 테스트 답변',intent=intent,reads=reads or [],actions=actions or [])


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.request=P.validate_input({'message':'문구를 바꿔줘','controls':[control()]})
        self.helper=MagicMock();self.helper.lock=threading.Lock();self.helper.cancel_event=threading.Event()
        self.helper.job={'id':'synthetic','state':'starting'}
        self.read=MagicMock(return_value={'items':[]});self.item=MagicMock(return_value={'id':'b','prompt':'Native synthetic prompt.','prompt_hash':'abc'})
        self.writer=MagicMock(return_value={'ok':True})
        self.manager=P.ProductionAssistant(self.helper,self.read,lambda:{'items':[{'id':'b','state':'queued','position':2}]},self.item,write_api=self.writer)

    def run_fake(self,answers,request=None):
        self.helper.grok.complete.side_effect=answers
        self.manager._run(request or self.request,'synthetic',self.helper.cancel_event)
        return self.helper.job

    def test_input_and_read_scrubbing_never_forward_media_or_unknown_properties(self):
        clean=P.validate_input({'message':'Explain','controls':[control()], 'images':['PRIVATE_PHOTO'],'tokens':'PRIVATE_TOKEN'})
        self.assertNotIn('PRIVATE',json.dumps(clean))
        value=P.scrub({'prompt':'A synthetic block.','ui':{'f':{'summary':'Keep this text.'}},'images':['PRIVATE_PHOTO'],'video':{'filename':'PRIVATE_RESULT'},'nested':{'any':'data:image/png;base64,PRIVATE'}})
        self.assertEqual(value['prompt'],'A synthetic block.');self.assertNotIn('PRIVATE',json.dumps(value))
        for body in ({'message':'','controls':[]},{'message':'x','controls':[control(),control()]},{'message':'x','controls':[control(type='password')]}):
            with self.assertRaises(ValueError):P.validate_input(body)

    def test_plan_rejects_invented_controls_ambiguous_edits_readonly_and_unknown_urls(self):
        cases=[action(target='main:99'),action(before=''),action(kind='api',path='https://outside.invalid'),action(kind='api',path='/api/cancel?url=outside')]
        for item in cases:
            with self.assertRaises(ValueError):P.validate_plan(plan([item]),self.request)
        request=P.validate_input({'message':'Synthetic','controls':[control(value='same same')]})
        with self.assertRaises(ValueError):P.validate_plan(plan([action(before='same')]),request)
        request=P.validate_input({'message':'Synthetic','controls':[dict(control(),readonly=True)]})
        with self.assertRaises(ValueError):P.validate_plan(plan([action()]),request)

    def test_text_patches_preserve_unrelated_bytes_and_select_membership(self):
        text='  First action.\nSecond action.  '
        self.assertEqual(P.replacement(text,'Second','Slower second'),'  First action.\nSlower second action.  ')
        request=P.validate_input({'message':'Synthetic','controls':[control(value='a',type='select',options=[{'value':'a'},{'value':'b'}])]})
        P.validate_plan(plan([action(before='a',value='b')]),request)
        with self.assertRaises(ValueError):P.validate_plan(plan([action(before='a',value='c')]),request)

    def test_numeric_bounds_are_kept_without_common_field_keyword_gate(self):
        request=P.validate_input({'message':'길이를 바꿔줘','controls':[control(value='7',type='number',min='1',max='15')]})
        with self.assertRaises(ValueError):P.validate_plan(plan([action(before='7',value='0')]),request)
        for field in ('subject','style','keep','oneTake'):
            source={**control(value='Original'),'id':field}
            request=P.validate_input({'message':'응, 그렇게 해줘','controls':[source],
                'conversation':[{'role':'user','text':'이 칸의 합성 문구를 다듬어줘'},{'role':'assistant','text':'Revised로 바꾸겠습니다.'}],
                'proposal':{'actions':[action()]}})
            clean=P.validate_plan(plan([action()]),request)
            self.assertEqual(clean['actions'],[action()]);self.assertTrue(P.execution_requested(request))
            self.assertEqual(source['value'],'Original','Validation never executes an edit')

    def test_retired_error_does_not_reenter_model_context_or_remove_user_text(self):
        error=P.LEGACY_COMMON_ERROR
        clean=P.validate_input({'message':'다시 고쳐줘','controls':[],
            'conversation':[{'role':'assistant','text':error},{'role':'user','text':error}],
            'contexts':[{'page':'main','statuses':[{'id':'status','text':error},{'id':'other','text':'Synthetic status'}]}]})
        self.assertEqual(clean['conversation'],[{'role':'user','text':error}])
        self.assertEqual(clean['contexts'][0]['statuses'],[{'id':'other','text':'Synthetic status'}])

    def test_targeted_read_precedes_plan_and_remembers_native_prompt_version(self):
        read={'path':'queue_item','args':'{"position":2}'}
        job=self.run_fake([plan(reads=[read],intent='explain'),plan(intent='explain')])
        self.assertEqual(job['state'],'done');self.item.assert_called_once()
        content=self.helper.grok.complete.call_args_list[-1].args[1]
        self.assertEqual(content['read_results'][0]['result']['prompt'],'Native synthetic prompt.')
        saved=self.manager.plans[job['production']['plan_id']]
        self.assertEqual(saved['queue']['prompt_hashes'],{'b':'abc'});self.writer.assert_not_called()

    def test_read_write_mix_and_explanation_cannot_execute_actions(self):
        job=self.run_fake([plan([action()],reads=[{'path':'queue','args':'{}'}])]);self.assertEqual(job['state'],'error')
        self.helper.job={'id':'synthetic','state':'starting'}
        job=self.run_fake([plan([action()],intent='explain')]);self.assertEqual(job['state'],'done')
        self.assertEqual(job['production']['intent'],'propose');self.assertFalse(job['production']['auto_eligible']);self.writer.assert_not_called()

    def test_auto_needs_both_execute_intent_and_direct_command(self):
        for message,intent,eligible in [('문구를 바꿔줘','execute',True),('어떻게 바꿔야 해?','execute',False),('문구를 바꿔줘','propose',False)]:
            self.helper.job={'id':'synthetic','state':'starting'}
            request=P.validate_input({'message':message,'controls':[control()]})
            result=self.run_fake([plan([action()],intent=intent)],request)['production']
            self.assertEqual(result['auto_eligible'],eligible)

    def test_short_approval_uses_dialogue_but_never_approves_advice_or_empty_context(self):
        for message in ('응','네!','좋아','OK'):
            for context,intent,expected in (([], 'execute',False),([{'role':'assistant','text':'합성 변경안을 제안합니다.'}], 'execute',True),([{'role':'assistant','text':'합성 조언입니다.'}], 'propose',False)):
                self.helper.job={'id':'synthetic','state':'starting'}
                request=P.validate_input({'message':message,'controls':[control()], 'conversation':context})
                result=self.run_fake([plan([action()],intent=intent)],request)['production']
                self.assertEqual(result['auto_eligible'],expected)
                self.writer.assert_not_called()

    def test_prior_unapplied_plan_is_context_not_an_automatic_write(self):
        request=P.validate_input({'message':'조금 더 느리게 다듬어줘','controls':[control()],'proposal':{'actions':[action()]}})
        self.assertEqual(request['pending_proposal']['actions'][0]['before'],'Original')
        self.run_fake([plan(intent='explain')],request);self.writer.assert_not_called()

    def test_claim_is_ordered_and_at_most_once(self):
        job=self.run_fake([plan([action(),dict(action(),before='Revised',value='Final')])])
        pid=job['production']['plan_id']
        with self.assertRaises(ValueError):self.manager.claim({'plan_id':pid,'index':1})
        self.assertIn('action',self.manager.claim({'plan_id':pid,'index':0}))
        self.assertTrue(self.manager.claim({'plan_id':pid,'index':0})['already_claimed'])
        self.manager.finish({'plan_id':pid,'index':0,'ok':False})
        with self.assertRaises(ValueError):self.manager.claim({'plan_id':pid,'index':1})

    def test_api_execution_rejects_modified_arguments_and_does_not_retry(self):
        request_action=dict(action(),kind='api',path='/api/settings/rename',target='',before='',value='',args='{"name":"Old","new_name":"New"}')
        job=self.run_fake([plan([request_action])]);pid=job['production']['plan_id'];self.manager.claim({'plan_id':pid,'index':0})
        with self.assertRaises(ValueError):self.manager.execute_api({'plan_id':pid,'index':0,'args':{'name':'Other','new_name':'New'}})
        body={'plan_id':pid,'index':0,'args':{'name':'Old','new_name':'New'}}
        self.assertTrue(self.manager.execute_api(body)['ok']);self.assertTrue(self.manager.execute_api(body)['already_claimed']);self.writer.assert_called_once()

    def test_local_binding_payload_is_resolved_only_at_execution(self):
        request_action=dict(action(),kind='api',path='/api/settings/save',target='',before='',value='',args='{"name":"Synthetic","data":"$current_settings"}')
        job=self.run_fake([plan([request_action])]);pid=job['production']['plan_id'];self.manager.claim({'plan_id':pid,'index':0})
        payload={'name':'Synthetic','data':{'images':['LOCAL_ONLY_PHOTO'],'f':{'summary':'Synthetic'}}}
        self.assertTrue(self.manager.execute_api({'plan_id':pid,'index':0,'args':payload})['ok'])
        sent=json.dumps(self.helper.grok.complete.call_args.args[1]);self.assertNotIn('LOCAL_ONLY_PHOTO',sent)

    def test_api_unknown_outcome_and_cancellation_never_replay(self):
        request_action=dict(action(),kind='api',path='/api/cancel',target='',args='{"ids":["b"]}')
        job=self.run_fake([plan([request_action])]);pid=job['production']['plan_id'];self.manager.claim({'plan_id':pid,'index':0});self.writer.side_effect=OSError('lost response')
        body={'plan_id':pid,'index':0,'args':{'ids':['b']}}
        self.assertFalse(self.manager.execute_api(body)['ok']);self.assertTrue(self.manager.execute_api(body)['already_claimed']);self.writer.assert_called_once()
        self.helper.job={'id':'synthetic','state':'starting'};self.helper.cancel_event.set()
        before=self.helper.grok.complete.call_count;job=self.run_fake([]);self.assertEqual(job['state'],'cancelled');self.assertEqual(before,self.helper.grok.complete.call_count)

    def test_shared_helper_busy_is_respected(self):
        self.helper.job={'state':'reviewing'}
        with self.assertRaises(ValueError):self.manager.start({'message':'Synthetic','controls':[]})

    def test_quality_first_effort_is_validated_and_forwarded(self):
        self.assertEqual(self.request['effort'],'high')
        for effort in ('low','medium','high','xhigh'):
            self.helper.job={'id':'synthetic','state':'starting'}
            request=P.validate_input({'message':'Synthetic','controls':[],'effort':effort})
            self.run_fake([plan(intent='explain')],request)
            self.assertEqual(self.helper.grok.complete.call_args.kwargs['effort'],effort)
        with self.assertRaises(ValueError):P.validate_input({'message':'Synthetic','controls':[],'effort':'invented'})

    def test_grok_budget_and_numeric_progress_never_include_task_text(self):
        def answer(system,content,schema,cancel,**kwargs):
            self.assertLessEqual(kwargs['timeout_s'],900)
            kwargs['on_progress']({'cli_elapsed_s':181,'cli_limit_s':300,'cli_stage':'thinking','cli_signals':42,'thought':'PRIVATE'})
            return plan(intent='explain')
        self.helper.grok.complete.side_effect=answer
        self.manager._run(self.request,'synthetic',self.helper.cancel_event)
        self.assertEqual(self.helper.job['state'],'done');self.assertEqual(self.helper.job['cli_elapsed_s'],181);self.assertEqual(self.helper.job['cli_limit_s'],300)
        self.assertNotIn('PRIVATE',json.dumps(self.helper.job));self.assertEqual(self.helper.job['cli_stage'],'thinking')

    def test_total_request_deadline_stops_before_a_new_model_call(self):
        with patch.object(P.time,'monotonic',side_effect=[0,0,901]):
            self.manager._run(self.request,'synthetic',self.helper.cancel_event)
        self.assertEqual(self.helper.job['state'],'error');self.assertIn('900',self.helper.job['error']);self.helper.grok.complete.assert_not_called();self.writer.assert_not_called()

    def test_large_queue_page_does_not_shorten_local_guards_or_target_access(self):
        rows=[{'id':f'synthetic-{n}','state':'queued','position':n,'pct':0} for n in range(1,1001)]
        snapshot={'items':rows,'pending_count':1000,'running_count':0,'other_count':2}
        self.manager.queue_snapshot=lambda:snapshot
        job=self.run_fake([plan(reads=[{'path':'queue_item','args':'{"position":990}'}],intent='explain'),plan(intent='explain')])
        self.assertEqual(job['state'],'done');self.item.assert_called_once_with({'position':990},snapshot)
        payload=self.helper.grok.complete.call_args.args[1]
        self.assertEqual(len(payload['queue']['items']),20);self.assertEqual(payload['queue']['total'],1000);self.assertTrue(payload['queue']['has_more'])
        self.assertEqual(len(self.manager.plans[job['production']['plan_id']]['queue']['items']),1000)
        self.assertLess(len(json.dumps(payload['queue'])),len(json.dumps(snapshot))//10)
        page=P.queue_page(snapshot,{'offset':980,'limit':20})
        self.assertEqual(page['items'][-1]['position'],1000);self.assertFalse(page['has_more'])
        for args in ({'offset':-1},{'limit':0},{'limit':101},{'offset':True}):
            with self.assertRaises(ValueError):P.queue_page(snapshot,args)

    def test_repeated_reads_are_reused_only_within_one_request(self):
        read={'path':'queue_item','args':'{"position":2}'}
        job=self.run_fake([plan(reads=[read],intent='explain'),plan(reads=[read],intent='explain'),plan(intent='explain')])
        self.assertEqual(job['state'],'done');self.item.assert_called_once()
        self.assertEqual(len(self.helper.grok.complete.call_args.args[1]['read_results']),1)
        self.helper.job={'id':'synthetic','state':'starting'}
        self.run_fake([plan(reads=[read],intent='explain'),plan(intent='explain')]);self.assertEqual(self.item.call_count,2)

    def test_model_view_preserves_text_true_flags_and_original_request(self):
        original=control(value='  Exact synthetic action.\n\n  ',hidden=False)
        request=P.validate_input({'message':'Synthetic','controls':[original,dict(control(ref='main:2'),readonly=True)]})
        compact=P.model_request(request)
        self.assertEqual(compact['controls'][0]['value'],original['value']);self.assertNotIn('disabled',compact['controls'][0])
        self.assertTrue(compact['controls'][1]['readonly']);self.assertIs(request['controls'][0]['disabled'],False)
        self.assertNotIn('effort',compact)

    def test_all_user_facing_json_routes_are_available_without_binary_or_recursive_access(self):
        source=ast.parse((SOURCE/'server.py').read_text(encoding='utf-8-sig'))
        handler=next(item for item in source.body if isinstance(item,ast.ClassDef) and item.name=='H')
        post=next(item for item in handler.body if isinstance(item,ast.FunctionDef) and item.name=='do_POST')
        paths={item.value for item in ast.walk(post) if isinstance(item,ast.Constant) and isinstance(item.value,str) and item.value.startswith('/api/')}
        paths-={'/api/ui-state'};paths={path for path in paths if not path.startswith('/api/production-assistant/')}
        self.assertTrue(paths<=P.WRITES.keys())
        for path in ('/api/video','/api/input','/api/gallery/thumbnail','/api/production-assistant/start'):
            self.assertNotIn(path,P.READS)


class NativeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.graph={'director':{'inputs':{'prompt':'summary: A block slides.\n\ndetailed_description: The block moves slowly.'}},'other':{'inputs':{'value':'UNCHANGED'}}}
        self.raw={'queue_running':[],'queue_pending':[[1,'b',self.graph,{},[]]]}
        self.db=[{'id':'b','prompt':'STALE HISTORY TEXT','images':['PRIVATE_PHOTO_PATH'],'video':{'filename':'PRIVATE_RESULT'},'ui':{'f':{'summary':'A block slides.'},'shots':[[0,'The block moves slowly.']]}}]
        self.calls=[]
        def comfy(path,data=None,headers=None):
            self.calls.append((path,json.loads(data) if data else None))
            if path=='/queue' and data is None:return io.BytesIO(json.dumps(self.raw).encode())
            return io.BytesIO(b'{}')
        self.replace=MagicMock(return_value={'prompt_verified':True})
        self.env={'json':json,'hashlib':hashlib,'time':__import__('time'),'urllib':urllib,'comfy':comfy,'HLOCK':threading.Lock(),'PLOCK':threading.Lock(),'QUEUE_EDIT_LOCK':threading.Lock(),'HIST_DB':self.db,'PROGRESS':{'b':{'pct':12}},'DIRECTOR':'director','PRODUCTION_READS':P.READS,'PRODUCTION_WRITES':P.WRITES,'_status':lambda pid,queue:{'state':'unknown'},'hist_result':MagicMock(),'replace_queued_prompt':self.replace,'_save_json':MagicMock(),'HIST':'SYNTHETIC','PORT':8190}
        source=ast.parse((SOURCE/'server.py').read_text(encoding='utf-8-sig'));functions=[item for item in source.body if isinstance(item,ast.FunctionDef) and item.name.startswith('production_')]
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<synthetic native bridge>','exec'),self.env)

    def test_queue_snapshot_has_only_status_and_native_prompt_read_is_targeted(self):
        snapshot=self.env['production_queue_snapshot']();self.assertNotIn('PRIVATE',json.dumps(snapshot));self.assertNotIn('prompt',json.dumps(snapshot))
        value=self.env['production_queue_item']({'position':1},snapshot)
        self.assertEqual(value['prompt'],self.graph['director']['inputs']['prompt']);self.assertNotIn('PRIVATE',json.dumps(value));self.assertNotIn('STALE',json.dumps(value))

    def test_queue_prompt_patch_changes_only_requested_bytes_and_keeps_graph_settings(self):
        snapshot=self.env['production_queue_snapshot']();item=self.env['production_queue_item']({'id':'b'},snapshot);snapshot['prompt_hashes']={'b':item['prompt_hash']}
        result=self.env['production_write_api']('/api/production-assistant/patch-queue',{'id':'b','edits':[{'before':'slowly','after':'very slowly'}]},snapshot)
        self.assertTrue(result['prompt_verified']);new=self.replace.call_args.args[1]
        self.assertEqual(new['other'],self.graph['other']);self.assertEqual(new['director']['inputs']['prompt'],self.graph['director']['inputs']['prompt'].replace('slowly','very slowly'))
        self.assertEqual(self.replace.call_args.kwargs['expected_graph'],self.graph)
        self.assertEqual(self.db[0]['ui']['final'],new['director']['inputs']['prompt']);self.assertEqual(self.db[0]['images'],['PRIVATE_PHOTO_PATH'])

    def test_changed_prompt_or_started_job_is_not_overwritten(self):
        snapshot=self.env['production_queue_snapshot']();snapshot['prompt_hashes']={'b':'stale-hash'}
        with self.assertRaises(ValueError):self.env['production_write_api']('/api/production-assistant/patch-queue',{'id':'b','edits':[{'before':'slowly','after':'fast'}]},snapshot)
        self.replace.assert_not_called()
        self.raw['queue_running']=self.raw['queue_pending'];self.raw['queue_pending']=[]
        with self.assertRaises(ValueError):self.env['production_validate_write']({'path':'/api/cancel','args':'{"ids":["b"]}'},snapshot)
        self.assertFalse(any(path=='/interrupt' for path,_ in self.calls))

    def test_pending_cancel_never_interrupts_a_job_that_starts_during_delete(self):
        snapshot=self.env['production_queue_snapshot']()
        original=self.env['comfy']
        def race(path,data=None,headers=None):
            if path=='/queue' and data:
                self.raw['queue_running']=self.raw['queue_pending'];self.raw['queue_pending']=[]
            return original(path,data,headers)
        self.env['comfy']=race
        self.env['production_write_api']('/api/cancel',{'ids':['b']},snapshot)
        self.assertEqual(self.raw['queue_running'][0][1],'b')
        self.assertTrue(any(path=='/queue' and data=={'delete':['b']} for path,data in self.calls));self.assertFalse(any(path=='/interrupt' for path,_ in self.calls))


if __name__=='__main__':unittest.main()
