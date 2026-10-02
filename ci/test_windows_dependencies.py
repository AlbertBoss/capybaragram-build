# SPDX-License-Identifier: MIT
"""Check the dependency transformation against the actual pinned upstream recipe.

The temporary-checkout git responses are mocked; installing packages and compiling
the client are separate checks performed by the native Windows build.
"""
import ast
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import prepare_windows_dependencies as prep

SOURCE = Path(sys.argv.pop(1))


class WindowsDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (SOURCE / prep.SOURCE_FILE).read_bytes().replace(b'\r\n', b'\n')
        cls.expected = prep.transform(cls.original)

    def checkout(self, root, crlf=False):
        path = root / prep.SOURCE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.original.replace(b'\n', b'\r\n') if crlf else self.original)
        return path

    def git(self, root, *args):
        if args == ('rev-parse', 'HEAD'):
            return prep.SOURCE_SHA.encode('ascii') + b'\n'
        if args == ('show', 'HEAD:' + prep.SOURCE_FILE):
            return self.original
        raise ValueError('Unexpected git call in test.')

    def test_exact_package_substitution_and_explicit_probe(self):
        # Restoring the two declared edits must restore the entire original recipe.
        restored = self.expected.replace(prep.NEW, prep.OLD).replace(prep.PROBE, b'')
        self.assertEqual(restored, self.original)
        self.assertNotIn(b'mingw-w64-x86_64-diffutils', self.expected)
        self.assertEqual(self.expected.count(prep.PROBE), 1)
        tree = ast.parse(self.expected.decode('utf-8'))
        stages = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == 'stage'
                  and node.args and isinstance(node.args[0], ast.Constant)
                  and node.args[0].value == 'msys64']
        self.assertEqual(len(stages), 1)
        commands = ast.literal_eval(stages[0].args[1])
        self.assertIn(r'"%THIRDPARTY_DIR%\msys64\usr\bin\diff.exe" --version', commands)
        self.assertIn('pacman -Syu --noconfirm', commands)

    def test_apply_verify_and_second_apply_refused_for_both_line_endings(self):
        for crlf in (False, True):
            with self.subTest(crlf=crlf), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                path = self.checkout(root, crlf)
                with patch.object(prep, 'git', self.git):
                    digest = prep.prepare(root)
                    self.assertEqual(prep.prepare(root, check=True), digest)
                    expected = self.expected.replace(b'\n', b'\r\n') if crlf else self.expected
                    self.assertEqual(path.read_bytes(), expected)
                    with self.assertRaises(ValueError):
                        prep.prepare(root)
                    self.assertEqual(path.read_bytes(), expected)

    def test_modified_original_is_refused_without_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.checkout(root)
            damaged = self.original + b'\n# unrelated modification\n'
            path.write_bytes(damaged)
            with patch.object(prep, 'git', self.git), self.assertRaises(ValueError):
                prep.prepare(root)
            self.assertEqual(path.read_bytes(), damaged)

    def test_wrong_revision_is_refused_without_write(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.checkout(root)
            with patch.object(prep, 'git', return_value=b'0' * 40), self.assertRaises(ValueError):
                prep.prepare(root)
            self.assertEqual(path.read_bytes(), self.original)

    def test_tampered_prepared_recipe_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = self.checkout(root)
            with patch.object(prep, 'git', self.git):
                prep.prepare(root)
                path.write_bytes(self.expected.replace(b'pacman -Syu', b'pacman -Sy'))
                with self.assertRaises(ValueError):
                    prep.prepare(root, check=True)

    def test_different_upstream_recipe_is_refused(self):
        with self.assertRaises(ValueError):
            prep.transform(self.original + b'\n')


if __name__ == '__main__':
    unittest.main()
