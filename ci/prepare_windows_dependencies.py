# SPDX-License-Identifier: MIT
"""Replace the unavailable MinGW diffutils build tool in the pinned upstream recipe.

MSYS diffutils is only used on the build runner. Pacman signature verification,
compiler selection and all client/runtime dependencies remain unchanged.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess

SOURCE_SHA = '80158983dba09d3bf5d96701f21473d6c34bf5f5'
SOURCE_FILE = 'Telegram/build/prepare/prepare.py'
INPUT_SHA256 = '398a7b0139dfa97c7cb6f1891bd324799f7529c554031f15566a162454169012'
OLD = b'        mingw-w64-x86_64-diffutils ^\n'
NEW = b'        diffutils ^\n'
END = b'        mingw-w64-x86_64-pkgconf\n'
PROBE = br'    "%THIRDPARTY_DIR%\\msys64\\usr\\bin\\diff.exe" --version' + b'\n'


def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=40)
    if result.returncode:
        raise ValueError('Source checkout verification failed.')
    return result.stdout


def transform(original):
    if hashlib.sha256(original).hexdigest() != INPUT_SHA256:
        raise ValueError('Pinned dependency recipe bytes differ.')
    if original.count(OLD) != 1 or original.count(END) != 1:
        raise ValueError('Reviewed dependency recipe anchors differ.')
    return original.replace(OLD, NEW).replace(END, END + PROBE)


def prepare(source, check=False):
    root = Path(source).resolve(strict=True)
    if git(root, 'rev-parse', 'HEAD').decode('ascii').strip() != SOURCE_SHA:
        raise ValueError('Source revision differs.')
    path = root / SOURCE_FILE
    if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
        raise ValueError('Dependency recipe path escapes checkout.')
    original = git(root, 'show', 'HEAD:' + SOURCE_FILE).replace(b'\r\n', b'\n')
    expected = transform(original)
    raw = path.read_bytes()
    if raw.replace(b'\r\n', b'\n') != (expected if check else original):
        raise ValueError('Dependency recipe does not match the expected preparation state.')
    if not check:
        path.write_bytes(expected.replace(b'\n', b'\r\n') if b'\r\n' in raw else expected)
    return hashlib.sha256(expected).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        digest = prepare(args.source, check=args.check)
    except (ValueError, OSError, UnicodeError, subprocess.TimeoutExpired):
        raise SystemExit('REFUSED: source state differs from the reviewed dependency recipe.')
    print('PASS: pinned Windows build-tool recipe ' + ('verified' if args.check else 'prepared') + '; sha256=' + digest)
