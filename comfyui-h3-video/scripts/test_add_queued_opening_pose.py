"""Synthetic opening-action transformations; no live queue or media access."""
import copy
import unittest

from scripts import add_queued_opening_pose as opening
from scripts import apply_queued_style as helper
from scripts import test_apply_queued_style as fixtures


class OpeningTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.StyleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.prefix = "Synthetic 45-degree opening action.\n\nKeep the chosen side."

    def prepare(self):
        f = self.fixture
        return opening.prepare_opening(f.entry, f.item, f.old, f.env, self.prefix)

    def test_preserves_common_actions_times_settings_and_graph(self):
        f = self.fixture
        f.entry['ui']['shots'].append(['2.5', 'Later synthetic motion.'])
        original = copy.deepcopy(f.entry)
        body, expected = self.prepare()
        self.assertEqual(body['ui']['f'], {})
        self.assertEqual(body['ui']['shots'][0], [0, self.prefix + '\n\n' + original['ui']['shots'][0][1]])
        self.assertEqual(body['ui']['shots'][1:], original['ui']['shots'][1:])
        self.assertEqual(body['prompt'], original['prompt'].replace('A synthetic movement.', self.prefix + '\n\nA synthetic movement.'))
        self.assertEqual(f.entry, original)
        self.assertEqual(body['bulk_fields'], ['content'])
        self.assertEqual(helper.semantic_graph(helper.patch_graph(expected, f.env['DIRECTOR'], body['prompt'], original['prompt'])), helper.semantic_graph(f.item[2]))

    def test_manual_action_is_preserved_independently_of_saved_scene(self):
        f = self.fixture
        manual = f.text.replace('A synthetic movement.', 'A manual synthetic movement.')
        f.item[2] = helper.patch_graph(f.item[2], f.env['DIRECTOR'], f.text, manual)
        f.entry.update(prompt=manual)
        f.entry['ui']['final'] = manual
        body, _ = self.prepare()
        self.assertIn(self.prefix + '\n\nA manual synthetic movement.', body['prompt'])
        self.assertEqual(body['ui']['final'], body['prompt'])
        self.assertEqual(body['ui']['shots'][0][1], self.prefix + '\n\nA synthetic movement.')

    def test_idempotence_and_missing_saved_prefix_repair(self):
        f = self.fixture
        body, graph = self.prepare()
        f.entry['prompt'] = body['prompt']
        f.item[2] = graph
        # Final prompt already changed but visible scene not yet changed.
        next_body, _ = self.prepare()
        self.assertEqual(next_body['prompt'], body['prompt'])
        self.assertEqual(next_body['ui']['shots'], body['ui']['shots'])
        f.entry['ui'].update(body['ui'], f=f.entry['ui']['f'])
        repeated, graph2 = self.prepare()
        self.assertEqual(repeated, body)
        self.assertEqual(graph2, graph)

    def test_marker_and_blank_action_keep_section_boundaries(self):
        f = self.fixture
        for marker in ('', '[Shot 1] '):
            text = f.text.replace('A synthetic movement.', marker + 'A synthetic movement.')
            new = opening.prepend_prompt(text, f.old, self.prefix)
            self.assertIn(marker + self.prefix + '\n\nA synthetic movement.', new)
            self.assertEqual(opening.prepend_prompt(new, f.old, self.prefix), new)
        blank = 'detailed_description: ' + f.old + '\n\noverall_soundscape: Synthetic audio.'
        new = opening.prepend_prompt(blank, f.old, self.prefix)
        self.assertTrue(new.endswith(self.prefix + '\n\noverall_soundscape: Synthetic audio.'))
        self.assertEqual(opening.prepend_prompt(new, f.old, self.prefix), new)
        self.assertEqual(opening.prepend_action('', self.prefix), self.prefix)

    def test_rejects_nonzero_scene_custom_prompt_or_unanchored_job(self):
        f = self.fixture
        f.entry['ui']['shots'][0][0] = '2'
        with self.assertRaises(helper.StyleMismatch): self.prepare()
        f.entry['ui']['shots'][0][0] = 0
        f.entry['anchor'] = False
        with self.assertRaises(helper.StyleMismatch): self.prepare()
        with self.assertRaises(helper.StyleMismatch):
            opening.prepend_prompt('detailed_description: A custom standalone action.', f.old, self.prefix)


if __name__ == '__main__':
    unittest.main()
