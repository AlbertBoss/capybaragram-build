# SPDX-License-Identifier: MIT
from pathlib import Path
import importlib.util, tempfile, unittest, shutil, os
from unittest.mock import patch
ci=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('prep',ci/'prepare_android_baseline.py');prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)
evidence=Path(os.environ.get('CAPY_ANDROID_SOURCE','android')).resolve()
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
  for p in prep.PATHS:
   dst=self.root/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(evidence/p,dst)
  self.initial={p:(self.root/p).read_bytes() for p in prep.PATHS}
 def tearDown(self):self.tmp.cleanup()
 def runprep(self,check=False):
  # This fixture tests actual upstream-file transformations, not a full Git checkout or compilation.
  with patch.object(prep,'verify_git'):prep.prepare(self.root,check)
 def test_check_no_writes(self):
  self.runprep(True)
  self.assertFalse((self.root/prep.BACKUP).exists());self.assertEqual(self.initial,{p:(self.root/p).read_bytes() for p in prep.PATHS})
 def test_apply_and_original_backup(self):
  self.runprep()
  for p,b in self.initial.items():self.assertEqual((self.root/prep.BACKUP/p).read_bytes(),b)
  text=(self.root/'TMessagesProj_App/build.gradle').read_text()
  original=self.initial['TMessagesProj_App/build.gradle'].decode()
  self.assertIn('capybara-debug.keystore',text)
  # The release signing block must be byte-for-byte identical after newline normalization.
  import re
  pattern=r'(?ms)        release \{\n.*?^        \}'
  self.assertEqual(re.search(pattern,original).group(),re.search(pattern,text).group())
  for p in prep.PATHS:
   if p.endswith('.xml'):
    root=prep.ET.parse(self.root/p).getroot();app=root.find('application')
    self.assertEqual(app.get('{'+prep.ANDROID+'}label'),'CapybaraGram Build Test')
    self.assertFalse(any(e.get('{'+prep.ANDROID+'}name')=='com.google.android.maps.v2.API_KEY' for e in app.findall('meta-data')))
    perms=[e for e in root.findall('uses-permission') if e.get('{'+prep.ANDROID+'}name')=='android.permission.INTERNET']
    self.assertEqual(len(perms),1);self.assertEqual(perms[0].get('{'+prep.TOOLS+'}node'),'remove')
  vars=(self.root/prep.PATHS[3]).read_text();self.assertIn('APP_ID = 0;',vars);self.assertIn('APP_HASH = "";',vars)
 def test_changed_last_file_refuses_before_writes(self):
  p=self.root/prep.PATHS[-1];p.write_bytes(p.read_bytes()+b'\n<!-- drift -->')
  with self.assertRaises(ValueError):self.runprep()
  self.assertFalse((self.root/prep.BACKUP).exists())
  self.assertEqual((self.root/prep.PATHS[0]).read_bytes(),self.initial[prep.PATHS[0]])
 def test_repeat_refuses(self):
  self.runprep()
  with self.assertRaises(ValueError):self.runprep()
 def test_missing_file_refuses(self):
  (self.root/prep.PATHS[-1]).unlink()
  with self.assertRaises(FileNotFoundError):self.runprep()
  self.assertFalse((self.root/prep.BACKUP).exists())
 def test_duplicate_anchor_refuses(self):
  text=self.initial[prep.PATHS[3]].decode()+'\npublic static int APP_ID = 0;\n'
  with self.assertRaises(ValueError):prep.transform_vars(text)
 def test_path_escape_refuses(self):
  with self.assertRaises(ValueError):prep.safe_path(self.root,'../outside')
 def test_wrong_git_revision_refuses(self):
  import subprocess
  values=[subprocess.CompletedProcess([],0,str(self.root)+'\n',''),subprocess.CompletedProcess([],0,'0'*40+'\n','')]
  with patch.object(prep.subprocess,'run',side_effect=values):
   with self.assertRaises(ValueError):prep.verify_git(self.root)
 def test_backup_failure_leaves_sources_unchanged(self):
  original_write=Path.write_bytes
  def fail(p,b):
   if prep.BACKUP in p.parts and p.name=='build.gradle':raise OSError('synthetic backup failure')
   return original_write(p,b)
  with patch.object(Path,'write_bytes',fail):
   with self.assertRaises(OSError):self.runprep()
  self.assertEqual(self.initial,{p:(self.root/p).read_bytes() for p in prep.PATHS})
if __name__=='__main__':unittest.main(verbosity=2)
