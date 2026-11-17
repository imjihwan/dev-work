"""Prompt helper validation and resource limits without loading a model."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prompt_helper_test", Path(os.environ.get("PROMPT_HELPER_TEST_SOURCE", ROOT / "simple_ui")) / "prompt_helper.py")
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class PromptHelperTests(unittest.TestCase):
    def test_dutchit_keeps_existing_contract_and_rejects_unsupported_choices(self):
        fixed={'subject':'  Synthetic identity.\n','style':'Initial continuous zoom, then hold.  ','keep':'Same face and outfit.\n'}
        request=HELPER.validate_request({'idea':'Slide a block.','engine':'dutchit','duration':5,'one_take':True,'anchor':True,'reference_count':3,'fixed':fixed,'images':['PRIVATE'],'history':'PRIVATE'})
        self.assertEqual(request['fixed'],fixed);self.assertTrue(request['one_take']);self.assertTrue(request['anchor'])
        self.assertEqual(request['reference_count'],3);self.assertNotIn('PRIVATE',json.dumps(request))
        self.assertEqual(HELPER.validate_request({'idea':'Synthetic action.'})['engine'],'legacy','Old clients retain their original engine without data migration')
        for extra in ({'engine':'unknown'},{'reference_count':10},{'reference_count':True},{'anchor':'yes'}):
            with self.assertRaises(ValueError):HELPER.validate_request({'idea':'Synthetic action.',**extra})

    def test_dutchit_cpu_model_is_explicit_and_does_not_replace_legacy_model(self):
        helper=HELPER.PromptHelper(ROOT/'local-prompt-helper');original=helper.model
        args=helper.command(12345,'dutchit')
        self.assertEqual(args[args.index('-m')+1],str(helper.dutchit_model));self.assertEqual(helper.model,original)
        for flag,value in (('-ngl','0'),('-t','2'),('-tb','2'),('-c','8192'),('--host','127.0.0.1')):self.assertEqual(args[args.index(flag)+1],value)

    def test_dutchit_insufficient_ram_never_falls_back_or_spawns(self):
        with tempfile.TemporaryDirectory() as temp:
            helper=HELPER.PromptHelper(temp);helper.exe.parent.mkdir();helper.exe.touch();helper.dutchit_model.touch();helper.model.touch()
            with patch.object(HELPER,'available_memory',return_value=7*1024**3),patch.object(HELPER.subprocess,'Popen') as spawn:
                with self.assertRaisesRegex(ValueError,'8GB'):helper.start({'idea':'Synthetic action.','engine':'dutchit'})
                spawn.assert_not_called()

    def test_dutchit_rejects_new_camera_cuts_and_invalid_references(self):
        request=HELPER.validate_request({'idea':'Move a block.','engine':'dutchit','one_take':True,'reference_count':1})
        for text in ('The camera cuts to another view.','The camera zooms out.','A medium shot shows the block.','Follow <Picture 2>.'):
            with self.assertRaises(ValueError):HELPER.enforce_dutchit_constraints({'f':{'summary':'Move.'},'shots':[[0,text]]},request)
        HELPER.enforce_dutchit_constraints({'f':{'summary':'The block moves.'},'shots':[[0,'The subject looks toward the camera and waves.']]},request)

    def test_dutchit_partial_edit_does_not_revalidate_or_migrate_unchanged_text(self):
        request=HELPER.validate_request({'idea':'Change only the music.','engine':'dutchit','one_take':True,'context':{'summary':'Old summary.','music':'N/A','shots':[['0.00','Existing camera instruction remains byte-for-byte.']]}})
        result=HELPER.apply_edits({'edits':[{'target':'music','index':0,'before':'N/A','after':'Gentle piano.'}]},request)
        HELPER.enforce_dutchit_constraints(result,request)
        self.assertEqual(result['f'],{'music':'Gentle piano.'});self.assertNotIn('shots',result)

    def test_dutchit_context_limit_rejects_before_generation(self):
        import io
        helper=HELPER.PromptHelper();helper.active_engine='dutchit'
        responses=[io.BytesIO(json.dumps({'prompt':'SYNTHETIC'}).encode()),io.BytesIO(json.dumps({'tokens':[1]*7000}).encode())]
        with patch.object(HELPER.urllib.request,'urlopen',side_effect=responses) as send:
            with self.assertRaisesRegex(ValueError,'문맥 한도'):helper._complete('http://127.0.0.1:12345','Synthetic system',{'idea':'Synthetic'},HELPER.SCHEMA,1900,.2)
        self.assertEqual(send.call_count,2,'No completion request may truncate the fixed constraints')

    def test_multilingual_requested_objects_are_preserved_with_uncertainty_notes(self):
        for idea in ("컵을 들고 미소 지어 주세요.", "컵을 hold하고 smile해 주세요.", "本を持って微笑んでください。"):
            with self.subTest(idea=idea):
                text="She holds a cup and smiles."
                draft={"f":{"summary":text},"shots":[[0,text]]}
                notes=HELPER.ground_draft(draft,{"idea":idea,"fixed":{},"existing":{}})
                self.assertEqual(draft,{"f":{"summary":text},"shots":[[0,text]]})
                self.assertTrue(notes)
                self.assertTrue(all(not note['removed'] and note['language_uncertain'] for note in notes))
                issues=HELPER.unrequested_issues(notes)
                self.assertTrue(all(issue['category']=='uncertainty' for issue in issues))
                self.assertTrue(all('요청에 없는' not in issue['issue'] for issue in issues))

    def test_multilingual_edit_terms_do_not_accuse_requested_translations(self):
        notes=HELPER.flag_edit_terms({'changes':[{'after':'She holds a cup and smiles.'}]},{'idea':'컵을 들어 주세요.'})
        self.assertTrue(notes[0]['language_uncertain'])
        self.assertEqual(HELPER.unrequested_issues(notes)[0]['category'],'uncertainty')

    def test_request_only_passes_opted_in_text(self):
        request = HELPER.validate_request({"idea": "safe idea", "images": ["must not pass"], "history": "private", "duration": 5})
        self.assertNotIn("images", request)
        self.assertNotIn("history", request)
        self.assertNotIn("existing", request)
        request = HELPER.validate_request({"idea": "safe idea", "context": {"summary": "safe text", "photos": ["private"], "shots": [[0,"safe"]]}})
        self.assertEqual(request["existing"], {"summary": "safe text", "shots": [[0, "safe"]]})
        request = HELPER.validate_request({"idea":"safe", "fixed":{"subject":"the subject","style":"fixed camera","keep":"face and outfit","images":["private"]}})
        self.assertEqual(request["fixed"], {"subject":"the subject","style":"fixed camera","keep":"face and outfit"})

    def test_blank_and_invalid_duration_rejected(self):
        for request in ({"idea":" "},{"idea":"safe", "duration":"nan"},{"idea":"safe", "duration":20}):
            with self.assertRaises(ValueError): HELPER.validate_request(request)

    def test_draft_can_only_change_content_fields(self):
        draft = {key:"safe" for key in HELPER.FIELDS}
        draft.update(shots=[{"time":0,"text":"safe action"}], images=["bad"], model="bad", seed=999,
            subject="replacement subject",style="replacement camera",keep="replacement outfit")
        result = HELPER.validate_draft(draft,5)
        self.assertEqual(set(result), {"f", "shots"})
        self.assertEqual(set(result["f"]), set(HELPER.FIELDS))
        self.assertEqual(set(result["f"]), {"summary","sound","music"})
        self.assertEqual(result["shots"], [[0,HELPER.REFERENCE_APPEARANCE+" safe action"]])
        self.assertTrue(set(HELPER.FIXED_FIELDS).isdisjoint(HELPER.SCHEMA["properties"]))
        draft["shots"][0]["time"] = 5
        with self.assertRaises(ValueError): HELPER.validate_draft(draft,5)

    def test_runtime_is_cpu_only_and_bounded(self):
        helper = HELPER.PromptHelper(ROOT / "local-prompt-helper")
        args = helper.command(12345)
        for flag,value in (("-ngl","0"),("-t","2"),("-tb","2"),("-np","1"),("-c","8192"),("--host","127.0.0.1"),("--cache-ram","0")):
            self.assertEqual(args[args.index(flag)+1],value)
        self.assertIn("--log-disable",args)
        self.assertIn("--no-webui",args)

    def test_low_ram_does_not_start_any_process(self):
        with tempfile.TemporaryDirectory() as temp:
            helper = HELPER.PromptHelper(temp)
            helper.exe.parent.mkdir()
            helper.exe.touch();helper.model.touch()
            with patch.object(HELPER,"available_memory",return_value=3*1024**3), patch.object(HELPER.subprocess,"Popen") as spawn:
                with self.assertRaisesRegex(ValueError,"4GB"): helper.start({"idea":"safe"})
                spawn.assert_not_called()

    def test_cancel_rejects_different_request_id(self):
        helper=HELPER.PromptHelper()
        helper.job={"id":"owned", "state":"generating"}
        with self.assertRaises(ValueError): helper.cancel("other")
        self.assertFalse(helper.cancel_event.is_set())
        helper.cancel("owned")
        self.assertTrue(helper.cancel_event.is_set())

    def edit_request(self, **extra):
        return HELPER.validate_request(dict(idea="Change only the music to gentle piano.",duration=5,
            context={"summary":"  A cup rotates.\n","sound":"Quiet room.  ","music":"N/A",
                "shots":[["0.00","The cup rotates slowly."],["2.50","It stops.  "]]},**extra))

    def test_edit_changes_one_field_without_rewriting_other_text_or_shots(self):
        request=self.edit_request()
        result=HELPER.apply_edits({"edits":[{"target":"music","index":0,"before":"N/A","after":"Gentle piano music."}]},request)
        self.assertEqual(result["f"],{"music":"Gentle piano music."})
        self.assertNotIn("shots",result)
        self.assertNotIn("final",result)
        self.assertEqual(request["existing"]["summary"],"  A cup rotates.\n")
        self.assertEqual(request["existing"]["shots"][1],["2.50","It stops.  "])

    def test_edit_preserves_all_other_shots_and_exact_timing(self):
        request=self.edit_request()
        result=HELPER.apply_edits({"edits":[{"target":"shot_text","index":0,"before":"slowly","after":"very slowly"}]},request)
        self.assertEqual(result["shots"],[["0.00","The cup rotates very slowly."],["2.50","It stops.  "]])
        self.assertEqual(result["f"],{})
        self.assertNotIn(HELPER.REFERENCE_APPEARANCE,result["shots"][0][1])

    def test_unmatched_ambiguous_and_fixed_edits_are_rejected_atomically(self):
        request=self.edit_request()
        for target,before in (("style",""),("summary","not present"),("shot_text","not present")):
            with self.subTest(target=target):
                with self.assertRaises(ValueError): HELPER.apply_edits({"edits":[{"target":target,"index":0,"before":before,"after":"new"}]},request)
        request["existing"]["summary"]="cup cup"
        with self.assertRaises(ValueError): HELPER.apply_edits({"edits":[{"target":"summary","index":0,"before":"cup","after":"mug"}]},request)
        self.assertEqual(request["existing"]["summary"],"cup cup")

    def test_manual_prompt_changes_only_the_exact_requested_words(self):
        text="subject_definitions: The subject in <Picture 1>.\n\nsummary: A cup rotates.\n\nretention_analysis: Keep appearance.\n\ndetailed_description: Fixed camera. The cup rotates slowly.\n\noverall_soundscape: Quiet room.\n\nnon_diegetic_music: N/A\n"
        request=self.edit_request(manual_prompt=text,fixed={"style":"Fixed camera."})
        result=HELPER.apply_edits({"edits":[{"target":"prompt","index":0,"before":"rotates slowly","after":"rotates very slowly"}]},request)
        self.assertEqual(result["final"],text.replace("rotates slowly","rotates very slowly"))
        self.assertEqual(result["f"],{})
        self.assertNotIn("shots",result)
        for before in ("The subject in <Picture 1>.","Keep appearance.","Fixed camera."):
            with self.assertRaises(ValueError): HELPER.apply_edits({"edits":[{"target":"prompt","index":0,"before":before,"after":"changed"}]},request)
        wrapped=HELPER.apply_edits({"edits":[{"target":"prompt","index":0,"before":"non_diegetic_music: N/A","after":"non_diegetic_music: Gentle piano."}]},request)
        self.assertEqual(wrapped["final"],text.replace("N/A","Gentle piano."))
        self.assertEqual(wrapped["changes"][0]["before"],"N/A")
        self.assertEqual(wrapped["changes"][0]["after"],"Gentle piano.")

    def test_edit_does_not_truncate_the_current_text(self):
        original="Unchanged text. "*70
        request=HELPER.validate_request({"idea":"safe","context":{"summary":original,"shots":[["0.0000",original]]}})
        self.assertEqual(request["existing"]["summary"],original)
        self.assertEqual(request["existing"]["shots"],[["0.0000",original]])
        result=HELPER.apply_edits({"edits":[]},request)
        self.assertEqual(result["f"],{})
        self.assertNotIn("shots",result)

    def test_review_only_accepts_current_text_without_idea_and_filters_private_inputs(self):
        request=HELPER.validate_request({"review_only":True,"context":{"summary":"A block slides.","shots":[[0,"The block slides."]]},
            "images":["private"],"history":"private"})
        self.assertTrue(request["review_only"])
        self.assertNotIn("images",request);self.assertNotIn("history",request)
        with self.assertRaises(ValueError): HELPER.validate_request({"review_only":True,"context":{}})

    def test_review_sees_resulting_edit_without_altering_unrequested_text(self):
        request=self.edit_request()
        edited=HELPER.apply_edits({"edits":[{"target":"music","index":0,"before":"N/A","after":"Piano."}]},request)
        candidate=HELPER.review_candidate(request,edited)["candidate"]
        self.assertEqual(candidate["music"],"Piano.")
        self.assertEqual(candidate["summary"],request["existing"]["summary"])
        self.assertEqual(candidate["shots"],request["existing"]["shots"])
        self.assertEqual(request["existing"]["music"],"N/A")
        manual=self.edit_request(manual_prompt="summary: Original action.")
        self.assertEqual(HELPER.review_candidate(manual,{"final":"summary: Updated action."})["candidate"],{"manual_prompt":"summary: Updated action."})

    def test_numeric_timing_check_overrides_model_ok_verdict(self):
        verdict={"status":"ok","summary":"검토 결과","issues":[]}
        for times in ([0,0],[0,3,2],[0,5],[1,2],[0,"nan"]):
            content={"duration":5,"candidate":{"shots":[[value,"Synthetic action."] for value in times]}}
            result=HELPER.validate_review(verdict,content)
            self.assertEqual(result["status"],"revise");self.assertEqual(result["issues"][0]["category"],"timing")
        result=HELPER.validate_review(verdict,{"duration":5,"candidate":{"shots":[[0,"Start."],[3,"Settle."]]}})
        self.assertEqual(result["status"],"ok");self.assertEqual(result["issues"],[])

    def test_review_severity_cannot_be_hidden_by_overall_ok(self):
        result=HELPER.validate_review({"status":"ok","summary":"검토 결과","issues":[{
            "severity":"critical","category":"physics","at":"0–1초","evidence":"Synthetic conflict","issue":"동작 충돌","suggestion":"한 동작으로 줄이세요."}]},
            {"duration":5,"candidate":{"summary":"Synthetic conflict"}})
        self.assertEqual(result["status"],"revise")
        with self.assertRaises(ValueError): HELPER.validate_review({"status":"guaranteed","summary":"", "issues":[]},{"candidate":{}})

    def run_fake_model(self,body,answers):
        helper=HELPER.PromptHelper()
        helper.job={"id":"synthetic-only","state":"starting"}
        process=MagicMock();process.poll.return_value=None
        response=MagicMock();response.__enter__.return_value.status=200
        with patch.object(HELPER.subprocess,"Popen",return_value=process),patch.object(HELPER.urllib.request,"urlopen",return_value=response),\
             patch.object(HELPER,"available_memory",return_value=8*1024**3),patch.object(helper,"_complete",side_effect=answers) as complete:
            helper._run(HELPER.validate_request(body))
        return helper.job,complete

    def test_draft_runs_independent_review_and_keeps_report_out_of_prompt(self):
        generated={"summary":"A block slides slowly.","sound":"Quiet room.","music":"N/A","shots":[{"time":0,"text":"The block moves smoothly then settles."}]}
        verdict={"status":"caution","summary":"속도를 확인하세요.","issues":[{"severity":"warning","category":"uncertainty","at":"",
            "evidence":"block","issue":"원본의 이동 여유 공간은 확인되지 않았습니다.","suggestion":"원본 사진에서 이동 경로를 확인하세요."}]}
        details="The same block begins sliding gradually along its established path. Its movement is continuous as it leaves the starting position, without lifting from its existing support. It maintains a steady pace during the central part of the motion, then decelerates smoothly and settles without bouncing."
        job,complete=self.run_fake_model({"idea":"Move a block slowly in five seconds.","duration":5,"detail":True},[generated,{"beat_1":details},verdict])
        self.assertEqual(job["state"],"done");self.assertEqual(complete.call_count,3)
        self.assertGreater(complete.call_args_list[0].args[4],1000)
        self.assertEqual(complete.call_args_list[1].args[1],HELPER.DETAIL_SYSTEM)
        self.assertEqual(complete.call_args_list[-1].args[1],HELPER.REVIEW_SYSTEM)
        self.assertEqual(job["draft"]["shots"][0][0],0)
        self.assertEqual(job["draft"]["shots"][0][1],HELPER.REFERENCE_APPEARANCE+" "+details)
        self.assertEqual(job["draft"]["f"]["summary"],generated["summary"])
        self.assertEqual(job["draft"]["review"]["status"],"caution")
        self.assertNotIn("review",job["draft"]["f"])

    def test_new_draft_is_not_expanded_unless_detail_requested(self):
        generated={"summary":"A block slides slowly.","sound":"Quiet room.","music":"N/A","shots":[{"time":0,"text":"The block moves smoothly then settles."}]}
        job,complete=self.run_fake_model({"idea":"Move a block slowly.","duration":5},[generated,{"status":"ok","summary":"문제 없음","issues":[]}])
        self.assertEqual(job["state"],"done");self.assertEqual(complete.call_count,2)
        self.assertNotIn(HELPER.DETAIL_SYSTEM,[call.args[1] for call in complete.call_args_list])

    def test_unrequested_appearance_and_props_are_removed_and_reported(self):
        generated={"summary":"A person waves and walks to the window.","sound":"Quiet room.","music":"N/A","shots":[
            {"time":0,"text":"The subject stands in a sunlit living room holding a white teapot. The subject raises one hand and waves."},
            {"time":2,"text":"They plant both feet, shift weight to the balls of the feet and walk toward the window."}]}
        job,_=self.run_fake_model({"idea":"A person waves, then walks slowly to the window.","duration":5},[generated,{"status":"ok","summary":"문제 없음","issues":[]}])
        shots=job["draft"]["shots"]
        self.assertNotIn("teapot",shots[0][1]);self.assertIn("raises one hand and waves",shots[0][1])
        self.assertIn("plant both feet",shots[1][1]);self.assertIn("window",shots[1][1])  # 요청에 있는 단어·동작 표현은 유지
        self.assertEqual(job["draft"]["review"]["status"],"caution")
        issue=job["draft"]["review"]["issues"][0]
        self.assertEqual(issue["category"],"constraints");self.assertIn("teapot",issue["issue"])

    def test_only_the_invented_phrase_or_clause_is_cut(self):
        allowed="A person waves, smiles, then walks slowly to the window. She lifts a teapot."
        cases={
            "The subject, wearing a blue jacket, raises one hand and waves.":"The subject raises one hand and waves.",
            "The subject stands in a sunlit living room holding a white teapot.":"The subject stands holding a teapot.",
            "They walk toward the window, their jacket swaying slightly.":"They walk toward the window.",
            "The subject holds a book and smiles warmly.":"The subject smiles warmly.",
            "She waves in a white shirt and black jeans.":"She waves.",
            "The subject sits at the table and looks toward the window.":"The subject sits and looks toward the window.",
        }
        for before,after in cases.items():
            with self.subTest(before=before):
                text,notes=HELPER.strip_unrequested(before,allowed)
                self.assertEqual(text,after)
                self.assertTrue(notes[0]["removed"]);self.assertTrue(notes[0]["fragment"])
        # 요청에 있는 단어만 든 문장은 그대로
        self.assertEqual(HELPER.strip_unrequested("She lifts a teapot toward the window.",allowed),("She lifts a teapot toward the window.",[]))

    def test_shot_whose_only_action_would_vanish_is_kept_and_flagged(self):
        text,notes=HELPER.strip_unrequested("The subject holds a book.","A person waves.")
        self.assertEqual(text,"The subject holds a book.")
        self.assertEqual([note["removed"] for note in notes],[False])
        issue=HELPER.unrequested_issues([dict(notes[0],where="장면 1")])[0]["issue"]
        self.assertIn("book",issue);self.assertIn("확인",issue)

    def test_cut_phrase_is_named_in_the_review_issue(self):
        _,notes=HELPER.strip_unrequested("The subject, wearing a blue jacket, raises one hand and waves.","A person waves.")
        issue=HELPER.unrequested_issues([dict(notes[0],where="장면 1")])[0]["issue"]
        self.assertIn("wearing a blue jacket",issue)

    def test_terms_named_in_request_or_fixed_fields_are_kept(self):
        request={"idea":"She lifts the teapot.","fixed":{"style":"A quiet kitchen, static camera."}}
        draft={"f":{"summary":"She lifts the teapot in the kitchen."},"shots":[[0,"She lifts the teapot from the counter in the kitchen."]]}
        self.assertEqual(HELPER.ground_draft(draft,request),[])
        self.assertIn("teapot",draft["shots"][0][1])

    def test_beat_times_are_spread_over_the_whole_video(self):
        R=HELPER.REFERENCE_APPEARANCE
        shots=[[0,R+" The subject nods twice, the head dipping forward and back in a steady rhythm."],
               [1.2,"A soft laugh breaks out, shoulders lifting slightly."],[1.8,"The subject turns the head to look to the side."]]
        spread=HELPER.spread_times(shots,5)
        times=[when for when,_ in spread]
        self.assertEqual(times[0],0);self.assertTrue(all(b>a for a,b in zip(times,times[1:])));self.assertLess(times[-1],5)
        lengths=[b-a for a,b in zip(times,times[1:]+[5])]
        self.assertGreaterEqual(min(lengths),1.0)          # 앞쪽에 몰리지 않는다(원래 0.6초 구간)
        self.assertLess(max(lengths)-min(lengths),1.0)      # 마지막 장면만 길게 남지 않는다
        self.assertEqual([text for _,text in spread],[text for _,text in shots])  # 순서·문장은 그대로
        self.assertEqual(HELPER.spread_times([[0,"Only one beat."]],5),[[0,"Only one beat."]])

    def test_failed_review_keeps_draft_and_reports_incomplete(self):
        generated={"summary":"A block slides.","sound":"Quiet room.","music":"N/A","shots":[{"time":0,"text":"A block slides."}]}
        job,_=self.run_fake_model({"idea":"Slide a block."},[generated,ValueError("synthetic expansion failure"),ValueError("synthetic review failure")])
        self.assertEqual(job["state"],"done");self.assertEqual(job["draft"]["review"]["status"],"unavailable")
        self.assertEqual(job["draft"]["f"]["summary"],generated["summary"])

    def test_partial_edit_is_not_expanded_or_repaired_by_review(self):
        body={"idea":"Change only the music to piano.","duration":5,"context":{"summary":"  Exact summary.  ","sound":"Original room tone.","music":"N/A","shots":[["0.00","Exact short action."]]}}
        patch_output={"edits":[{"target":"music","index":0,"before":"N/A","after":"Piano."}]}
        report={"status":"revise","summary":"원문 동작을 확인해 주세요.","issues":[{"severity":"critical","category":"timing","at":"0–5초","evidence":"Exact short action.","issue":"별도 점검 사항","suggestion":"동작 수정을 별도로 요청하세요."}]}
        job,complete=self.run_fake_model(body,[patch_output,report])
        self.assertEqual(complete.call_count,2);self.assertEqual(job["draft"]["f"],{"music":"Piano."})
        self.assertNotIn("shots",job["draft"])
        self.assertEqual(complete.call_args_list[-1].args[2]["candidate"]["summary"],"  Exact summary.  ")

    def test_review_only_skips_generation_and_preserves_story_context(self):
        body={"review_only":True,"duration":5,"context":{"summary":"A block stops.","shots":[[0,"The block decelerates."]]},
            "story_context":{"clip_index":2,"scenarios":["Start.","Slide.","Stop.","Hold."],"opening_state":"Moving.","ending_state":"Stopped."}}
        job,complete=self.run_fake_model(body,[{"status":"ok","summary":"큰 충돌이 검출되지 않았습니다.","issues":[]}])
        self.assertEqual(complete.call_count,1);self.assertTrue(job["draft"]["review_only"])
        self.assertEqual(complete.call_args.args[2]["story_context"]["clip_index"],2)
        self.assertEqual(job["draft"]["f"],{})

    def test_review_rejects_invented_evidence_and_does_not_claim_success(self):
        content={"duration":5,"candidate":{"summary":"The cube makes a quarter turn.","shots":[[0,"It turns a quarter turn slowly."]]}}
        verdict={"status":"revise","summary":"Unsupported claim","issues":[{"severity":"critical","category":"physics","at":"0–5초",
            "evidence":"rotates 360 degrees every second","issue":"원문에 없는 회전량","suggestion":"속도를 줄이세요."}]}
        result=HELPER.validate_review(verdict,content)
        self.assertEqual(result["status"],"unavailable");self.assertEqual(result["issues"],[])
        self.assertNotIn("Unsupported",result["summary"])

    def test_review_accepts_quoted_source_labels_only_if_excerpt_really_exists(self):
        content={"duration":5,"candidate":{"shots":[[0,"The subject performs twenty full jumps."]]}}
        verdict={"status":"revise","summary":"동작 수를 줄이세요.","issues":[{"severity":"critical","category":"physics","at":"0–5초",
            "evidence":"candidate: 'performs twenty full jumps'","issue":"시간 안에 하기 어렵습니다.","suggestion":"동작 수를 줄이세요."}]}
        result=HELPER.validate_review(verdict,content)
        self.assertEqual(result["status"],"revise")
        self.assertEqual(result["issues"][0]["evidence"],"performs twenty full jumps")


    def test_dutchit_real_pipeline_uses_adapter_and_preserves_fixed_text(self):
        body={'idea':'A block moves slowly, then stops.','engine':'dutchit','duration':5,'one_take':True,'anchor':True,'fixed':{'subject':'  Original subject.  ','style':'A continuous initial zoom, then hold.','keep':'Original retention.'}}
        output={'summary':'The block moves and stops.','sound':'Quiet room tone.','music':'N/A','shots':[{'time':0,'text':'The block begins moving slowly, decelerates and settles.'}]}
        job,complete=self.run_fake_model(body,[output,{'status':'ok','summary':'문제 없음','issues':[]}])
        self.assertEqual(job['state'],'done');self.assertEqual(job['draft']['engine'],'dutchit')
        self.assertIn('DutchIT MiniMax H3',complete.call_args_list[0].args[1])
        self.assertEqual(complete.call_args_list[0].args[2]['fixed'],body['fixed'])
        self.assertTrue(complete.call_args_list[0].args[2]['anchor']);self.assertTrue(complete.call_args_list[0].args[2]['one_take'])
        self.assertTrue(set(HELPER.FIXED_FIELDS).isdisjoint(job['draft']['f']))


if __name__=="__main__": unittest.main()
