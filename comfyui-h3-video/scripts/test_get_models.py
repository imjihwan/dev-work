"""Small synthetic downloads and hashes only; no network or real model access."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('get_models',ROOT/'scripts/get_models.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)


class Response(io.BytesIO):
    def __init__(self,data,status=200):super().__init__(data);self.status=status


class ModelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.target=Path(self.temp.name)/'synthetic.safetensors';self.raw=b'synthetic checkpoint bytes'
        self.spec=dict(repo='synthetic/repository',path='synthetic.safetensors',revision='pinned-revision',filename=self.target.name,size=len(self.raw),sha256=hashlib.sha256(self.raw).hexdigest())

    def test_pinned_download_is_verified_before_install(self):
        with patch.object(M.urllib.request,'urlopen',return_value=Response(self.raw)) as request:
            M.download_hf(self.spec,str(self.target))
        self.assertEqual(self.target.read_bytes(),self.raw)
        self.assertIn('/resolve/pinned-revision/',request.call_args.args[0].full_url)
        self.assertFalse(self.target.with_name(self.target.name+'.part').exists())

    def test_wrong_hash_never_replaces_an_existing_model(self):
        self.target.write_bytes(b'previous trusted model')
        with patch.object(M.urllib.request,'urlopen',return_value=Response(b'x'*len(self.raw))):
            with self.assertRaisesRegex(ValueError,'SHA256'):M.download_hf(self.spec,str(self.target))
        self.assertEqual(self.target.read_bytes(),b'previous trusted model')

    def test_complete_partial_file_can_be_verified_without_redownloading(self):
        self.target.with_name(self.target.name+'.part').write_bytes(self.raw)
        with patch.object(M.urllib.request,'urlopen',side_effect=AssertionError('No network required')):
            M.download_hf(self.spec,str(self.target))
        self.assertEqual(self.target.read_bytes(),self.raw)

    def test_range_resume_and_ignored_range_both_preserve_full_file_hash(self):
        partial=self.target.with_name(self.target.name+'.part')
        for status,data in [(206,self.raw[4:]),(200,self.raw)]:
            partial.write_bytes(self.raw[:4])
            with patch.object(M.urllib.request,'urlopen',return_value=Response(data,status)) as request:
                M.download_hf(self.spec,str(self.target))
            self.assertEqual(request.call_args.args[0].get_header('Range'),'bytes=4-')
            self.assertEqual(self.target.read_bytes(),self.raw)

    def test_mirror_cannot_override_canonical_size_or_hash(self):
        manifest=Path(self.temp.name)/'models.json'
        canonical=dict(self.spec,id='synthetic',role='Synthetic test model',dest='models',required=False,source='civitai',page='synthetic',url='synthetic',mirrors=[dict(source='hf',repo='mirror/repository',path='mirror.safetensors',revision='mirror-revision',size=1,sha256='untrusted')])
        manifest.write_text(json.dumps({'files':[canonical]}))
        with patch.object(M,'MANIFEST',str(manifest)),patch.object(M.sys,'argv',['get_models.py','--comfy',self.temp.name,'--downloads',str(Path(self.temp.name)/'downloads'),'--only','synthetic']),patch.object(M,'download_hf') as download:
            with self.assertRaises(SystemExit) as result:M.main()
        self.assertEqual(result.exception.code,0)
        actual=download.call_args.args[0]
        self.assertEqual(actual['size'],self.spec['size']);self.assertEqual(actual['sha256'],self.spec['sha256'])
        self.assertEqual(actual['revision'],'mirror-revision')

    def run_main(self,files,*arguments,stdout=None):
        manifest=Path(self.temp.name)/'models.json';manifest.write_text(json.dumps({'files':files},ensure_ascii=False),encoding='utf-8')
        argv=['get_models.py','--comfy',self.temp.name,'--downloads',str(Path(self.temp.name)/'downloads'),*arguments]
        with patch.object(M,'MANIFEST',str(manifest)),patch.object(M.sys,'argv',argv),patch.object(M,'download_hf',side_effect=AssertionError('No download expected')):
            with patch.object(M.sys,'stdout',stdout or io.StringIO()),self.assertRaises(SystemExit) as result:M.main()
        return result.exception.code

    def entry(self,identity,**changes):
        return {**self.spec,'id':identity,'role':'Synthetic test model','dest':'models','required':True,'source':'hf',**changes}

    def test_required_only_run_passes_while_optional_manual_files_are_missing(self):
        # Complete-Models.ps1 은 필수 파일만 확인한다. 직접 받아야 하는 선택 파일 때문에 실패로 끝나면 안 된다.
        (Path(self.temp.name)/'models').mkdir();(Path(self.temp.name)/'models'/self.spec['filename']).write_bytes(self.raw)
        optional=self.entry('optional-manual',required=False,source='civitai',filename='manual.safetensors',page='synthetic',url='synthetic')
        files=[self.entry('required'),optional]
        self.assertEqual(self.run_main(files),0)
        self.assertEqual(self.run_main(files,'--all'),1)

    def test_unknown_id_is_an_error_instead_of_checking_nothing(self):
        code=self.run_main([self.entry('real')],'--only','real','typo','--check')
        self.assertIsInstance(code,str);self.assertIn('typo',code)

    def test_destination_outside_the_comfy_folder_is_refused(self):
        for changes in ({'dest':'../outside'},{'filename':'../escape.safetensors'}):
            with self.subTest(changes=changes):
                code=self.run_main([self.entry('escaping',**changes)],'--check')
                self.assertIsInstance(code,str);self.assertIn('escaping',code)
        self.assertFalse((Path(self.temp.name).parent/'outside').exists())

    def test_install_at_a_drive_root_is_not_mistaken_for_an_escape(self):
        # D:\ 같은 드라이브 루트는 실제 경로가 이미 구분자로 끝난다. 구분자를 한 번 더 붙이면 모든 파일이 폴더 밖으로 보인다.
        root=str(Path(self.temp.name).resolve());real=M.os.path.realpath
        def at_root(path):
            tail=M.os.path.relpath(real(path),root)
            return 'Q:'+M.os.sep+('' if tail=='.' else tail)
        (Path(self.temp.name)/'models').mkdir();(Path(self.temp.name)/'models'/self.spec['filename']).write_bytes(self.raw)
        with patch.object(M.os.path,'realpath',at_root):
            self.assertEqual(self.run_main([self.entry('rooted')]),0)

    def test_listing_survives_an_output_encoding_that_cannot_show_the_names(self):
        # 출력을 파일·파이프로 돌린 한국어 Windows(cp949): 목록의 '—' 나 한자 파일 이름에서 멈추지 않는다
        captured=io.BytesIO();stream=io.TextIOWrapper(captured,encoding='cp949')
        files=[self.entry('named',role='기본값 — 电影感',filename='电影感lora.safetensors')]
        self.assertEqual(self.run_main(files,'--check','--fast',stdout=stream),1)
        stream.flush();self.assertIn(b'named',captured.getvalue())


if __name__=='__main__':unittest.main()
