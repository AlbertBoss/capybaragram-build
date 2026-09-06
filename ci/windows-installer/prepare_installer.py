# SPDX-License-Identifier: MIT
"""Verify the exact known native binary before packaging, without owner API secrets."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess

SOURCE_RUN = 34031740962
SOURCE_HEAD = '4ee5059a997be3dcf7bc913d9758babedf3287b2'
EXE_SHA256 = '24150fb9370a9473eef888e77ed4905df34866ffc7675d802a45f08f57e26a8a'

def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Windows':
        raise ValueError('Packaging runs only on the disposable Windows CI machine.')
    stage = Path(os.environ['RUNNER_TEMP']) / 'installer-input'
    exe = stage / 'CapybaraGram.exe'
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    if digest != EXE_SHA256:
        raise ValueError('Native binary differs from the reviewed artifact.')
    checksum = (stage/'SHA256SUMS.txt').read_text(encoding='utf-8-sig').strip()
    if checksum != EXE_SHA256 + ' *CapybaraGram.exe':
        raise ValueError('Native artifact checksum record differs.')
    with exe.open('rb') as stream:
        header = stream.read(64)
        if header[:2] != b'MZ':
            raise ValueError('Not a Windows executable.')
        offset = struct.unpack_from('<I', header, 60)[0]
        if offset > exe.stat().st_size - 6:
            raise ValueError('Invalid PE header position.')
        stream.seek(offset)
        if stream.read(6) != b'PE\0\0\x64\x86':
            raise ValueError('Expected native x64 executable.')
    info = (stage/'BUILD-INFO.txt').read_text(encoding='utf-8-sig')
    if not re.search(rf'(?m)^Run: {SOURCE_RUN}\s*$', info) or 'RELEASE CANDIDATE, not approved for final delivery. Build configuration: Release.' not in info:
        raise ValueError('Native build provenance differs.')
    for filename in ['LICENSE', 'LEGAL']:
        if (stage/filename).stat().st_size < 20:
            raise ValueError('Upstream license notice missing.')
    (stage/'SOURCE.txt').write_text(
        'CapybaraGram Windows source and reproducible build instructions\n'
        f'https://github.com/AlbertBoss/capybaragram-build/tree/{SOURCE_HEAD}\n'
        'Upstream and submodules are pinned by the build workflow.\n'
        'Upstream: https://github.com/telegramdesktop/tdesktop/tree/80158983dba09d3bf5d96701f21473d6c34bf5f5\n'
        f'Native build: https://github.com/AlbertBoss/capybaragram-build/actions/runs/{SOURCE_RUN}\n'
        f'Native SHA256: {digest}\n', encoding='utf-8')
    (stage/'INSTALL-NOTES.txt').write_text(
        'CapybaraGram — тестовая версия / Preview\n\n'
        'Неофициальный клиент Telegram. Эта сборка предназначена для проверки установки; '
        'она ещё не готова к повседневному использованию.\n'
        'Вход, несколько аккаунтов, уведомления и новые функции требуют проверки.\n'
        'Автоматическое обновление отключено. Установщик не имеет цифровой подписи.\n'
        'При удалении приложения локальные данные сохраняются.\n\n'
        'Unofficial Telegram client. This preview is for installation testing. '
        'Login, multi-account behavior, notifications and added features still require acceptance testing. '
        'Automatic updates are disabled. The installer is unsigned. '
        'Uninstalling preserves local user data.\n', encoding='utf-8-sig')
    compiler = Path(os.environ['ProgramFiles(x86)']) / 'Inno Setup 6' / 'ISCC.exe'
    if not compiler.is_file():
        raise ValueError('Expected runner-provided Inno Setup compiler missing.')
    spec = importlib.util.spec_from_file_location('capy_identity', Path(__file__).parents[1]/'prepare_windows_online.py')
    identity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(identity)
    out = Path('ci/installer-results').resolve()
    out.mkdir(parents=True, exist_ok=True)
    command = [str(compiler), '/Qp', '/DInputDir='+str(stage), '/DOutputDir='+str(out),
               '/DToastClsid='+identity.identity('toast-activator'), str(Path(__file__).with_name('capybaragram.iss').resolve())]
    subprocess.run(command, check=True, timeout=600)
    setup = out/'CapybaraGram-Windows-x64-Setup.exe'
    setup_hash = hashlib.sha256(setup.read_bytes()).hexdigest()
    (out/'SHA256SUMS.txt').write_text(setup_hash+' *'+setup.name+'\n', encoding='ascii')
    (out/'BUILD-INFO.json').write_text(json.dumps(dict(source_run=SOURCE_RUN, source_head=SOURCE_HEAD,
        native_sha256=digest, setup_sha256=setup_hash, final_release=False,
        purpose='Installer verification using the exact optimized Release candidate; real account session upgrade acceptance remains pending.',
        github_run=os.environ['GITHUB_RUN_ID']), indent=2)+'\n', encoding='utf-8')
    print('Verified exact native x64 artifact and compiled preview installer.')

if __name__ == '__main__':
    main()
