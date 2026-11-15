"""Thumbnail size/orientation/cache checks using generated pixels only."""
import ast
from functools import lru_cache
import io
import os
from pathlib import Path
import unittest
import urllib.parse
from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(os.environ.get('REFERENCE_TEST_SOURCE',ROOT/'simple_ui'))
TREE=ast.parse((SOURCE/'server.py').read_text(encoding='utf-8'))
FUNCTION=next(node for node in TREE.body if isinstance(node,ast.FunctionDef) and node.name=='input_thumbnail')


class ThumbnailTests(unittest.TestCase):
    def setUp(self):
        output=io.BytesIO()
        with Image.new('RGB',(800,400),'blue') as image:
            exif=Image.Exif();exif[274]=6
            image.save(output,format='JPEG',exif=exif)
        self.original=output.getvalue();self.calls=[]
        def fake_comfy(path):
            self.calls.append(path)
            return io.BytesIO(self.original)
        self.env={'lru_cache':lru_cache,'io':io,'urllib':urllib,'Image':Image,'ImageOps':ImageOps,'comfy':fake_comfy}
        exec(compile(ast.Module(body=[FUNCTION],type_ignores=[]),'thumbnail','exec'),self.env)

    def test_small_webp_preserves_portrait_orientation(self):
        data=self.env['input_thumbnail']('simpleui_1234567890.jpg')
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.format,'WEBP')
            self.assertEqual(image.size,(96,192))
        self.assertLess(len(data),len(self.original))
        with Image.open(io.BytesIO(self.original)) as original:
            self.assertEqual(original.size,(800,400))

    def test_repeated_thumbnail_does_not_read_input_again(self):
        thumb=self.env['input_thumbnail']
        first=thumb('simpleui_1234567890.jpg')
        self.assertEqual(thumb('simpleui_1234567890.jpg'),first)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(thumb.cache_info().maxsize,256)

    def test_gallery_size_is_cached_separately_and_preserves_orientation(self):
        thumb=self.env['input_thumbnail']
        small=thumb('simpleui_1234567890.jpg')
        large=thumb('simpleui_1234567890.jpg',480)
        self.assertNotEqual(small,large)
        with Image.open(io.BytesIO(large)) as image:
            self.assertEqual(image.size,(240,480))
        self.assertEqual(thumb('simpleui_1234567890.jpg',480),large)
        self.assertEqual(len(self.calls),2)


if __name__=='__main__':unittest.main()
