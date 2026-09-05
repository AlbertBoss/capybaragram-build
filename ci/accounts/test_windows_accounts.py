# SPDX-License-Identifier: MIT
"""Pinned-source and patch-integrity checks; actual Desktop build/runtime separate."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import windows_accounts_patch as prep

SOURCE = Path(sys.argv.pop(1))

class DesktopAccountsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = {}
        for group in prep.hashes().values():
            for name, expected in group.items():
                raw = (SOURCE / name).read_bytes().replace(b'\r\n', b'\n')
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise ValueError('Pinned Desktop audit source differs.')
                cls.original[name] = raw
        cls.planned = prep.plan(SOURCE)

    def fixture(self, root):
        for name in prep.FILES:
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.original[name])

    def test_one_limit_without_changing_premium_session(self):
        header = self.planned[prep.FILES[0]].decode()
        domain = self.planned[prep.FILES[1]].decode()
        self.assertIn('kMaxAccounts = 10;', header)
        self.assertIn('kPremiumMaxAccounts = kMaxAccounts;', header)
        self.assertIn('int Domain::maxAccounts() const {\n\treturn kMaxAccounts;\n}', domain)
        self.assertEqual(set(self.planned), set(prep.FILES))
        self.assertNotIn(prep.PREFIX + 'main/main_session.cpp', self.planned)

    def test_storage_guards_and_dynamic_slot_allocation_preserved(self):
        storage = self.original[prep.PREFIX + 'storage/storage_domain.cpp'].decode()
        self.assertIn('count > Main::Domain::kPremiumMaxAccounts', storage)
        self.assertIn('index < Main::Domain::kPremiumMaxAccounts', storage)
        self.assertIn('tried.emplace(index).second', storage)
        for anchor in ['Expects(_accounts.size() < kPremiumMaxAccounts);',
                       'while (ranges::contains(_accounts, index, &AccountWithIndex::index))']:
            self.assertIn(anchor, self.planned[prep.FILES[1]].decode())

    def test_limit_box_does_not_offer_premium_for_more_slots(self):
        text = self.planned[prep.FILES[3]].decode()
        box = text.split('void AccountsLimitBox(', 1)[1].split('QString LimitsPremiumRef', 1)[0]
        self.assertIn('tr::lng_accounts_limit1(', box)
        self.assertIn('box->closeBox()', box)
        for forbidden in ['lng_accounts_limit2', 'ShowPremium', 'promotePossible', 'premiumPossible']:
            self.assertNotIn(forbidden, box)

    def test_unrelated_premium_features_and_boxes_preserved(self):
        name = prep.FILES[2]
        before, after = self.original[name].decode(), self.planned[name].decode()
        begin = '\tconst auto nextMax = session->domain().maxAccounts() + 1;\n'
        end = '\t{\n\t\tconst auto premium = limits.similarChannelsPremium();'
        self.assertTrue(after.startswith(before[:before.index(begin)]))
        self.assertTrue(after.endswith(before[before.index(end):]))
        self.assertNotIn('lng_premium_double_limits_subtitle_accounts', after)
        name = prep.FILES[3]
        before, after = self.original[name].decode(), self.planned[name].decode()
        self.assertTrue(after.startswith(before[:before.index('void AccountsLimitBox(')]))
        self.assertTrue(after.endswith(before[before.index('QString LimitsPremiumRef'):]))

    def test_plan_does_not_write_and_damaged_last_input_prevents_any_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            self.assertEqual(prep.plan(root), self.planned)
            before = {name: (root / name).read_bytes() for name in prep.FILES}
            self.assertEqual(before, {name: self.original[name] for name in prep.FILES})
            last = root / prep.FILES[-1]
            last.write_bytes(last.read_bytes() + b'// unexpected\n')
            snapshot = {name: (root / name).read_bytes() for name in prep.FILES}
            with patch.object(prep, 'git', return_value=prep.SOURCE_SHA.encode()):
                with self.assertRaises(ValueError):
                    prep.prepare(root)
            self.assertEqual(snapshot, {name: (root / name).read_bytes() for name in prep.FILES})

    def test_apply_check_reapply_and_altered_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            # Fixture Git only supplies immutable source bytes and HEAD. Real Git
            # checkout verification happens in the full Desktop build workflow.
            def git(_root, *args):
                if args == ('rev-parse', 'HEAD'):
                    return prep.SOURCE_SHA.encode()
                if args[0] == 'show':
                    return self.original[args[1].removeprefix('HEAD:')]
                raise AssertionError(args)
            with patch.object(prep, 'git', side_effect=git):
                self.assertEqual(prep.prepare(root), 4)
                self.assertEqual(prep.prepare(root, check=True), 4)
                with self.assertRaises(ValueError):
                    prep.prepare(root)
                path = root / prep.FILES[0]
                path.write_bytes(path.read_bytes() + b'// later modification\n')
                with self.assertRaises(ValueError):
                    prep.prepare(root, check=True)

    def test_wrong_revision_prevents_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with patch.object(prep, 'git', return_value=b'wrong-commit'):
                with self.assertRaises(ValueError):
                    prep.prepare(root)
            self.assertEqual({name: (root / name).read_bytes() for name in prep.FILES},
                             {name: self.original[name] for name in prep.FILES})

if __name__ == '__main__':
    unittest.main()
