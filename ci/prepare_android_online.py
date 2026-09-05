# SPDX-License-Identifier: MIT
"""Convert the reviewed offline checkout to a separate online preview.

Run after prepare_android_baseline.py on a disposable checkout. Credentials are
read from the environment, never CLI arguments. Do not upload this modified
checkout, backups, build intermediates or private signing material as artifacts.
"""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from api_credentials import credentials

PACKAGE = 'org.capybaragram.preview'
BACKUP = '.capybara-online-backup'

def load_baseline(control):
    # Explicitly supplied build-control directory, owned/reviewed by the caller.
    spec = importlib.util.spec_from_file_location('capy_baseline', control / 'prepare_android_baseline.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def changes(root, baseline, environ=None):
    api_id, api_hash = credentials(environ)
    offline_backup = root / baseline.BACKUP
    if offline_backup.is_symlink() or (hasattr(offline_backup,'is_junction') and offline_backup.is_junction()):
        raise ValueError('Offline backup must be a regular directory.')
    _, expected = baseline.plan(offline_backup)
    originals = {}
    for relative, content in expected.items():
        current = baseline.safe_path(root, relative).read_bytes()
        if current != content:
            raise ValueError('Source differs from the reviewed offline preparation.')
        originals[relative] = current
    transformed = {}
    relative = 'TMessagesProj/src/main/java/org/telegram/messenger/BuildVars.java'
    text = originals[relative].decode('utf-8')
    text = baseline.replace_once(text, r'(?m)^(\s*public static int APP_ID\s*=)\s*0;', lambda m: m[1] + ' ' + api_id + ';')
    text = baseline.replace_once(text, r'(?m)^(\s*public static String APP_HASH\s*=)\s*"";', lambda m: m[1] + ' "' + api_hash + '";')
    transformed[relative] = text.encode('utf-8')
    for relative in ('TMessagesProj/config/debug/AndroidManifest.xml', 'TMessagesProj/config/debug/AndroidManifest_SDK23.xml'):
        doc = ET.fromstring(originals[relative])
        permissions = [e for e in doc.findall('uses-permission')
                       if e.get('{'+baseline.ANDROID+'}name') == 'android.permission.INTERNET'
                       and e.get('{'+baseline.TOOLS+'}node') == 'remove']
        if len(permissions) != 1: raise ValueError('Expected one offline INTERNET removal marker.')
        doc.remove(permissions[0])
        doc.find('application').set('{'+baseline.ANDROID+'}label', 'CapybaraGram Preview')
        # Explicit permission, not reliance on a transitive manifest.
        doc.insert(0, ET.Element('uses-permission', {'{'+baseline.ANDROID+'}name':'android.permission.INTERNET'}))
        transformed[relative] = ('<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(doc, encoding='unicode') + '\n').encode('utf-8')
    relative = 'gradle.properties'
    text = baseline.replace_once(originals[relative].decode('utf-8'), r'(?m)^APP_PACKAGE=.*$', 'APP_PACKAGE=' + PACKAGE)
    transformed[relative] = text.encode('utf-8')
    relative = 'TMessagesProj_App/build.gradle'
    text = originals[relative].decode('utf-8')
    for pattern, replacement in [
        (r'storeFile file\("\.\./TMessagesProj/config/capybara-debug\.keystore"\)',
         'storeFile file(System.getenv("CAPY_ANDROID_KEYSTORE_PATH"))'),
        (r'storePassword "android"', 'storePassword System.getenv("CAPY_ANDROID_KEYSTORE_PASSWORD")'),
        (r'keyAlias "androiddebugkey"', 'keyAlias "capybaragram-preview"'),
        (r'keyPassword "android"', 'keyPassword System.getenv("CAPY_ANDROID_KEYSTORE_PASSWORD")'),
    ]:
        text = baseline.replace_once(text, pattern, replacement)
    transformed[relative] = text.encode('utf-8')
    return originals, transformed

def prepare(source, baseline, environ=None, check=False):
    root = source.resolve(strict=True)
    if source.is_symlink() or (hasattr(source,'is_junction') and source.is_junction()):
        raise ValueError('Source must be a regular directory.')
    result = subprocess.run(['git','-C',str(root),'rev-parse','HEAD'], capture_output=True, text=True, timeout=30)
    if result.returncode or result.stdout.strip() != baseline.SHA:
        raise ValueError('Unexpected source revision.')
    result = subprocess.run(['git','-C',str(root),'rev-parse','--show-toplevel'], capture_output=True, text=True, timeout=30)
    if result.returncode or Path(result.stdout.strip()).resolve() != root:
        raise ValueError('Source must be the repository root.')
    result = subprocess.run(['git','-C',str(root),'status','--porcelain','--untracked-files=no','--ignore-submodules=none'], capture_output=True, text=True, timeout=30)
    if result.returncode or any(line[:3] != ' M ' or line[3:] not in baseline.PATHS for line in result.stdout.splitlines()):
        raise ValueError('Checkout contains changes beyond offline preparation.')
    backup = root / BACKUP
    if backup.exists() or backup.is_symlink(): raise ValueError('Use a fresh offline-prepared checkout.')
    originals, transformed = changes(root, baseline, environ)
    if check: return
    for relative, content in originals.items():
        if baseline.safe_path(root, relative).read_bytes() != content:
            raise ValueError('Source changed during online preparation.')
    backup.mkdir()
    for relative in transformed:
        destination = backup / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(originals[relative])
    for relative, content in transformed.items():
        baseline.safe_path(root, relative).write_bytes(content)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--control-ci', type=Path, required=True)
    p.add_argument('--check', action='store_true')
    args = p.parse_args()
    try:
        prepare(args.source, load_baseline(args.control_ci.resolve(strict=True)), check=args.check)
    except (ValueError, OSError, ET.ParseError, subprocess.SubprocessError):
        print('REFUSED: invalid credentials, source state or preparation output. No values logged.')
        raise SystemExit(1)
    print('PASS: online preview preparation; real login and signing still require verification.')
