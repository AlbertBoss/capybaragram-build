# SPDX-License-Identifier: MIT
"""Actual Windows Qt codec check; no Telegram profiles, network or owner secrets."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

here = Path(__file__).resolve().parent
root = Path(os.environ['RUNNER_TEMP']) / 'capy-archive-setting-runtime'
root.mkdir(exist_ok=False)
report = here / 'settings-test-results'
report.mkdir(exist_ok=False)
flags = shlex.split(subprocess.run(['pkg-config', '--cflags', '--libs', 'Qt6Core'],
    capture_output=True, text=True, check=True, timeout=30).stdout)
qt_version = subprocess.run(['pkg-config', '--modversion', 'Qt6Core'],
    capture_output=True, text=True, check=True, timeout=30).stdout.strip()
exe = root / 'capy-archive-settings-test.exe'
subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
    str(here / 'capy_archive_settings_test.cpp'), '-o', str(exe)] + flags,
    check=True, timeout=180)
runtime = subprocess.run([str(exe)], capture_output=True, encoding='utf-8',
    errors='replace', timeout=30)
(report / 'runtime-result.txt').write_text(runtime.stdout + runtime.stderr, encoding='utf-8')
match = re.fullmatch(r'CAPY_QT_ARCHIVE_SETTINGS=PASS checks=([0-9]+)\s*', runtime.stdout)
if runtime.returncode or not match:
    raise RuntimeError('Native archive setting codec failed; inspect artifact')
result = {
    'platform': sys.platform, 'result': 'PASS', 'checks': int(match.group(1)),
    'qt_version': qt_version,
    'source_sha256': {p.name: hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        for p in (here / 'capy_archive_settings.h', here / 'capy_archive_settings_test.cpp', Path(__file__))},
    'full_client_compiled': False, 'account_restart_tested': False,
    'test_dependencies': 'Official MSYS2 test-only Qt Core; production pinned Qt is checked in full client build'}
(report / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(runtime.stdout, flush=True)
