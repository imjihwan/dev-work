"""Prompt helper validation and resource limits without loading a model."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prompt_helper_test", ROOT / "simple_ui/prompt_helper.py")
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


class PromptHelperTests(unittest.TestCase):
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

    def test_terms_named_in_request_or_fixed_fields_are_kept(self):
        request={"idea":"She lifts the teapot.","fixed":{"style":"A quiet kitchen, static camera."}}
        draft={"f":{"summary":"She lifts the teapot in the kitchen."},"shots":[[0,"She lifts the teapot from the counter in the kitchen."]]}
        self.assertEqual(HELPER.ground_draft(draft,request),[])
        self.assertIn("teapot",draft["shots"][0][1])

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


if __name__=="__main__": unittest.main()
