# SPDX-License-Identifier: MIT
"""Source-contract tests; the native build and runtime are separate checks."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import prepare_windows_online as prep

SOURCE = Path(sys.argv.pop(1))

class WindowsIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = {name: (SOURCE/name).read_bytes().replace(b'\r\n', b'\n') for name in prep.FILES}
        hashes = json.loads(Path(prep.__file__).with_name('windows-input-hashes.json').read_text())
        for name, data in cls.original.items():
            if hashlib.sha256(data).hexdigest() != hashes[name]:
                raise ValueError('Test inputs differ from pinned source.')
        cls.result = {name: prep.transform(name, raw.decode()) for name, raw in cls.original.items()}

    def test_default_windows_profile_does_not_use_executable_directory(self):
        text = self.result[prep.PREFIX+'logs.cpp']
        windows = text.split('#ifdef Q_OS_WIN\n\t\tconst auto path', 1)[1].split('#elif', 1)[0]
        self.assertIn('psAppDataPath()', windows)
        self.assertIn('if (path.isEmpty())', windows)
        self.assertIn('return;', windows)
        self.assertNotIn('cExeDir()', windows)

    def test_no_automatic_legacy_migration(self):
        launcher = self.result[prep.PREFIX+'core/launcher.cpp']
        self.assertNotIn('MoveLegacyAlphaFolder', launcher)
        self.assertNotIn('TelegramAlpha_data', launcher)
        self.assertNotIn('TelegramBeta_data', launcher)
        self.assertIn('u"CapybaraGramForcePortable"_q', launcher)
        self.assertNotIn('MoveOldDataFiles(psAppDataPathOld())', self.result[prep.PREFIX+'logs.cpp'])

    def test_distinct_identifiers_and_windows_system_guids_preserved(self):
        values = [prep.identity(name) for name in ('ipc', 'application', 'toast-activator')]
        self.assertEqual(len(set(values)), 3)
        for name in ('config.h', 'core/version.h', 'platform/win/windows_toast_activator.h'):
            self.assertNotEqual(self.result[prep.PREFIX+name], self.original[prep.PREFIX+name].decode())
        name = prep.PREFIX+'platform/win/windows_app_user_model_id.cpp'
        before = [line for line in self.original[name].decode().splitlines() if line.startswith('const PROPERTYKEY ') and ' = ' in line]
        after = [line for line in self.result[name].splitlines() if line.startswith('const PROPERTYKEY ') and ' = ' in line]
        self.assertEqual(len(before), 3)
        self.assertEqual(before, after)

    def test_shortcuts_cannot_target_official_names(self):
        for short in ('platform/win/specific_win.cpp', 'platform/win/windows_app_user_model_id.cpp'):
            text = self.result[prep.PREFIX+short]
            self.assertNotIn('Telegram.lnk', text)
            self.assertNotIn('TelegramAlpha.lnk', text)
        version = self.result[prep.PREFIX+'core/version.h']
        self.assertIn('AppName = "CapybaraGram Preview"_cs', version)
        self.assertIn('AppFile = "CapybaraGram"_cs', version)

    def test_url_associations_remain_explicit(self):
        text = self.result[prep.PREFIX+'core/application.cpp']
        self.assertNotIn('\t\tautoRegisterUrlScheme();', text)
        self.assertIn('void Application::RegisterUrlScheme()', text)
        self.assertIn('.protocol = u"tg"_q', text)
        self.assertEqual(text.count('.shortAppName = u"capybaragram-preview"_q'), 2)

    def test_license_headers_preserved(self):
        for name, raw in self.original.items():
            self.assertEqual(raw.decode().split('*/', 1)[0], self.result[name].split('*/', 1)[0])

    def checkout(self, root):
        for name, raw in self.original.items():
            path = root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw.replace(b'\n', b'\r\n'))

    def git(self, root, *args):
        if args == ('rev-parse', 'HEAD'):
            return prep.SOURCE_SHA.encode()+b'\n'
        if args[0] == 'show':
            return self.original[args[1].removeprefix('HEAD:')]
        if args[0] == 'status':
            return b''.join(b' M '+name.encode()+b'\0' for name, raw in self.original.items()
                            if (root/name).read_bytes().replace(b'\r\n', b'\n') != raw)
        raise ValueError('Unexpected git call in test.')

    def test_apply_then_verify_and_refuse_second_apply(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.checkout(root)
            with patch.object(prep, 'git', self.git):
                self.assertEqual(prep.prepare(root), 8)
                self.assertEqual(prep.prepare(root, check=True), 8)
                with self.assertRaises(ValueError):
                    prep.prepare(root)

    def test_dirty_input_refused_before_any_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.checkout(root)
            damaged = root/prep.FILES[-1]
            damaged.write_bytes(damaged.read_bytes()+b'\n// altered\n')
            before = {name: (root/name).read_bytes() for name in prep.FILES}
            with patch.object(prep, 'git', self.git), self.assertRaises(ValueError):
                prep.prepare(root)
            self.assertEqual(before, {name: (root/name).read_bytes() for name in prep.FILES})

    def test_wrong_revision_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(prep, 'git', return_value=b'0'*40), self.assertRaises(ValueError):
                prep.prepare(Path(folder))

    def test_modified_prepared_file_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.checkout(root)
            with patch.object(prep, 'git', self.git):
                prep.prepare(root)
                path = root/prep.PREFIX/'core/version.h'
                path.write_bytes(self.original[prep.PREFIX+'core/version.h'])
                with self.assertRaises(ValueError):
                    prep.prepare(root, check=True)

if __name__ == '__main__':
    unittest.main()
