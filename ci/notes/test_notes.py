# SPDX-License-Identifier: MIT
"""Check the composed account + notes source transformation, not client runtime."""
import hashlib
from pathlib import Path
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import prepare_android_notes as notes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'accounts'))
import android_accounts_patch as accounts

SOURCE = Path(sys.argv.pop(1))

class NotesIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.account_stage = accounts.plan(SOURCE)

    def fixture(self, root):
        for name in notes.FILES:
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            raw = self.account_stage.get(name, (SOURCE / name).read_bytes())
            dest.write_bytes(raw)

    def test_composition_and_repeat_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            planned = notes.plan(root)
            self.assertEqual(len(planned), 12)
            for name, raw in planned.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
            self.assertEqual(notes.plan(root, True), planned)
            with self.assertRaises(ValueError):
                notes.plan(root)

    def test_corrupted_input_is_not_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            target = root / notes.FILES[-1]
            target.write_bytes(target.read_bytes() + b'// unreviewed\n')
            before = {name: (root / name).read_bytes() for name in notes.FILES}
            with self.assertRaises(ValueError):
                notes.plan(root)
            self.assertEqual(before, {name: (root / name).read_bytes() for name in notes.FILES})
            self.assertTrue(all(not (root / name).exists() for name in notes.ADDED))

    def test_locale_keys_match_ui_and_do_not_package_test_harness(self):
        english = {node.attrib['name'] for node in ET.parse(notes.ROOT / 'strings.xml').getroot()}
        russian = {node.attrib['name'] for node in ET.parse(notes.ROOT / 'strings-ru.xml').getroot()}
        self.assertEqual(english, russian)
        references = set(re.findall(r'R\.string\.(Capy\w+)', (notes.ROOT / 'CapyNotesUi.java').read_text()))
        self.assertEqual(references, english)
        for path in notes.ADDED:
            self.assertNotRegex(path, r'Test|DeviceProbe|Instrumentation')

    def test_client_hooks_and_draft_only_insertion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = notes.plan(root)
            config = result[notes.FILES[0]].decode()
            logout = config.split('public void clearConfig() {', 1)[1]
            self.assertLess(logout.index('CapyVault.beforeLogout'), logout.index('getPreferences().edit().clear()'))
            self.assertIn('oldUser == null ? 0 : oldUser.id, user.id', config)
            self.assertIn('MAX_ACCOUNT_COUNT = 10;', config)
            launch = result[notes.FILES[1]].decode()
            self.assertIn('SharedConfig.appLocked = true;\n        org.capybaragram.telegram.CapyVault.locked();', launch)
            self.assertIn('NotificationAccountBinding', launch)
            chat = result[notes.FILES[2]].decode()
            method = chat.split('private void showCapyVault(boolean templates) {', 1)[1].split('@Override', 1)[0]
            self.assertIn('isLastFragment() && !paused', method)
            self.assertIn('getTopicId() == expectedTopic', method)
            self.assertIn('combined.append(old)', method)
            self.assertIn('chatActivityEnterView.setFieldText(combined)', method)
            self.assertNotIn('sendMessage', method)
            self.assertEqual(chat.count('CapyNotesUi.closeFor(this);'), 2)

if __name__ == '__main__':
    unittest.main()
