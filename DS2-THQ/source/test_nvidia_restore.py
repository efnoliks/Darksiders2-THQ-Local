"""NVIDIA backup/restore control-flow tests with mocked DRS calls.
No driver settings are written. Requires nvapi64.dll to import the helper.
"""
import argparse
import contextlib
import ctypes
import importlib.util
import io
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

class RestoreTests(unittest.TestCase):
    def setUp(self):
        path=pathlib.Path(__file__).resolve().parent.parent/'nvidia_ds2.py'
        spec=importlib.util.spec_from_file_location('nvidia_restore_test_subject',path)
        self.m=importlib.util.module_from_spec(spec)
        try: spec.loader.exec_module(self.m)
        except OSError as exc: self.skipTest('NVIDIA library unavailable: '+str(exc))
        self.tmp=tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).parent)
        self.m.ROOT=pathlib.Path(self.tmp.name)
        self.game=self.m.ROOT/'Darksiders2.exe';self.game.write_bytes(b'test fixture only')
        self.state=dict(status=0,id='0x10835002',name='FPS',value=0,location=3,predefined=1)
        self.m.initialize=lambda:0;self.m.destroy=lambda *a:0
        self.m.load=lambda *a:0;self.m.save=lambda *a:0
        def create(p):ctypes.cast(p,ctypes.POINTER(self.m.H)).contents.value=1;return 0
        self.m.create=create
        def find(s,path,p,app):ctypes.cast(p,ctypes.POINTER(self.m.H)).contents.value=2;return 0
        self.m.find=find
        def info(s,p,out):v=ctypes.cast(out,ctypes.POINTER(self.m.Profile)).contents;v.name='Darksiders 2';v.apps=1;return 0
        self.m.info=info
        def enum(s,p,start,count,out):ctypes.cast(out,ctypes.POINTER(self.m.App)).contents.name='darksiders2.exe';return 0
        self.m.enumapps=enum
        self.m.setting=lambda *a:(dict(self.state),None)
        def setvalue(s,p,out):v=ctypes.cast(out,ctypes.POINTER(self.m.Setting)).contents;self.state.update(value=int(v.current.dword),location=0,predefined=0);return 0
        self.m.setvalue=setvalue
        def delete(*args):self.state.update(value=0,location=3,predefined=1);return 0
        self.m.delete=delete
    def tearDown(self):
        if hasattr(self,'tmp'):
            self.assertEqual(pathlib.Path(self.tmp.name).resolve().parent,pathlib.Path(__file__).resolve().parent)
            self.tmp.cleanup()
    def run_action(self,action):
        with patch.object(sys,'argv',['nvidia_ds2.py',action,'--game',str(self.game)]),contextlib.redirect_stdout(io.StringIO()):self.m.main()
    def test_apply_restore_apply_archives_backup_and_preserves_inheritance(self):
        self.run_action('apply');self.assertEqual(self.state['value'],60)
        self.run_action('restore');self.assertEqual(self.state['location'],3)
        self.assertFalse((self.m.ROOT/'nvidia-ds2-before.json').exists())
        self.assertEqual(len(list(self.m.ROOT.glob('nvidia-ds2-restored-*.json'))),1)
        self.run_action('apply');self.assertEqual(self.state['value'],60)
    def test_changed_setting_is_not_overwritten(self):
        self.run_action('apply');self.state['value']=30
        with self.assertRaises(RuntimeError):self.run_action('restore')
        self.assertEqual(self.state['value'],30)
        self.assertTrue((self.m.ROOT/'nvidia-ds2-before.json').exists())

if __name__=='__main__':unittest.main()
