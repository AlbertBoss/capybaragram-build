# SPDX-License-Identifier: MIT
"""Source preparation safety tests. These do not claim native Telegram UI coverage."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest

HERE = Path(__file__).resolve().parent
SOURCE = Path(sys.argv[1]).resolve(strict=True)
sys.argv = [sys.argv[0]]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name,path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


patch = module('capy_notes',HERE/'windows_notes_patch.py')
ci = HERE.parent
if not (ci/'prepare_windows_online.py').exists():
    ci = Path('outputs/capybaragram-build/ci').resolve(strict=True)
identity = module('capy_identity',ci/'prepare_windows_online.py')
accounts = module('capy_accounts',ci/'accounts/windows_accounts_patch.py')


class Preparation(unittest.TestCase):
    def setUp(self):
        self.scratch = (Path.cwd()/'work'/'windows-notes-contracts').resolve()
        self.scratch.mkdir(parents=True,exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='fixture-',dir=self.scratch)
        self.root = Path(self.temp.name).resolve(strict=True)
        self.assertTrue(self.root.is_relative_to(self.scratch))
        self.addCleanup(self.cleanup)
        self.before = {}
        for name in patch.FILES:
            text = (SOURCE/name).read_text(encoding='utf-8')
            if name in identity.FILES: text = identity.transform(name,text)
            if name in accounts.FILES: text = accounts.transform(name,text)
            raw = text.encode('utf-8')
            self.assertEqual(hashlib.sha256(raw).hexdigest(),patch.read_manifest()['patch'][name]['before'])
            path = self.root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(raw)
            self.before[name] = raw

    def cleanup(self):
        self.assertTrue(self.root.resolve().is_relative_to(self.scratch))
        self.temp.cleanup()

    def test_full_composition_and_check(self):
        self.assertEqual(patch.apply(self.root),21)
        self.assertEqual(patch.plan(self.root,check=True),{})
        for name,raw in patch.payloads().items():
            self.assertEqual(patch.normalized(self.root/name),raw)

    def test_every_changed_input_rejected_before_any_write(self):
        for name in patch.FILES:
            path = self.root/name
            path.write_bytes(self.before[name]+b'\n// unexpected drift\n')
            with self.assertRaises(ValueError): patch.apply(self.root)
            for other,raw in self.before.items():
                if other != name: self.assertEqual((self.root/other).read_bytes(),raw)
            self.assertFalse((self.root/patch.PREFIX/'capybara').exists())
            path.write_bytes(self.before[name])

    def test_existing_added_source_is_never_overwritten(self):
        target = self.root/patch.PREFIX/'capybara/capy_notes_ui.cpp'
        target.parent.mkdir(parents=True)
        target.write_text('existing local work',encoding='utf-8')
        with self.assertRaises(ValueError): patch.apply(self.root)
        self.assertEqual(target.read_text(),'existing local work')
        for name,raw in self.before.items(): self.assertEqual((self.root/name).read_bytes(),raw)

    def test_post_check_rejects_modified_patch_and_payload(self):
        patch.apply(self.root)
        for name in [patch.FILES[-1],patch.PREFIX+'capybara/capy_notes_ui.cpp']:
            path = self.root/name
            raw = path.read_bytes()
            path.write_bytes(raw+b'\n// altered output\n')
            with self.assertRaises(ValueError): patch.plan(self.root,check=True)
            path.write_bytes(raw)
        self.assertEqual(patch.plan(self.root,check=True),{})


unittest.main()
