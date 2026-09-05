# SPDX-License-Identifier: MIT
"""Inspect a baseline APK without installing it or extracting archive entries."""
import argparse
import hashlib
import json
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

def locate_apk(source):
    """Use AGP's output manifest rather than assuming a variant directory layout."""
    # AGP can place IDE-targeted APKs under intermediates instead of outputs/apk.
    # The injected ABI option is an IDE build option; use the artifact type below.
    root = source / 'TMessagesProj_App/build'
    if not root.is_dir():
        raise RuntimeError('Application build directory is absent: TMessagesProj_App/build')
    manifests = list(root.rglob('output-metadata.json'))
    files = sorted({str(p.relative_to(root)) for p in root.rglob('*.apk')} | {str(p.relative_to(root)) for p in manifests})
    print('APK/metadata files (' + str(len(files)) + '): ' + ', '.join(files[:60]))
    matches = []
    for manifest in manifests:
        manifest.resolve(strict=True).relative_to(root.resolve(strict=True))
        if manifest.is_symlink() or manifest.stat().st_size > 65536:
            raise RuntimeError('Invalid APK output metadata.')
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('artifactType', {}).get('type') != 'APK':
            continue
        if data.get('variantName') != 'afatDebug':
            continue
        if data.get('applicationId') != 'org.capybaragram.buildtest.beta':
            raise RuntimeError('Unexpected application ID in output metadata.')
        elements = data.get('elements', [])
        if len(elements) != 1:
            raise RuntimeError('Expected one afatDebug output in metadata.')
        name = elements[0].get('outputFile')
        if not isinstance(name, str) or not name.endswith('.apk') or '/' in name or '\\' in name or ':' in name:
            raise RuntimeError('APK metadata must name a local APK file.')
        apk = manifest.parent / name
        if apk.is_symlink() or not apk.is_file():
            raise RuntimeError('APK output is not a regular file.')
        apk.resolve(strict=True).relative_to(root.resolve(strict=True))
        matches.append(apk)
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one afatDebug APK output manifest.')
    return matches[0].resolve(strict=True)

def collect(source, output):
    source = source.resolve(strict=True)
    apk = locate_apk(source)
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
        for name in libraries:
            with archive.open(name) as library:
                header = library.read(20)
            if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\xb7\x00':
                raise RuntimeError('Native library is not a little-endian ARM64 ELF file.')
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
        'Verified: package ID, absence of INTERNET, APK signature verification and ARM64 ELF library headers.\n'
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
