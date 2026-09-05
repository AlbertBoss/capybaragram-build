# SPDX-License-Identifier: MIT
"""Apply a reviewed identity patch only to the pinned clean Desktop checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid

SOURCE_SHA = '80158983dba09d3bf5d96701f21473d6c34bf5f5'
PREFIX = 'Telegram/SourceFiles/'
FILES = [PREFIX + path for path in (
    'config.h', 'core/version.h', 'core/launcher.cpp', 'core/application.cpp', 'logs.cpp',
    'platform/win/specific_win.cpp', 'platform/win/windows_app_user_model_id.cpp',
    'platform/win/windows_toast_activator.h')]

def identity(name):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'https://github.com/AlbertBoss/capybaragram-build/windows-preview/' + name)).upper()

def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('Reviewed source anchor differs.')
    return text.replace(old, new)

def transform(name, text):
    if name == PREFIX + 'config.h':
        return replace(text, '87A94AB0-E370-4cde-98D3-ACC110C5967D', identity('ipc'))
    if name == PREFIX + 'core/version.h':
        for old, new in (
            ('53F49750-6209-4FBF-9CA8-7A333C87D1ED', identity('application')),
            ('"Telegram Win (Unofficial)"_cs', '"CapybaraGram Preview Legacy"_cs'),
            ('"Telegram Desktop"_cs', '"CapybaraGram Preview"_cs'),
            ('"Telegram"_cs', '"CapybaraGram"_cs')):
            text = replace(text, old, new)
        return text
    if name == PREFIX + 'core/launcher.cpp':
        start = text.index('bool MoveLegacyAlphaFolder(const QString &folder, const QString &file) {')
        end = text.index('bool CheckPortableVersionFolder() {', start)
        text = text[:start] + text[end:]
        text = replace(text, '\tif (!MoveLegacyAlphaFolder()) {\n\t\treturn false;\n\t}\n\n', '')
        text = replace(text, 'u"TelegramForcePortable"_q', 'u"CapybaraGramForcePortable"_q')
        return replace(text, 'QApplication::setApplicationName(u"TelegramDesktop"_q);',
                       'QApplication::setApplicationName(u"CapybaraGramPreview"_q);')
    if name == PREFIX + 'core/application.cpp':
        text = replace(text, '\t\tautoRegisterUrlScheme();\n', '')
        return replace(text, '.shortAppName = u"tdesktop"_q,', '.shortAppName = u"capybaragram-preview"_q,', 2)
    if name == PREFIX + 'logs.cpp':
        original = '#if (!defined Q_OS_WIN && !defined _DEBUG) || defined Q_OS_WINRT || defined OS_WIN_STORE || defined OS_MAC_STORE\n'
        patched = '''#ifdef Q_OS_WIN
		const auto path = psAppDataPath();
		if (path.isEmpty()) {
			delete LogsData;
			LogsData = nullptr;
			return;
		}
		cForceWorkingDir(path);
#elif !defined _DEBUG || defined OS_MAC_STORE
'''
        text = replace(text, original, patched)
        text = replace(text, '// (!Q_OS_WIN && !_DEBUG) || Q_OS_WINRT || OS_WIN_STORE || OS_MAC_STORE',
                       '// Q_OS_WIN || !_DEBUG || OS_MAC_STORE', 2)
        old = '''#ifdef Q_OS_WIN
	if (cWorkingDir() == psAppDataPath()) { // fix old "Telegram Win (Unofficial)" version
		MoveOldDataFiles(psAppDataPathOld());
	}
#elif !defined Q_OS_MAC && !defined _DEBUG // fix first version'''
        return replace(text, old, '#if !defined Q_OS_WIN && !defined Q_OS_MAC && !defined _DEBUG // fix first version')
    if name == PREFIX + 'platform/win/specific_win.cpp':
        text = replace(text, 'u"/Telegram Desktop UWP/"_q', 'u"/CapybaraGram Preview UWP/"_q')
        text = replace(text, '"\\\\Telegram.lnk"', '"\\\\CapybaraGram.lnk"', 2)
        for old, new in [('Telegram autorun link.', 'CapybaraGram autorun link.'),
                         ('Telegram send to link.', 'CapybaraGram send to link.'),
                         ('in Telegram settings.', 'in CapybaraGram settings.')]:
            text = replace(text, old, new, 2 if old == 'in Telegram settings.' else 1)
        return text
    if name == PREFIX + 'platform/win/windows_app_user_model_id.cpp':
        for old, new, count in [
            ('L"Telegram.TelegramDesktop.Store"', 'L"CapybaraGram.Preview.Store"', 1),
            ('L"Telegram.TelegramDesktop"', 'L"CapybaraGram.Preview"', 1),
            ('u"Telegram.lnk"_q', 'u"CapybaraGram.lnk"_q', 2),
            ('u"Telegram Desktop/Telegram.lnk"_q', 'u"CapybaraGram Preview/CapybaraGram.lnk"_q', 1),
            ('u"Telegram Win (Unofficial)/Telegram.lnk"_q', 'u"CapybaraGram Preview Legacy/CapybaraGram.lnk"_q', 1),
            ('u"TelegramAlpha.lnk"_q', 'u"CapybaraGramAlpha.lnk"_q', 1)]:
            text = replace(text, old, new, count)
        return text
    if name == PREFIX + 'platform/win/windows_toast_activator.h':
        return replace(text, 'F11932D3-6110-4BBC-9B02-B2EC07A1BD19', identity('toast-activator'), 2)
    raise ValueError('Unreviewed source file.')

def git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('Source checkout verification failed.')
    return result.stdout

def prepare(root, check=False):
    root = Path(root).resolve(strict=True)
    if git(root, 'rev-parse', 'HEAD').decode().strip() != SOURCE_SHA:
        raise ValueError('Source revision differs.')
    hashes = json.loads(Path(__file__).with_name('windows-input-hashes.json').read_text())
    if set(hashes) != set(FILES):
        raise ValueError('Source allowlist differs.')
    status = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    entries = [entry for entry in status.split(b'\0') if entry]
    expected_status = {b' M ' + name.encode() for name in FILES}
    if entries and (not check or set(entries) != expected_status):
        raise ValueError('Unexpected working-tree changes.')
    prepared = {}
    for name in FILES:
        path = root / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Source path escapes checkout.')
        original = git(root, 'show', 'HEAD:' + name).replace(b'\r\n', b'\n')
        if hashlib.sha256(original).hexdigest() != hashes[name]:
            raise ValueError('Pinned source bytes differ.')
        patched = transform(name, original.decode('utf-8')).encode('utf-8')
        actual = path.read_bytes().replace(b'\r\n', b'\n')
        if actual != (patched if check else original):
            raise ValueError('Source bytes do not match expected preparation state.')
        prepared[path] = patched
    if not check:
        for path, data in prepared.items():
            path.write_bytes(data.replace(b'\n', b'\r\n') if os.name == 'nt' else data)
    return len(prepared)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        count = prepare(args.source, args.check)
    except (ValueError, OSError, subprocess.TimeoutExpired):
        raise SystemExit('REFUSED: source state differs from the reviewed Windows identity patch.')
    print(f'PASS: {count} Windows identity source files ' + ('verified.' if args.check else 'prepared.'))
