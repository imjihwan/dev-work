"""HTTP handler checks using synthetic controllers and in-memory streams only."""
import ast
from http.server import BaseHTTPRequestHandler
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.parse


ROOT=Path(__file__).resolve().parents[1]


class StoryRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.here=Path(self.temp.name)
        (self.here/'index.html').write_text('synthetic single tab',encoding='utf-8')
        (self.here/'story.html').write_text('synthetic story tab',encoding='utf-8')
        self.calls=[]
        owner=self
        class Controller:
            def __getattr__(self,name):
                def call(*args):
                    owner.calls.append((name,args))
                    return {'filename':'synthetic.mp4','subfolder':'synthetic','type':'output'} if name=='video' else {'ok':True}
                return call
        def comfy(path,data,headers):
            self.calls.append(('comfy',(path,headers)))
            response=io.BytesIO(b'synthetic-video-bytes')
            response.status=206;response.headers={'Content-Type':'video/mp4','Content-Length':'21','Content-Range':'bytes 0-20/21','Accept-Ranges':'bytes'}
            return response
        source=ast.parse((ROOT/'simple_ui/server.py').read_text(encoding='utf-8-sig'))
        handler=next(node for node in source.body if isinstance(node,ast.ClassDef) and node.name=='H')
        env={'BaseHTTPRequestHandler':BaseHTTPRequestHandler,'json':json,'os':os,'urllib':urllib,
            'HERE':str(self.here),'INDEX':str(self.here/'index.html'),'STORIES':Controller(),'comfy':comfy,
            'build_and_queue':lambda body:self.calls.append(('single',(body,))) or {'ok':True}}
        exec(compile(ast.Module(body=[handler],type_ignores=[]),'<synthetic-handler>','exec'),env)
        self.handler_class=env['H']

    def request(self,path,body=None,headers=None):
        handler=self.handler_class.__new__(self.handler_class)
        raw=json.dumps(body).encode() if body is not None else b''
        handler.path=path;handler.headers={'Content-Length':str(len(raw)),**(headers or {})}
        handler.rfile=io.BytesIO(raw);handler.wfile=io.BytesIO();handler.response_headers={}
        handler.send_response=lambda code:setattr(handler,'code',code)
        handler.send_header=lambda key,value:handler.response_headers.update({key:value})
        handler.end_headers=lambda:None
        handler.do_GET() if body is None else handler.do_POST()
        return handler

    def test_tabs_serve_separate_pages_without_requesting_jobs(self):
        single=self.request('/');story=self.request('/story')
        self.assertEqual(single.wfile.getvalue(),b'synthetic single tab')
        self.assertEqual(story.wfile.getvalue(),b'synthetic story tab')
        self.assertEqual(story.response_headers['Cache-Control'],'no-store')
        self.assertEqual(self.calls,[])

    def test_story_actions_dispatch_only_the_supplied_project_and_stage(self):
        body={'id':'a'*32,'index':2,'definition':{'synthetic':True}}
        for route,method,args in [('save','save',(body,)),('generate','start',(body['id'],2)),
            ('approve','approve',(body['id'],2)),('merge','start_merge',(body['id'],)),('cancel','cancel',(body['id'],))]:
            response=self.request('/api/story/'+route,body)
            self.assertEqual(response.code,200);self.assertEqual(self.calls[-1],(method,args))
        self.request('/api/story/project?id='+body['id'])
        self.assertEqual(self.calls[-1],('get',(body['id'],)))
        self.request('/api/generate',{'synthetic':'single-video'})
        self.assertEqual(self.calls[-1],('single',({'synthetic':'single-video'},)))

    def test_video_proxy_keeps_range_and_uses_generic_download_name(self):
        response=self.request('/api/story/video?id='+('a'*32)+'&clip=2&download=1',headers={'Range':'bytes=0-20'})
        self.assertEqual(self.calls[0],('video',('a'*32,'2')))
        self.assertEqual(self.calls[1][1][1],{'Range':'bytes=0-20'})
        self.assertEqual(response.code,206);self.assertEqual(response.wfile.getvalue(),b'synthetic-video-bytes')
        self.assertEqual(response.response_headers['Content-Disposition'],'attachment; filename=story-video.mp4')
        self.assertEqual(response.response_headers['Accept-Ranges'],'bytes')


if __name__=='__main__':unittest.main()
