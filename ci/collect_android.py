# SPDX-License-Identifier: MIT
"""Inspect an APK without installing it or extracting archive entries."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

PROFILES = {
    'offline': ('org.capybaragram.buildtest.beta', 'CapybaraGram-OFFLINE-BUILD-TEST.apk'),
    'preview': ('org.capybaragram.preview.beta', 'CapybaraGram-Preview-arm64.apk'),
    'candidate': ('org.capybaragram', 'CapybaraGram-Android-arm64.apk'),
}

def checked(args):
    p = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=90, check=False)
    if p.returncode:
        raise RuntimeError(f"Artifact inspection failed: {Path(args[0]).name}")
    return p.stdout

def locate_apk(source, package='org.capybaragram.buildtest.beta', variant='afatDebug'):
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
        if data.get('variantName') != variant:
            continue
        if data.get('applicationId') != package:
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
        raise RuntimeError('Expected exactly one '+variant+' APK output manifest.')
    return matches[0].resolve(strict=True)

def require_normal_install(manifest):
    require_disabled_flag(manifest, 'testOnly')

def require_disabled_flag(manifest, name):
    if name not in {'testOnly','debuggable','allowBackup'}:
        raise ValueError('Unexpected manifest flag')
    values = re.findall(r'\bandroid:'+name+r'(?:\([^)]*\))?\s*=\s*([^\r\n]+)', manifest)
    if not values:
        if name == 'allowBackup':
            raise RuntimeError('APK must explicitly disable allowBackup.')
        return
    if len(values) != 1:
        raise RuntimeError('Ambiguous '+name+' attributes in signed APK manifest.')
    value = values[0].strip().lower().replace(' ', '')
    if value != 'false' and not re.fullmatch(r'\(type0x12\)0x0+',value):
        raise RuntimeError('APK manifest must disable '+name+'.')

def collect(source, output, profile='offline', certificate_sha256=None):
    if profile not in PROFILES:
        raise RuntimeError('Unknown APK profile.')
    package, filename = PROFILES[profile]
    online = profile != 'offline'
    if online and (not isinstance(certificate_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', certificate_sha256)):
        raise RuntimeError('Preview requires a pinned signing certificate SHA256.')
    source = source.resolve(strict=True)
    apk = locate_apk(source, package, 'afatRelease' if profile == 'candidate' else 'afatDebug')
    apk.relative_to(source)
    sdk_env = os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT')
    if not sdk_env:
        raise RuntimeError('Android SDK is not configured.')
    tools = Path(sdk_env) / 'build-tools/36.0.0'
    badging = checked([tools / 'aapt', 'dump', 'badging', apk])
    if not re.search(r"^package: name='" + re.escape(package) + r"' ", badging, re.M):
        raise RuntimeError('Unexpected application ID; refusing to package.')
    permissions = checked([tools / 'aapt', 'dump', 'permissions', apk])
    if online:
        manifest = checked([tools / 'aapt','dump','xmltree',apk,'AndroidManifest.xml'])
        require_normal_install(manifest)
        if profile == 'candidate':
            require_disabled_flag(manifest,'debuggable')
            require_disabled_flag(manifest,'allowBackup')
    if ('android.permission.INTERNET' in permissions) != online:
        raise RuntimeError('INTERNET permission does not match the requested APK profile.')
    signature = checked([tools / 'apksigner', 'verify', '--verbose', '--print-certs', apk])
    if online:
        fingerprints = re.findall(r'^Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-fA-F]{64})\s*$', signature, re.M)
        if [value.lower() for value in fingerprints] != [certificate_sha256]:
            raise RuntimeError('APK signer does not match the pinned preview certificate.')
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError('Duplicate archive entries.')
        if 'AndroidManifest.xml' not in names or 'classes.dex' not in names:
            raise RuntimeError('APK missing manifest or code.')
        libraries = [n for n in names if n.startswith('lib/') and n.endswith('.so')]
        print('Packaged native libraries (' + str(len(libraries)) + '): ' + ', '.join(sorted(libraries)))
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
    dest = output / filename
    shutil.copyfile(apk, dest)
    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{digest} *{dest.name}\n', encoding='ascii')
    description = (
        'ONLINE PREVIEW, not a release. Owner application credentials and persistent preview signature.\n'
        'Certificate SHA256: ' + certificate_sha256 + '\n'
        'Modifications: ci/prepare_android_baseline.py, ci/prepare_android_online.py, ci/accounts/android_accounts_patch.py, ci/notes/prepare_android_notes.py, ci/brand/prepare_android_brand.py.\n'
        'Local notes and template UI included; full client login, UI and session lifecycle acceptance remains required.\n'
        'Verified: package ID, INTERNET permission, testOnly absent/false, pinned APK signer and ARM64 ELF library headers.\n'
    ) if online else (
        'OFFLINE BUILD TEST, not a working Telegram client or release.\n'
        'No INTERNET permission, API_ID=0, ephemeral debug signature.\n'
        'Modifications: ci/prepare_android_baseline.py in the build repository.\n'
        'Verified: package ID, absence of INTERNET, APK signature verification and ARM64 ELF library headers.\n'
    )
    if profile == 'candidate':
        description = description.replace('ONLINE PREVIEW, not a release.','RELEASE CANDIDATE, not approved for final delivery.')
        description += 'Candidate preparation: ci/prepare_android_candidate.py. afatRelease; debuggable and allowBackup absent/false verified.\n'
    (output / 'BUILD-INFO.txt').write_text(description +
        'Source: https://github.com/DrKLO/Telegram/tree/62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c\n'
        'Not verified: installation, UI launch, actual login, notifications, calls.\n', encoding='utf-8')
    for name in ['LICENSE', 'LICENSE.md', 'LEGAL']:
        if (source / name).is_file():
            shutil.copyfile(source / name, output / name)
    print('PASS: ' + profile + ' APK structure, signature and package; runtime not tested.')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--profile', choices=PROFILES, default='offline')
    args = p.parse_args()
    collect(args.source, args.output, args.profile, os.environ.get('CAPY_ANDROID_CERT_SHA256'))
