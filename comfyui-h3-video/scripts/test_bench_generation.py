"""측정 도구의 계산·그래프 조립만 확인한다. ComfyUI·GPU·네트워크·실제 사진을 쓰지 않는다."""
import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bench_generation', ROOT / 'scripts/bench_generation.py')
B = importlib.util.module_from_spec(spec)
spec.loader.exec_module(B)


def event(at, kind, **data):
    return at, {'type': kind, 'data': {'prompt_id': 'job', **data}}


class TimingTests(unittest.TestCase):
    GRAPH = {'1': {'class_type': 'MiniMaxH3DirectorGuide'}, '2': {'class_type': 'SamplerCustomAdvanced'},
             '3': {'class_type': 'DaSiWaH3ContinuitySegmentDecode'}, '4': {'class_type': 'DaSiWa_EnhancedVideoCombine'}}

    def test_phases_and_steps_come_from_the_event_times(self):
        events = [event(100.0, 'execution_start'), event(100.0, 'execution_cached', nodes=['9', '8']),
                  event(100.0, 'executing', node='1'), event(105.0, 'executing', node='2'),
                  event(130.0, 'progress', node='2', value=1, max=3), event(150.0, 'progress', node='2', value=2, max=3),
                  event(171.0, 'progress', node='2', value=3, max=3), event(172.0, 'executing', node='3'),
                  event(186.0, 'executing', node='4'), event(189.0, 'executing', node=None), event(189.0, 'execution_success'),
                  (120.0, {'type': 'progress', 'data': {'prompt_id': 'someone-else', 'node': '2', 'value': 9, 'max': 9}})]
        timing, end, mine = B.timings(events, self.GRAPH, 'job', submitted=99.5)
        self.assertEqual(timing['total'], 89.0)
        self.assertEqual(timing['queued_to_start'], 0.5)
        self.assertEqual(timing['by_class']['SamplerCustomAdvanced'], 67.0)
        self.assertEqual(timing['by_class']['DaSiWaH3ContinuitySegmentDecode'], 14.0)
        self.assertEqual(timing['by_class']['MiniMaxH3DirectorGuide'], 5.0)
        self.assertEqual(timing['before_first_step'], 25.0)       # 모델 올리기 + 첫 스텝
        self.assertEqual(timing['step_seconds'], [20.0, 21.0])
        self.assertEqual(timing['step_median'], 21.0)
        self.assertEqual(timing['cached_nodes'], 2)
        self.assertEqual(end, 189.0)
        self.assertEqual(len(mine), 11)                            # 다른 작업의 이벤트는 섞지 않는다

    def test_an_unfinished_job_reports_no_total(self):
        timing, end, _ = B.timings([event(10.0, 'execution_start'), event(10.0, 'executing', node='1')], self.GRAPH, 'job', submitted=9.0)
        self.assertIsNone(timing['total'])
        self.assertIsNone(end)
        self.assertIsNone(timing['step_median'])


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.instance = B.Instance(Path(self.temp.name) / 'comfy', Path(self.temp.name) / 'bench', 8198)
        self.helpers = B.server_helpers()

    def build(self, **variant):
        with patch.object(B, 'pick_option', side_effect=lambda url, node, field, wanted: f'listed/{wanted}'), \
             patch.object(B, 'upload_image', side_effect=lambda url, path: Path(path).name):
            return B.build_graph(self.instance, {'name': 'case', **variant}, self.helpers)

    def test_text_only_graph_follows_the_server_fill(self):
        graph, shape = self.build(mode='T2VA', aspect='4:5', duration=5, steps=6, sampler='lcm', shift_video=7, shift_audio=4,
                                  model='turbo.safetensors', loras=[{'name': 'style.safetensors', 'strength': 0.5}], seed=77)
        self.assertEqual((shape['width'], shape['height']), (768, 960))
        director = graph[B.DIRECTOR]['inputs']
        timeline = json.loads(director['timeline_data'])
        builder = json.loads(director['builder_state'])
        text = director['prompt']
        self.assertTrue(text.startswith('integrated_multimodal_description:'))
        # 화면 서버가 채우는 프롬프트 사본 네 곳이 모두 같은 글이어야 Director 가 엇갈린 문구를 쓰지 않는다
        self.assertEqual({timeline['builder_state']['simple_prompt'], timeline['resolved_prompt'],
                          timeline['continuity']['continuation_prompt'], builder['simple_prompt']}, {text})
        self.assertEqual(timeline['items'], [])
        self.assertEqual(graph[B.SCHED]['inputs']['model'], [B.SHIFT, 0])
        self.assertEqual((graph[B.SCHED]['inputs']['steps'], graph[B.SAMPLER]['inputs']['sampler_name']), (6, 'lcm'))
        self.assertEqual({graph[k]['inputs']['unet_name'] for k in B.LOADERS}, {'listed/turbo.safetensors'})
        rows = json.loads(graph[B.LORA]['inputs']['stack_data'])
        self.assertEqual(len(rows), B.LORA_SLOTS)
        self.assertEqual((rows[0]['lora'], rows[0]['str'], rows[1]['lora']), ('listed/style.safetensors', 0.5, 'None'))
        self.assertEqual(graph[B.SEED]['inputs']['seed_value'], 77)
        self.assertEqual(graph[B.SAVE]['inputs']['filename_prefix'], 'bench/case')

    def test_reference_photo_becomes_a_timeline_item_and_sets_the_canvas(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest('Pillow 없음')
        folder = self.instance.folders()['input']
        folder.mkdir(parents=True)
        Image.new('RGB', (900, 1600), (120, 90, 60)).save(folder / 'synthetic.png')
        graph, shape = self.build(mode='REF2VA', image='synthetic.png', aspect='auto', resolution='draft')
        timeline = json.loads(graph[B.DIRECTOR]['inputs']['timeline_data'])
        item = timeline['items'][0]
        self.assertEqual((item['value'], item['slot'], item['source_width'], item['source_height']), ('synthetic.png', 0, 900, 1600))
        self.assertEqual(timeline['resolution']['input_scaling'], 'Auto')
        self.assertEqual((shape['width'], shape['height']), self.helpers['canvas']('auto', 'draft', (900, 1600)))
        self.assertIn('<Picture 1>', graph[B.DIRECTOR]['inputs']['prompt'])

    def test_overrides_and_extra_nodes_are_applied_last(self):
        graph, _ = self.build(mode='T2VA', overrides={B.SAVE: {'quality': 18}, '1512:2592': {'model': ['9101', 0]}},
                              nodes={'9101': {'class_type': 'MiniMaxH3Cache', 'inputs': {'model': [B.SHIFT, 0]}}})
        self.assertEqual(graph[B.SAVE]['inputs']['quality'], 18)
        self.assertEqual(graph['1512:2592']['inputs']['model'], ['9101', 0])
        self.assertEqual(graph['9101']['class_type'], 'MiniMaxH3Cache')

    def test_canvas_helper_is_the_servers_own(self):
        tree = ast.parse((ROOT / 'simple_ui/server.py').read_text(encoding='utf-8'))
        self.assertIn('canvas', {n.name for n in tree.body if isinstance(n, ast.FunctionDef)})
        self.assertEqual(self.helpers['canvas']('9:16', '720p', None), self.helpers['canvas']('9:16', '720p', (10, 10)))
        self.assertEqual(self.helpers['canvas']('4:5', 'auto', None), (768, 960))


class SafetyTests(unittest.TestCase):
    def test_outputs_are_only_looked_up_inside_the_bench_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            instance = B.Instance(Path(folder) / 'comfy', Path(folder) / 'bench', 8198)
            target = instance.folders()['output'] / 'bench'
            target.mkdir(parents=True)
            (target / 'clip_00001.mp4').write_bytes(b'synthetic')
            history = {'outputs': {'2568': {'gifs': [{'filename': 'clip_00001.mp4', 'subfolder': 'bench', 'type': 'output'}],
                                            'images': [{'filename': 'missing.png', 'subfolder': '', 'type': 'temp'}]}}}
            self.assertEqual(B.find_outputs(instance, history), [target / 'clip_00001.mp4'])

    def test_stop_never_touches_a_process_it_did_not_start(self):
        with tempfile.TemporaryDirectory() as folder:
            instance = B.Instance(Path(folder) / 'comfy', Path(folder) / 'bench', 8198)
            instance.root.mkdir(parents=True)
            self.assertFalse(instance.stop())                                 # 기록이 없으면 아무것도 하지 않는다
            try:
                import psutil
            except ImportError:
                self.skipTest('psutil 없음')
            import os
            instance.state.write_text(json.dumps({'pid': os.getpid(), 'flags': []}), encoding='utf-8')
            self.assertFalse(instance.stop())                                 # 명령줄이 측정 인스턴스가 아니면 끝내지 않는다
            self.assertTrue(psutil.pid_exists(os.getpid()))

    def test_every_scene_is_synthetic_and_follows_the_page_layout(self):
        for name in B.SCENES:
            reference = B.scene_prompt(name, 'REF2VA')
            self.assertEqual([line.split(':')[0] for line in reference.split('\n\n')],
                             ['subject_definitions', 'summary', 'retention_analysis', 'detailed_description', 'overall_soundscape', 'non_diegetic_music'])
            self.assertTrue(B.scene_prompt(name, 'I2VA').startswith('For the target video, at 0.00 seconds'))


if __name__ == '__main__':
    unittest.main()
