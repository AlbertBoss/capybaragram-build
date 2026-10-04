# SPDX-License-Identifier: MIT
"""Use eager imports where the SDK and Rust raw-dylib import libraries overlap.

The immutable candidate's ADVAPI32 call used an orphan IAT slot with the Rust
advapi32 descriptor, yielding an out-of-range delay-helper lookup and startup AV.
This is a build fix. It changes no client feature, account, DLL search policy,
Windows setting, or vendor source. Optional DirectX libraries stay delay-loaded.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE_SHA = '80158983dba09d3bf5d96701f21473d6c34bf5f5'
HOST = 'Telegram/CMakeLists.txt'
# Rust/Windows crate and SDK import records have different module-name casing.
# The list covers the overlapping DLLs in the admitted connection library.
IMPORTS = (
    '        /DELAYLOAD:advapi32.dll\n',
    '        /DELAYLOAD:ws2_32.dll\n',
    '        /DELAYLOAD:crypt32.dll\n',
    '        /DELAYLOAD:bcrypt.dll\n',
    '        /DELAYLOAD:secur32.dll\n',
    '        /DELAYLOAD:userenv.dll\n',
    '            /DELAYLOAD:API-MS-Win-Core-Synch-l1-2-0.dll # Synchronization.lib\n',
)

def replacement(line):
    indentation = line[:len(line) - len(line.lstrip())]
    name = line.split('/DELAYLOAD:', 1)[1].split()[0]
    return indentation + '# Capy eager SDK/Rust import: ' + name + '\n'

def transform(text, reverse=False):
    for original in IMPORTS:
        marker = replacement(original)
        before, after = (marker, original) if reverse else (original, marker)
        # Anchor at line start: Updater has a separately indented ADVAPI32 flag.
        before, after = '\n' + before, '\n' + after
        if text.count(before) != 1 or after in text:
            raise ValueError('Pinned eager-import anchor differs')
        text = text.replace(before, after)
    return text

def prepare(source, check=False):
    root = Path(source).resolve(strict=True)
    process = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                             capture_output=True, check=True, timeout=30)
    if process.stdout.decode('ascii').strip() != SOURCE_SHA:
        raise ValueError('Wrong Telegram revision')
    path = root / HOST
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('Build host escapes source checkout')
    native = json.loads((HERE / 'windows-connection-native/native-hashes.json').read_text())
    if native['source_sha'] != SOURCE_SHA:
        raise ValueError('Connection revision differs')
    expected = native['post'][HOST]
    raw = path.read_bytes()
    normalized = raw.replace(b'\r\n', b'\n').decode('utf-8')
    original = transform(normalized, reverse=True) if check else normalized
    if hashlib.sha256(original.encode('utf-8')).hexdigest() != expected:
        raise ValueError('Complete prepared CMake host differs')
    prepared = transform(original)
    if check and prepared != normalized:
        raise ValueError('Eager import preparation differs')
    if not check:
        path.write_bytes(prepared.replace('\n', '\r\n').encode('utf-8') if b'\r\n' in raw else prepared.encode('utf-8'))
    return hashlib.sha256(prepared.encode('utf-8')).hexdigest()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print('CAPY_EAGER_IMPORT_SOURCE=PASS sha256=' + prepare(args.source, args.check))
