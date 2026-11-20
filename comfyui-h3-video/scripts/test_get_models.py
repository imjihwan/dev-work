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


if __name__=='__main__':unittest.main()
