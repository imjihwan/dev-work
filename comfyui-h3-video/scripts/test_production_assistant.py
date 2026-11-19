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
from bulk_progress import BulkProgress


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

    def test_hidden_writable_inputs_and_unique_dom_ids_remain_addressable(self):
        request=P.validate_input({'message':'수정해줘','controls':[{**control(),'hidden':True}]})
        original=action(target='summary')
        result=P.validate_plan(plan([original]),request)
        self.assertEqual(result['actions'][0]['target'],'main:1');self.assertEqual(original['target'],'summary')
        for flags in ({'disabled':True},{'readonly':True}):
            request=P.validate_input({'message':'수정해줘','controls':[{**control(),**flags}]})
            with self.assertRaises(P.UnavailableTarget):P.validate_plan(plan([action()]),request)
        request=P.validate_input({'message':'수정해줘','controls':[control(),control(ref='main:2')]})
        with self.assertRaises(P.UnavailableTarget):P.validate_plan(plan([action(target='summary')]),request)

    def test_whole_field_replace_captures_original_and_repeated_edits_use_fresh_values(self):
        original='  Long synthetic scene.\nSecond line.  '
        for revised in ('First revision.','Second revision.','Third revision.'):
            request=P.validate_input({'message':'수정 후 전체 반영','controls':[control(value=original)]})
            source=action(kind='replace',before='',value=revised)
            validated=P.validate_plan(plan([source]),request)['actions'][0]
            self.assertEqual(validated['kind'],'set');self.assertEqual(validated['before'],original)
            self.assertEqual(P.replacement(original,validated['before'],validated['value']),revised)
            self.assertEqual(source['kind'],'replace');original=revised

    def test_failed_exact_edit_replans_as_whole_replacement_without_writes(self):
        job=self.run_fake([plan([action(before='wrong original')]),plan([action(kind='replace',before='',value='New synthetic action.')])])
        self.assertEqual(job['state'],'done');self.assertEqual(self.helper.grok.complete.call_count,2)
        self.assertEqual(job['production']['actions'][0]['before'],self.request['controls'][0]['value'])
        self.writer.assert_not_called()

    def test_stale_text_proposal_does_not_block_new_request_or_mix_final_with_shots(self):
        request=P.validate_input({'message':'다시 수정','controls':[control()], 'proposal':{'actions':[action(before='old original')]}})
        self.assertNotIn('pending_proposal',request)
        request=P.validate_input({'message':'수정','controls':[{**control(),'id':'final'},{**control(ref='main:2'),'id':'shot-1-action'}]})
        with self.assertRaises(P.InvalidEdit):P.validate_plan(plan([action(),action(target='main:2')]),request)

    def test_bad_target_is_replanned_as_an_api_without_any_write(self):
        bulk=action(kind='api',target='',before='',value='',path='/api/production-assistant/patch-queue',args='{"all_pending":true,"edits":[{"before":"slow","after":"fast"}]}')
        answers=iter([plan([action(target='old:99')]),plan([bulk])]);feedback=[]
        def answer(system,content,*args,**kwargs):
            feedback.append(json.loads(json.dumps(content.get('action_feedback'))))
            return next(answers)
        job=self.run_fake(answer)
        self.assertEqual(job['state'],'done');self.assertEqual(self.helper.grok.complete.call_count,2)
        self.assertIsNone(feedback[0]);self.assertEqual(feedback[1]['reason'],'missing');self.assertFalse(feedback[1]['executed'])
        self.assertEqual(job['production']['actions'][0]['path'],bulk['path']);self.writer.assert_not_called()

    def test_target_repair_is_bounded_and_timeouts_are_not_retried(self):
        job=self.run_fake([plan([action(target='old:99')]),plan([action(target='old:99')])])
        self.assertEqual(job['state'],'error');self.assertEqual(self.helper.grok.complete.call_count,2)
        self.assertNotIn('현재 화면에서 사용할 수 없는 대상',job['error']);self.writer.assert_not_called()
        self.helper.job={'id':'synthetic','state':'starting'};self.helper.grok.complete.reset_mock()
        job=self.run_fake([RuntimeError('Synthetic provider timeout')])
        self.assertEqual(job['state'],'error');self.assertEqual(self.helper.grok.complete.call_count,1)

    def test_stale_proposal_target_does_not_prevent_a_new_request(self):
        request=P.validate_input({'message':'다시 해줘','controls':[control()], 'proposal':{'actions':[action(target='old:99')]}})
        self.assertNotIn('pending_proposal',request)

    def test_hidden_buttons_need_a_known_reveal_path(self):
        click=action(kind='click',before='',value='')
        for revealable in (False,True):
            request=P.validate_input({'message':'실행해줘','controls':[{**control(type='button'),'hidden':True,'revealable':revealable}]})
            if revealable:self.assertEqual(P.validate_plan(plan([click]),request)['actions'],[click])
            else:
                with self.assertRaises(P.UnavailableTarget):P.validate_plan(plan([click]),request)

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
            self.assertEqual(clean['actions'],[action()])
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

    def test_auto_uses_semantic_intent_without_keyword_or_punctuation_gate(self):
        for message,intent,eligible in [('문구를 바꿔줘','execute',True),('가능하면 구성을 알아서 개선해줄 수 있어?','execute',True),('구성이 왜 이상한지 보고 고쳐줘','execute',True),('어떻게 바꾸면 좋을지 설명해줘','explain',False),('문구를 바꿔줘','propose',False)]:
            self.helper.job={'id':'synthetic','state':'starting'}
            request=P.validate_input({'message':message,'controls':[control()]})
            result=self.run_fake([plan([action()],intent=intent)],request)['production']
            self.assertEqual(result['auto_eligible'],eligible)

    def test_short_approval_and_advice_use_model_intent(self):
        for message in ('응','네!','좋아','OK'):
            for context,intent,expected in (([{'role':'assistant','text':'합성 변경안을 제안합니다.'}], 'execute',True),([{'role':'assistant','text':'합성 조언입니다.'}], 'propose',False)):
                self.helper.job={'id':'synthetic','state':'starting'}
                request=P.validate_input({'message':message,'controls':[control()], 'conversation':context})
                result=self.run_fake([plan([action()],intent=intent)],request)['production']
                self.assertEqual(result['auto_eligible'],expected)
                self.writer.assert_not_called()

    def test_complete_rewrite_is_allowed_and_bulk_scope_is_one_action(self):
        source={**control(value='Original wording. Original composition.'),'id':'style'}
        request=P.validate_input({'message':'알아서 전체적으로 다시 구성해줘','controls':[source]})
        rewritten=action(before=source['value'],value='Entirely new composition and wording.')
        clean=P.validate_plan(plan([rewritten]),request)
        self.assertEqual(P.replacement(source['value'],clean['actions'][0]['before'],clean['actions'][0]['value']),rewritten['value'])
        bulk=action(kind='api',target='',before='',value='',path='/api/production-assistant/patch-queue',args='{"all_pending":true,"edits":[{"before":"slow","after":"fast"}]}')
        self.helper.job={'id':'synthetic','state':'starting'}
        job=self.run_fake([plan([bulk])],request)
        self.assertEqual(len(job['production']['actions']),1);self.assertTrue(job['production']['auto_eligible']);self.writer.assert_not_called()

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

    def large_screen(self):
        controls=[{**control(ref=f'main:{n+1}',value=('Synthetic scene line.\n'*3000)+str(n)),'id':field} for n,field in enumerate(('subject','summary','actionText','style','keep','final'))]
        controls += [{**control(ref=f'main:{n+7}',value='',type='button'),'id':f'button-{n}'} for n in range(1100)]
        controls += [{**control(ref='story:1200',type='select',value='choice-0'),'id':'large-choice','page':'story','options':[{'value':f'choice-{n}','label':f'Synthetic choice {n} '+('X'*100)} for n in range(500)]}]
        return P.validate_input({'message':'동작만 수정하고 전체 반영해줘','controls':controls})

    def test_large_screen_is_bounded_for_model_but_original_values_remain_readable(self):
        request=self.large_screen();raw=json.dumps(request,ensure_ascii=False);self.assertGreater(len(raw),240000)
        view=P.model_request(request);self.assertLess(len(json.dumps(view,ensure_ascii=False)),160000)
        self.assertTrue(view['ui_overview']['has_more']);self.assertLessEqual(len(view['controls']),200)
        action_field=next(c for c in view['controls'] if c.get('id')=='actionText')
        self.assertTrue(action_field['value_omitted']);self.assertNotIn('value',action_field)
        read=P.ui_controls_page(request,{'refs':[action_field['ref']]});original=next(c for c in request['controls'] if c['ref']==action_field['ref'])
        self.assertEqual(read['controls'][0]['value'],original['value']);self.assertGreater(len(original['value']),60000)
        self.assertNotIn('value_omitted',original)
        self.assertEqual(P.ui_controls_page(request,{'ids':['button-1099']})['controls'][0]['id'],'button-1099')

    def test_large_select_options_and_text_reads_are_paged_without_silent_loss(self):
        request=self.large_screen()
        read=P.ui_controls_page(request,{'ids':['large-choice'],'option_offset':200,'option_limit':100})['controls'][0]
        self.assertEqual(read['options'][0]['value'],'choice-200');self.assertEqual(read['options_total'],500);self.assertTrue(read['options_has_more'])
        read=P.ui_controls_page(request,{'refs':['main:1','main:2'],'limit':2})
        self.assertEqual(len(read['controls']),1);self.assertTrue(read['has_more']);self.assertEqual(read['total'],2)
        for args in ({'limit':0},{'offset':-1},{'refs':'main:1'},{'option_limit':201}):
            with self.assertRaises(ValueError):P.ui_controls_page(request,args)

    def test_large_screen_read_then_replace_keeps_entire_original_for_exact_execution(self):
        request=self.large_screen()
        request['message']='통합 동작만 수정해줘'
        updated=action(kind='replace',target='main:3',before='',value='Updated complete synthetic action.')
        read={'path':'ui_controls','args':'{"ids":["actionText"]}'}
        job=self.run_fake([plan(reads=[read]),plan([updated])],request)
        self.assertEqual(job['state'],'done');self.assertEqual(self.helper.grok.complete.call_count,2)
        planned=job['production']['actions'][0]
        self.assertEqual(planned['before'],request['controls'][2]['value']);self.assertEqual(planned['value'],updated['value'])
        self.read.assert_not_called();self.writer.assert_not_called()

    def test_unread_preview_cannot_be_rewritten_and_feedback_allows_a_targeted_read(self):
        request=self.large_screen();updated=action(kind='replace',target='main:3',before='',value='Revised synthetic action.')
        read={'path':'ui_controls','args':'{"refs":["main:3"]}'}
        job=self.run_fake([plan([updated]),plan(reads=[read]),plan([updated])],request)
        self.assertEqual(job['state'],'done');self.assertEqual(self.helper.grok.complete.call_count,3)
        self.assertEqual(job['production']['actions'][0]['before'],request['controls'][2]['value']);self.writer.assert_not_called()

    def test_large_pending_proposal_has_retrievable_full_new_text(self):
        request=self.large_screen();new='Revised synthetic scene. '*2500
        request['pending_proposal']={'actions':[action(kind='set',target='main:3',before=request['controls'][2]['value'],value=new)]}
        view=P.model_request(request);item=view['pending_proposal']['actions'][0]
        self.assertNotIn('before',item);self.assertTrue(item['value_omitted']);self.assertNotIn('value',item)
        read=P.ui_controls_page(request,{'proposal':True,'limit':1})['actions'][0]
        self.assertEqual(read['value'],new);self.assertNotIn('before',read)

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
        self.env['BULK_PROGRESS']=BulkProgress()
        source=ast.parse((SOURCE/'server.py').read_text(encoding='utf-8-sig'));functions=[item for item in source.body if isinstance(item,ast.FunctionDef) and (item.name.startswith('production_') or item.name=='commit_bulk_history')]
        exec(compile(ast.Module(body=functions,type_ignores=[]),'<synthetic native bridge>','exec'),self.env)
        from types import SimpleNamespace
        self.env['bulk_queue_editor']=lambda:SimpleNamespace(apply=self.apply_bulk)

    def apply_bulk(self, changes):
        state=json.load(self.env['comfy']('/queue'))
        pending={row[1]:row for row in state['queue_pending']}
        verified=[];failed=[]
        for change in changes:
            if change['id'] not in pending or pending[change['id']][2]!=change['before']:
                failed.append({'id':change['id'],'error':'Synthetic race'});continue
            try:
                result=self.replace(change['id'],change['prompt'],expected_graph=change['before'])
                if not result.get('prompt_verified'):raise ValueError('Synthetic verification failed')
                verified.append(change)
            except (OSError,ValueError) as exc:failed.append({'id':change['id'],'error':str(exc)})
        if verified:self.env['commit_bulk_history'](verified)
        return verified,failed

    def with_builder(self):
        text=self.graph['director']['inputs']['prompt']
        builder={'prompt_mode':'simple','simple_prompt':text,'mode':'REF2VA','duration':8,'unchanged':'KEEP'}
        timeline={'builder_state':dict(builder),'resolved_prompt':text,'continuity':{'continuation_prompt':text,'keep':'KEEP'},'items':[{'synthetic_reference':'KEEP'}]}
        self.graph['director']['inputs'].update(builder_state=json.dumps(builder),timeline_data=json.dumps(timeline),external_prompt_overwrite='')

    def assert_mirrors(self,graph,text):
        d=graph['director']['inputs'];b=json.loads(d['builder_state']);tl=json.loads(d['timeline_data'])
        self.assertEqual(d['prompt'],text);self.assertEqual(b['simple_prompt'],text);self.assertEqual(b['prompt_mode'],'simple')
        self.assertEqual(tl['builder_state']['simple_prompt'],text);self.assertEqual(tl['resolved_prompt'],text);self.assertEqual(tl['continuity']['continuation_prompt'],text)
        self.assertEqual(b['unchanged'],'KEEP');self.assertEqual(tl['continuity']['keep'],'KEEP');self.assertEqual(tl['items'],[{'synthetic_reference':'KEEP'}])

    def test_repeated_whole_queue_apply_updates_actual_dasiwa_builder_and_all_mirrors(self):
        self.with_builder()
        def apply(pid,graph,expected_graph):
            self.assertEqual(self.raw['queue_pending'][0][2],expected_graph)
            self.raw['queue_pending'][0][2]=graph
            return {'prompt_verified':True}
        self.replace.side_effect=apply
        helper_path=ROOT/'ComfyUI/custom_nodes/ComfyUI-DaSiWa-Nodes/nodes/helper_minimax_h3_prompt_builder.py'
        native=None
        if helper_path.exists():
            spec=importlib.util.spec_from_file_location('synthetic_native_prompt_helper',helper_path);native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
        for text in ('summary: First revision.','summary: Second revision.','summary: Third revision.'):
            snapshot=self.env['production_queue_snapshot']()
            result=self.env['production_write_api']('/api/production-assistant/patch-queue',{'all_pending':True,'prompt':text},snapshot)
            self.assertEqual(result['verified_count'],1);graph=self.raw['queue_pending'][0][2]
            self.assert_mirrors(graph,text)
            if native:self.assertEqual(native.build_prompt(json.loads(graph['director']['inputs']['builder_state'])),text)
            self.assertEqual(graph['other'],self.graph['other']);self.assertEqual(self.db[0]['ui']['final'],text)
        self.assertEqual(self.raw['queue_pending'][0][0:2],[1,'b']);self.assertEqual(self.replace.call_count,3)

    def test_partial_patch_updates_native_mirrors_and_external_literal(self):
        self.with_builder();self.graph['director']['inputs']['external_prompt_overwrite']=self.graph['director']['inputs']['prompt']
        snapshot=self.env['production_queue_snapshot']();snapshot['prompt_hashes']={'b':hashlib.sha256(self.graph['director']['inputs']['prompt'].encode()).hexdigest()}
        self.env['production_write_api']('/api/production-assistant/patch-queue',{'id':'b','edits':[{'before':'slowly','after':'quickly'}]},snapshot)
        graph=self.replace.call_args.args[1];self.assert_mirrors(graph,graph['director']['inputs']['prompt'])
        self.assertEqual(graph['director']['inputs']['external_prompt_overwrite'],graph['director']['inputs']['prompt'])

    def test_invalid_builder_or_connected_override_never_submits_or_changes_original(self):
        for bad in ({'builder_state':'bad json'},{'builder_state':'[]'},{'timeline_data':'[]'},{'external_prompt_overwrite':['linked',0]}):
            graph=json.loads(json.dumps(self.graph));graph['director']['inputs'].update(bad);before=json.loads(json.dumps(graph))
            with self.assertRaises(ValueError):self.env['production_prompt_graph'](graph,'New synthetic prompt.')
            self.assertEqual(graph,before)
        self.replace.assert_not_called()

    def test_repair_only_confirmed_saved_pending_edits_and_dry_run_has_no_effect(self):
        self.with_builder();old=self.graph['director']['inputs']['prompt'];new='summary: Saved revision.'
        self.graph['director']['inputs']['prompt']=new;self.db[0].update(prompt=new,edited_at=1);self.db[0]['ui']['final']=new
        running=json.loads(json.dumps(self.graph));self.raw['queue_running']=[[0,'running',running,{},[]]];self.db.append({'id':'running','prompt':new,'edited_at':1,'ui':{'final':new}})
        result=self.env['production_repair_prompt_state']();self.assertEqual(result['eligible'],1);self.replace.assert_not_called()
        result=self.env['production_repair_prompt_state'](False);self.assertEqual(result['repaired'],1)
        self.assertEqual(self.replace.call_args.args[0],'b');self.assert_mirrors(self.replace.call_args.args[1],new)
        self.assertEqual(json.loads(running['director']['inputs']['builder_state'])['simple_prompt'],old)
        self.assertFalse(any(key in result for key in ('prompt','id','images')))
        self.replace.reset_mock();self.db[0]['ui']['final']='Different edit.'
        self.assertEqual(self.env['production_repair_prompt_state'](False)['eligible'],0);self.replace.assert_not_called()

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

    def test_bulk_prompt_patch_covers_more_than_one_page_and_preserves_each_graph(self):
        self.raw['queue_pending']=[];self.db.clear()
        for number in range(25):
            graph={'director':{'inputs':{'prompt':f'Unique scene {number}. Common text.'}},'other':{'inputs':{'seed':number}}}
            self.raw['queue_pending'].append([number,f'job-{number}',graph,{},[]]);self.db.append({'id':f'job-{number}','images':['PRIVATE_PHOTO'],'ui':{}})
        self.raw['queue_pending'].append([30,'foreign',self.graph,{},[]])
        self.raw['queue_running']=[[0,'running',self.graph,{},[]]];self.db.append({'id':'running'})
        snapshot=self.env['production_queue_snapshot']()
        result=self.env['production_write_api']('/api/production-assistant/patch-queue',{'all_pending':True,'edits':[{'before':'Common text.','after':'Revised common text.'}]},snapshot)
        self.assertEqual(result['target_count'],25);self.assertEqual(result['updated_count'],25);self.assertEqual(result['verified_count'],25)
        status=self.env['BULK_PROGRESS'].snapshot();self.assertEqual(status['processed'],25);self.assertEqual(status['state'],'done');self.assertEqual(status['verified'],25)
        for number,call in enumerate(self.replace.call_args_list):
            pid,graph=call.args
            self.assertEqual(pid,f'job-{number}');self.assertEqual(graph['other']['inputs']['seed'],number)
            self.assertEqual(graph['director']['inputs']['prompt'],f'Unique scene {number}. Revised common text.')
            self.assertEqual(call.kwargs['expected_graph']['director']['inputs']['prompt'],f'Unique scene {number}. Common text.')
        self.assertEqual(self.db[0]['images'],['PRIVATE_PHOTO']);self.assertEqual([r[1] for r in self.raw['queue_pending']], [f'job-{n}' for n in range(25)]+['foreign'])
        self.assertEqual(self.raw['queue_running'][0][1],'running')

    def test_real_six_hundred_assistant_batch_uses_shared_editor_and_preserves_graph_settings(self):
        from queue_bulk import QueueBulkEditor
        from test_queue_bulk import Backend
        import tempfile,copy
        backend=Backend(0);self.db.clear()
        for index in range(600):
            graph={'director':{'inputs':{'prompt':f'Synthetic scene {index}. Common text.'}},'other':{'inputs':{'seed':index}}}
            backend.pending.append([index,f'synthetic-{index}',graph,{'synthetic_metadata':index},[]])
            self.db.append({'id':f'synthetic-{index}','images':['SYNTHETIC'],'ui':{'f':{'summary':'Synthetic'}},'seed':index})
        backend.running=[[-1,'running',copy.deepcopy(backend.pending[0][2]),{},[]]]
        self.env['comfy']=backend.request
        with tempfile.TemporaryDirectory() as tmp:
            def save(path,value):
                from pathlib import Path
                Path(path).write_text(json.dumps(value),encoding='utf8')
            self.env['bulk_queue_editor']=lambda:QueueBulkEditor(backend.request,self.env['QUEUE_EDIT_LOCK'],tmp,save,self.env['commit_bulk_history'])
            snapshot={'items':[],'prompt_hashes':{}}
            result=self.env['production_write_api']('/api/production-assistant/patch-queue',
                {'all_pending':True,'edits':[{'before':'Common text.','after':'Updated common text.'}]},snapshot)
        self.assertEqual(result['verified_count'],600);self.assertEqual(result['failed'],[])
        self.assertEqual(sum(path=='/queue' and body is None for path,body in backend.calls),49)
        self.assertEqual(self.env['_save_json'].call_count,24)
        self.assertEqual(backend.running[0][1],'running')
        saved={entry['id']:entry for entry in self.db}
        for row in backend.pending:
            index=row[0];text=f'Synthetic scene {index}. Updated common text.'
            self.assertEqual(row[2]['director']['inputs']['prompt'],text)
            self.assertEqual(row[2]['other']['inputs']['seed'],index)
            self.assertEqual(saved[row[1]]['seed'],index)
            self.assertEqual(saved[row[1]]['images'],['SYNTHETIC'])
            self.assertEqual(saved[row[1]]['ui']['final'],text)
        self.assertEqual(self.env['BULK_PROGRESS'].snapshot()['verified'],600)

    def test_selected_batch_reports_mismatches_and_does_not_touch_foreign_jobs(self):
        self.raw['queue_pending'].append([2,'c',{'director':{'inputs':{'prompt':'Different content.'}}},{},[]]);self.db.append({'id':'c'})
        snapshot=self.env['production_queue_snapshot']()
        result=self.env['production_write_api']('/api/production-assistant/patch-queue',{'ids':['b','c'],'edits':[{'before':'slowly','after':'fast'}]},snapshot)
        self.assertEqual(result['updated_count'],1);self.assertEqual([x['id'] for x in result['failed']],['c'])
        status=self.env['BULK_PROGRESS'].snapshot();self.assertEqual(status['processed'],2);self.assertEqual(status['failed'],1);self.assertEqual(status['succeeded'],1)
        self.assertEqual(self.replace.call_count,1)
        with self.assertRaises(ValueError):self.env['production_write_api']('/api/production-assistant/patch-queue',{'ids':['foreign'],'edits':[{'before':'slowly','after':'fast'}]},snapshot)

    def test_bulk_race_never_changes_a_started_job(self):
        snapshot=self.env['production_queue_snapshot']();original=self.env['comfy'];reads=[0]
        def race(path,data=None,headers=None):
            if path=='/queue' and data is None:
                reads[0]+=1
                if reads[0]==2:self.raw['queue_running']=self.raw['queue_pending'];self.raw['queue_pending']=[]
            return original(path,data,headers)
        self.env['comfy']=race
        result=self.env['production_write_api']('/api/production-assistant/patch-queue',{'all_pending':True,'edits':[{'before':'slowly','after':'fast'}]},snapshot)
        self.assertEqual(result['updated_count'],0);self.assertEqual(len(result['failed']),1);self.replace.assert_not_called()

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
