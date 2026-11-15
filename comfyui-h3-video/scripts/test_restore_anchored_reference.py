"""Synthetic rollback fixtures; never read real history, backups, photos or results."""
import copy
import unittest

from scripts import apply_queued_style as helper
from scripts import restore_anchored_reference as restore
from scripts import test_apply_queued_style as fixtures


class RestoreTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.StyleTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.env=fixture.env
        self.original=copy.deepcopy(fixture.entry)
        keep='Keep the synthetic outfit. Preserve the original background unchanged.'
        subject=helper.REFERENCE_SUBJECT_OLD_SINGLE+' Synthetic subject detail.'
        original_text=fixture.text.replace('Keep synthetic clothing.',keep+' '+helper.PREVIOUS_ONE_TAKE_KEEP).replace('Synthetic identity.',subject)
        self.original['prompt']=original_text
        self.original['ui']['f'].update(keep=keep,subject=subject)
        self.original['ui']['final']=original_text
        self.original_item=copy.deepcopy(fixture.item)
        self.original_item[2]=helper.patch_graph(fixture.item[2],self.env['DIRECTOR'],fixture.text,original_text)
        self.unlocked='Synthetic unlocked policy.';self.clear='Synthetic replacement pose policy.'
        first,graph=helper.prepare(self.original,self.original_item,self.unlocked,self.env,restore.UNLOCKED_ONE_TAKE,True,True)
        current=copy.deepcopy(self.original);current.update(prompt=first['prompt'],anchor=False)
        current['ui']['f'].update(first['ui']['f']);current['ui']['final']=first['ui']['final']
        item=copy.deepcopy(self.original_item);item[2]=graph
        second,graph=helper.prepare(current,item,self.clear,self.env,disable_anchor=True,reference_role=True)
        current.update(prompt=second['prompt']);current['ui']['f'].update(second['ui']['f']);current['ui']['final']=second['ui']['final'];item[2]=graph
        self.current,self.item=current,item

    def prepare(self,original=True):
        return restore.prepare_restore(self.current,self.item,self.fixture.old,self.env,self.original if original else None,(self.unlocked,self.clear))

    def test_exact_original_prompt_and_graph_return_after_both_changes(self):
        body,graph=self.prepare()
        self.assertTrue(body['anchor'])
        self.assertEqual(body['prompt'],self.original['prompt'])
        self.assertEqual(body['ui']['final'],self.original['prompt'])
        self.assertEqual(body['ui']['f'],{key:self.original['ui']['f'][key] for key in ('style','keep','subject')})
        self.assertEqual(helper.semantic_graph(graph),helper.semantic_graph(self.original_item[2]))

    def test_later_scene_changes_and_settings_are_preserved(self):
        changed=self.current['prompt'].replace('A synthetic movement.','A later manually edited movement.')
        self.item[2]=helper.patch_graph(self.item[2],self.env['DIRECTOR'],self.current['prompt'],changed)
        self.current['prompt']=changed;self.current['ui']['final']=changed
        self.current['ui']['shots']=[[0,'A later manually edited movement.']]
        body,graph=self.prepare()
        self.assertIn('A later manually edited movement.',body['prompt'])
        self.assertNotIn('A synthetic movement.',body['prompt'])
        self.assertNotIn('shots',body['ui'])
        self.assertEqual(graph[self.env['SEED']],self.item[2][self.env['SEED']])

    def test_new_post_unlock_job_restores_only_known_common_clauses(self):
        body,graph=self.prepare(original=False)
        self.assertTrue(body['anchor'])
        self.assertIn(restore.RESTORED_BACKGROUND,body['prompt'])
        self.assertNotIn(helper.REFERENCE_BACKGROUND,body['prompt'])
        self.assertNotIn(helper.REFERENCE_POSE_SCOPE,body['prompt'])
        self.assertIn('Synthetic subject detail.',body['prompt'])
        self.assertIn('A synthetic movement.',body['prompt'])

    def test_restore_is_idempotent_and_unrelated_policy_is_rejected(self):
        body,graph=self.prepare()
        self.current.update(prompt=body['prompt'],anchor=True)
        self.current['ui']['f'].update(body['ui']['f']);self.current['ui']['final']=body['ui']['final'];self.item[2]=graph
        again,again_graph=self.prepare()
        self.assertEqual(again['prompt'],body['prompt'])
        self.assertEqual(again_graph,graph)
        self.current['ui']['f']['style']='A separate custom policy.'
        with self.assertRaises(helper.StyleMismatch):self.prepare()


if __name__=='__main__':unittest.main()
