"""Synthetic native queue and count-only proxy tests; no running server/media."""
import ast
import copy
import heapq
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pause_control',ROOT/'extensions/h3-video-queue-pause/control.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class Queue:
    def __init__(self):
        self.not_empty=threading.Condition(threading.RLock());self.queue=[];self.currently_running={};self.counter=0
    def get(self,timeout=None):
        with self.not_empty:
            if not self.queue:return None
            item=heapq.heappop(self.queue);index=self.counter;self.counter+=1;self.currently_running[index]=item
            return item,index
    def put(self,item):
        with self.not_empty:heapq.heappush(self.queue,item);self.not_empty.notify_all()


class QueuePauseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'pause-state.json';self.queue=Queue();self.gate=module.QueuePauseGate(self.queue,self.path).install()

    def test_pause_keeps_current_and_pending_objects_and_order(self):
        self.queue.put((3,'third'));self.queue.put((1,'first'));self.queue.put((2,'second'))
        running=self.queue.get();self.gate.set_paused(True)
        self.assertEqual(self.gate.snapshot()['state'],'finishing')
        self.assertIs(self.queue.currently_running[0],running[0])
        self.assertIsNone(self.queue.get(timeout=.01));self.assertEqual(len(self.queue.queue),2)
        self.queue.currently_running.clear();self.assertEqual(self.gate.snapshot()['state'],'paused')
        self.gate.set_paused(False)
        self.assertEqual([self.queue.get()[0][1],self.queue.get()[0][1]],['second','third'])

    def test_pause_also_blocks_a_worker_already_waiting_on_an_empty_queue(self):
        done=threading.Event();result=[]
        thread=threading.Thread(target=lambda:(result.append(self.queue.get(timeout=1)),done.set()),daemon=True);thread.start()
        self.gate.set_paused(True);self.queue.put((1,'synthetic'))
        self.assertFalse(done.wait(.03));self.assertEqual(self.queue.counter,0)
        self.gate.set_paused(False);self.assertTrue(done.wait(.5));thread.join(.5)
        self.assertEqual(result[0][0],(1,'synthetic'));self.assertEqual(self.queue.counter,1)

    def test_state_survives_reload_and_invalid_state_holds_queue(self):
        self.gate.set_paused(True);other=module.QueuePauseGate(Queue(),self.path)
        self.assertTrue(other.snapshot()['paused']);self.assertNotIn('synthetic',json.dumps(other.snapshot()))
        self.path.write_text('invalid',encoding='utf-8');other=module.QueuePauseGate(Queue(),self.path)
        self.assertTrue(other.snapshot()['paused']);self.assertTrue(other.snapshot()['storage_error'])
        other.set_paused(False);self.assertFalse(other.snapshot()['storage_error'])

    def test_bad_request_and_failed_storage_do_not_change_pause_state(self):
        with self.assertRaises(ValueError):self.gate.set_paused('true')
        self.gate.path=Path(self.tmp.name)/'missing'/'state.json'
        with self.assertRaises(OSError):self.gate.set_paused(True)
        self.assertFalse(self.gate.snapshot()['paused'])

    def test_proxy_only_sends_boolean_and_returns_counts(self):
        tree=ast.parse((ROOT/'simple_ui/server.py').read_text(encoding='utf-8'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='queue_pause')
        calls=[]
        def request(path,data=None,headers=None,timeout=None):
            calls.append((path,json.loads(data) if data else None))
            return io.BytesIO(json.dumps(dict(supported=True,paused=True,state='paused',running=0,pending=3,prompt='PRIVATE',filename='PRIVATE')).encode())
        env={'comfy':request,'json':json,'urllib':__import__('urllib')}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'queue_pause','exec'),env)
        value=env['queue_pause']({'paused':True});self.assertNotIn('PRIVATE',str(value));self.assertEqual(calls,[('/h3-video/queue-pause',{'paused':True})])
        for body in ({'paused':1},{'paused':True,'prompt':'PRIVATE'},[]):
            with self.assertRaises(ValueError):env['queue_pause'](body)
        def missing(*args,**kwargs):raise urllib.error.HTTPError('synthetic',404,'not found',{},None)
        env['comfy']=missing;self.assertEqual(env['queue_pause']()['state'],'unsupported')

    def test_installed_native_queue_class_keeps_ids_and_extra_data_on_resume(self):
        source=ROOT/'ComfyUI/execution.py'
        if not source.is_file():self.skipTest('Optional native source not installed')
        tree=ast.parse(source.read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PromptQueue')
        cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('__init__','put','get')]
        env=dict(threading=threading,heapq=heapq,copy=copy,time=time)
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'native_queue','exec'),env)
        class Server:
            def queue_updated(self):pass
        queue=env['PromptQueue'](Server());gate=module.QueuePauseGate(queue,self.path).install()
        first=[1,'first',{'synthetic':'graph'},{'seed':100},[]];second=[2,'second',{'synthetic':'graph'},{'seed':101},[]]
        queue.put(second);queue.put(first);gate.set_paused(True)
        self.assertIsNone(queue.get(timeout=.01));self.assertEqual(queue.task_counter,0)
        gate.set_paused(False)
        self.assertEqual(queue.get()[0],first);self.assertEqual(queue.get()[0],second)


if __name__=='__main__':unittest.main()
