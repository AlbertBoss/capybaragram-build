# SPDX-License-Identifier: MIT
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import android_accounts_patch as patch

SOURCE = Path(sys.argv.pop(1))

class AccountSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planned = patch.plan(SOURCE)

    def test_capacity_agrees_between_java_and_jni(self):
        java = self.planned[patch.CONFIG].decode()
        native = self.planned[patch.DEFINES].decode()
        values = [int(re.search(r'MAX_ACCOUNT_DEFAULT_COUNT = (\d+);', java)[1]),
                  int(re.search(r'MAX_ACCOUNT_COUNT = (\d+);', java)[1]),
                  int(re.search(r'#define MAX_ACCOUNT_COUNT (\d+)', native)[1])]
        self.assertEqual(values, [10, 10, 10])
        self.assertIn('return MAX_ACCOUNT_COUNT;', java)
        self.assertNotIn('return hasPremiumOnAccounts() ? 5 : 3;', java)

    def test_summary_and_children_use_same_notification_namespace(self):
        text = self.planned[patch.NOTIFICATIONS].decode()
        calls = [line.strip() for line in text.splitlines()
                 if 'notificationManager.notify(' in line or 'notificationManager.cancel(' in line]
        self.assertEqual(len(calls), 11)
        for line in calls:
            self.assertIn('("capybaragram.account." + currentAccount, ', line)
        # Services use a null tag, which differs even when the numeric ID is equal.
        for account in range(10):
            self.assertNotEqual(('capybaragram.account.'+str(account), account+1), (None, account+1))

    def test_account_addition_does_not_advertise_premium_capacity(self):
        text = self.planned[patch.INFO].decode()
        self.assertNotIn('new PremiumPreviewFragment("add_account")', text)
        self.assertIn('presentFragment(new LoginActivity(availableAccount));', text)

    def test_copyright_headers_preserved(self):
        for name, result in self.planned.items():
            if name == patch.BINDING:
                continue
            original = (SOURCE/name).read_text(encoding='utf-8')
            if original.startswith('/*'):
                self.assertEqual(original.split('*/', 1)[0], result.decode().split('*/', 1)[0])
            else:
                self.assertEqual(original.splitlines()[0], result.decode().splitlines()[0])

    def test_modified_source_refused_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in patch.FILES:
                target = root/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((SOURCE/name).read_bytes())
            target = root/patch.FILES[-1]
            target.write_bytes(target.read_bytes()+b'\n// changed\n')
            before = {name: (root/name).read_bytes() for name in patch.FILES}
            with self.assertRaises(ValueError):
                patch.plan(root)
            self.assertEqual(before, {name: (root/name).read_bytes() for name in patch.FILES})

    def test_all_notification_actions_are_bound(self):
        text = self.planned[patch.NOTIFICATIONS].decode()
        calls = re.findall(r'PendingIntent\.get(?:Activity|Broadcast|Service)\(ApplicationLoader\.applicationContext,[^\n]+', text)
        self.assertEqual(len(calls), 13)
        for call in calls:
            self.assertIn('NotificationAccountBinding.bind(', call)

    def test_async_receivers_revalidate_owner(self):
        for name in ['WearReplyReceiver', 'AutoMessageHeardReceiver']:
            text = self.planned[patch.JAVA+'messenger/'+name+'.java'].decode()
            self.assertIn('NotificationAccountBinding.isCurrent(intent, currentAccount)', text)
            for anchor in ['Utilities.globalQueue.postRunnable(() -> {', 'AndroidUtilities.runOnUIThread(() -> {']:
                callbacks = text.split(anchor)[1:]
                self.assertEqual(len(callbacks), 2)
                for block in callbacks:
                    first = block.lstrip().splitlines()[0]
                    self.assertIn('NotificationAccountBinding.isCurrent(currentAccount, expectedUserId)', first)

def test_native_selector():
    compiler = shutil.which('g++')
    if not compiler:
        raise SystemExit('Native selector check requires g++; do not report compilation as passed.')
    planned = patch.plan(SOURCE)
    cpp = planned[patch.CONNECTIONS].decode()
    start = cpp.index('ConnectionsManager& ConnectionsManager::getInstance(')
    end = cpp.index('\nint ConnectionsManager::callEvents(', start)
    actual_function = cpp[start:end]
    capacity = re.search(r'#define MAX_ACCOUNT_COUNT (\d+)', planned[patch.DEFINES].decode())[1]
    harness = '''#include <array>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <thread>
#include <vector>
#include <iostream>
#define MAX_ACCOUNT_COUNT CAPACITY
std::array<std::atomic<int>, MAX_ACCOUNT_COUNT> constructions{};
class ConnectionsManager {
public:
    int id;
    explicit ConnectionsManager(int value): id(value) { ++constructions[value]; }
    static ConnectionsManager& getInstance(int32_t instanceNum);
};
FUNCTION
int main(int argc, char** argv) {
    if (argc == 2) { ConnectionsManager::getInstance(std::atoi(argv[1])); return 99; }
    std::atomic<int> errors{0};
    std::vector<std::thread> threads;
    for (int t = 0; t < 16; ++t) threads.emplace_back([&] {
        for (int round = 0; round < 1000; ++round) for (int i = 0; i < MAX_ACCOUNT_COUNT; ++i) {
            auto& instance = ConnectionsManager::getInstance(i);
            if (instance.id != i || &instance != &ConnectionsManager::getInstance(i)) ++errors;
        }
    });
    for (auto& thread : threads) thread.join();
    for (int i = 0; i < MAX_ACCOUNT_COUNT; ++i) {
        if (constructions[i] != 1) ++errors;
        for (int j = 0; j < i; ++j)
            if (&ConnectionsManager::getInstance(i) == &ConnectionsManager::getInstance(j)) ++errors;
    }
    std::cout << "Native selector errors: " << errors << "\\n";
    return errors ? 1 : 0;
}
'''.replace('CAPACITY', capacity).replace('FUNCTION', actual_function)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        source, executable = root/'selector.cpp', root/'selector'
        source.write_text(harness, encoding='utf-8')
        subprocess.run([compiler, '-std=c++17', '-pthread', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(executable)], check=True, timeout=60)
        subprocess.run([str(executable)], check=True, timeout=30)
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for invalid in ['-1', capacity]:
            result = subprocess.run([str(executable), invalid], capture_output=True, timeout=10)
            if result.returncode not in [-6, 134]:
                raise ValueError('Invalid slot was not rejected by abort.')
    print('PASS: compiled actual native selector, 160000 concurrent lookups, unique slot instances and invalid-slot rejection. Network/JNI runtime not exercised.')

if __name__ == '__main__':
    native = '--native' in sys.argv
    if native:
        sys.argv.remove('--native')
    result = unittest.main(exit=False).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    if native:
        test_native_selector()
