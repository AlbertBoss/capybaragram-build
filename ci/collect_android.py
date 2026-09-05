# SPDX-License-Identifier: MIT
"""Inspect a baseline APK without installing it or extracting archive entries."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

def checked(args):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=90, check=False)
    if p.returncode:
        raise RuntimeError(f"Artifact inspection failed: {Path(args[0]).name}")
    return p.stdout

def collect(source, output):
    source = source.resolve(strict=True)
    apks = list((source / 'TMessagesProj_App/build/outputs/apk/afat/debug').glob('*.apk'))
    if len(apks) != 1 or apks[0].is_symlink():
        raise RuntimeError('Expected exactly one regular afat/debug APK.')
    apk = apks[0].resolve(strict=True)
    apk.relative_to(source)
    sdk_env = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT')
    if not sdk_env:
        raise RuntimeError('Android SDK is not configured.')
    tools = Path(sdk_env) / 'build-tools/36.0.0'
    badging = checked([tools / 'aapt', 'dump', 'badging', apk])
    if not re.search(r"^package: name='org\.capybaragram\.buildtest\.beta' ", badging, re.M):
        raise RuntimeError('Unexpected application ID; refusing to package.')
    permissions = checked([tools / 'aapt', 'dump', 'permissions', apk])
    if 'android.permission.INTERNET' in permissions:
        raise RuntimeError('Offline baseline must not request INTERNET permission.')
    checked([tools / 'apksigner', 'verify', '--verbose', apk])
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError('Duplicate archive entries.')
        if 'AndroidManifest.xml' not in names or 'classes.dex' not in names:
            raise RuntimeError('APK missing manifest or code.')
        libraries = [n for n in names if n.startswith('lib/') and n.endswith('.so')]
        if not libraries or any(not n.startswith('lib/arm64-v8a/') for n in libraries):
            raise RuntimeError('Expected ARM64 libraries only.')
        if 'lib/arm64-v8a/libtmessages.49.so' not in libraries:
            raise RuntimeError('Telegram native library is absent.')
    if output.exists() or output.is_symlink():
        raise RuntimeError('Artifact directory must be new.')
    output.mkdir(parents=True)
    dest = output / 'CapybaraGram-OFFLINE-BUILD-TEST.apk'
    shutil.copyfile(apk, dest)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{digest} *{dest.name}\n', encoding='ascii')
    (output / 'BUILD-INFO.txt').write_text(
        'OFFLINE BUILD TEST, not a working Telegram client or release.\n'
        'No INTERNET permission, API_ID=0, ephemeral debug signature.\n'
        'Source: https://github.com/DrKLO/Telegram/tree/62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c\n'
        'Modifications: ci/prepare_android_baseline.py in the build repository.\n'
        'Verified: package ID, absence of INTERNET, APK signature verification and ARM64 library entries.\n'
        'Not verified: installation, UI launch, actual login, notifications, calls.\n', encoding='utf-8')
    for name in ['LICENSE', 'LICENSE.md', 'LEGAL']:
        if (source / name).is_file():
            shutil.copyfile(source / name, output / name)
    print('PASS: offline APK structure, signature and package; runtime not tested.')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    collect(args.source, args.output)
