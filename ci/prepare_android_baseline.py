# SPDX-License-Identifier: MIT
"""Prepare a disposable offline build baseline. Never use this configuration for a release.

Written by Codex after two failed Fable generations. --check changes nothing.
All transformations are validated before writing. Backups precede writes, but an
interrupted process can still leave a partially patched tree; discard that checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

SHA = '62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c'
BACKUP = '.capybara-baseline-backup'
ANDROID = 'http://schemas.android.com/apk/res/android'
TOOLS = 'http://schemas.android.com/tools'
ET.register_namespace('android', ANDROID)
ET.register_namespace('tools', TOOLS)
PATHS = (
    'settings.gradle', 'TMessagesProj_App/build.gradle', 'gradle.properties',
    'TMessagesProj/src/main/java/org/telegram/messenger/BuildVars.java',
    'TMessagesProj/config/debug/AndroidManifest.xml',
    'TMessagesProj/config/debug/AndroidManifest_SDK23.xml',
)

def replace_once(text, pattern, replacement):
    if len(re.findall(pattern, text)) != 1:
        raise ValueError('Expected exactly one known source anchor.')
    return re.sub(pattern, replacement, text, count=1)

def safe_path(root, relative):
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Source-relative paths only.')
    path = root / relative
    current = path
    while current != root:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('Symbolic links/junctions are not accepted.')
        current = current.parent
    path.resolve(strict=True).relative_to(root)
    if not path.is_file():
        raise ValueError('Expected a regular source file.')
    return path

def verify_git(root):
    def git(*args):
        p = subprocess.run(['git', '-C', str(root), *args], shell=False,
                           capture_output=True, text=True, timeout=30)
        if p.returncode:
            raise ValueError('Git verification failed.')
        return p.stdout.strip()
    if Path(git('rev-parse', '--show-toplevel')).resolve() != root:
        raise ValueError('Source must be the repository root.')
    if git('rev-parse', 'HEAD') != SHA:
        raise ValueError('Unexpected source revision.')
    if git('status', '--porcelain', '--untracked-files=no', '--ignore-submodules=none'):
        raise ValueError('Tracked source has local changes.')

def transform_settings(text):
    expected = {'TMessagesProj','TMessagesProj_App','TMessagesProj_AppHuawei',
                'TMessagesProj_AppHockeyApp','TMessagesProj_AppStandalone','TMessagesProj_AppTests','jlatexmath'}
    found = re.findall(r"(?m)^include ':(\w+)'\s*$", text)
    if len(found) != len(expected) or set(found) != expected:
        raise ValueError('Unexpected module declarations.')
    for module in sorted(expected - {'TMessagesProj', 'TMessagesProj_App', 'jlatexmath'}):
        text = replace_once(text, rf"(?m)^include ':{module}'[^\S\n]*\n?", '')
    return text

def transform_app(text):
    pattern = r'(?ms)(signingConfigs\s*\{\s*debug\s*\{)(.*?)(^\s*\})'
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError('Unexpected debug signing block.')
    m = matches[0]
    body = m.group(2)
    replacements = [
        (r'storeFile file\("\.\./TMessagesProj/config/release\.keystore"\)', 'storeFile file("../TMessagesProj/config/capybara-debug.keystore")'),
        (r'\bstorePassword RELEASE_STORE_PASSWORD\b', 'storePassword "android"'),
        (r'\bkeyAlias RELEASE_KEY_ALIAS\b', 'keyAlias "androiddebugkey"'),
        (r'\bkeyPassword RELEASE_KEY_PASSWORD\b', 'keyPassword "android"'),
    ]
    for pattern, replacement in replacements:
        body = replace_once(body, pattern, replacement)
    text = text[:m.start(2)] + body + text[m.end(2):]
    return replace_once(text, r"(?m)^apply plugin: 'com\.google\.gms\.google-services'[^\S\n]*$", '// Offline baseline: no Firebase project is configured.')

def transform_vars(text):
    fields = [('int','APP_ID','0')]
    fields += [('String', k, '""') for k in ['APP_HASH','SAFETYNET_KEY','GOOGLE_AUTH_CLIENT_ID','HUAWEI_APP_ID']]
    fields += [('boolean', k, 'false') for k in ['CHECK_UPDATES','USE_CLOUD_STRINGS','LOGS_ENABLED']]
    for kind, name, value in fields:
        pattern = rf'(?m)^(\s*public static {kind} {name}\s*=)[^;\n]*;'
        text = replace_once(text, pattern, lambda m, v=value: m.group(1) + ' ' + v + ';')
    return text

def transform_properties(text):
    text = replace_once(text, r'(?m)^org\.gradle\.jvmargs=.*$', 'org.gradle.jvmargs=-Xmx3g -XX:MaxMetaspaceSize=768m')
    text = replace_once(text, r'(?m)^org\.gradle\.parallel=true[^\S\n]*$', 'org.gradle.parallel=false')
    if re.search(r'(?m)^org\.gradle\.workers\.max=', text):
        text = replace_once(text, r'(?m)^org\.gradle\.workers\.max=.*$', 'org.gradle.workers.max=2')
    else:
        text = text.rstrip() + '\norg.gradle.workers.max=2\n'
    return text

def transform_manifest(text):
    doc = ET.fromstring(text)
    apps = doc.findall('application')
    if len(apps) != 1:
        raise ValueError('Expected one manifest application.')
    app = apps[0]
    keys = [e for e in app.findall('meta-data') if e.get(f'{{{ANDROID}}}name') == 'com.google.android.maps.v2.API_KEY']
    if len(keys) != 1:
        raise ValueError('Unexpected maps metadata.')
    app.remove(keys[0])
    app.set(f'{{{ANDROID}}}label', 'CapybaraGram Build Test')
    if any(e.get(f'{{{ANDROID}}}name') == 'android.permission.INTERNET' for e in doc.findall('uses-permission')):
        raise ValueError('Unexpected existing INTERNET overlay.')
    remove = ET.Element('uses-permission', {f'{{{ANDROID}}}name':'android.permission.INTERNET',f'{{{TOOLS}}}node':'remove'})
    doc.insert(0, remove)
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(doc, encoding='unicode') + '\n'

def plan(root):
    expected = json.loads(Path(__file__).with_name('android-input-hashes.json').read_text(encoding='utf-8'))
    originals, changes = {}, {}
    for relative in PATHS:
        content = safe_path(root, relative).read_bytes()
        normalized = content.replace(b'\r\n', b'\n')
        if hashlib.sha256(normalized).hexdigest() != expected[relative]:
            raise ValueError(f'Input file differs from reviewed source: {relative}')
        originals[relative] = content
        text = normalized.decode('utf-8')
        if relative == 'settings.gradle': new = transform_settings(text)
        elif relative.endswith('build.gradle'): new = transform_app(text)
        elif relative == 'gradle.properties': new = transform_properties(text)
        elif relative.endswith('BuildVars.java'): new = transform_vars(text)
        else: new = transform_manifest(text)
        changes[relative] = new.encode('utf-8')
    return originals, changes

def prepare(source, check=False):
    if source.is_symlink() or (hasattr(source, 'is_junction') and source.is_junction()):
        raise ValueError('Source cannot be a symlink/junction.')
    root = source.resolve(strict=True)
    backup = root / BACKUP
    if backup.exists() or backup.is_symlink():
        raise ValueError('Baseline backup already exists; use a fresh checkout.')
    verify_git(root)
    originals, changes = plan(root)
    if check:
        print('CHECK: ' + ', '.join(changes))
        return
    # Re-read all inputs before the first mutation. A disposable, exclusively owned
    # checkout is still required; this does not defend against a concurrent attacker.
    for relative, content in originals.items():
        if safe_path(root, relative).read_bytes() != content:
            raise ValueError('Source changed during preparation.')
    backup.mkdir(exist_ok=False)
    for relative, content in originals.items():
        dest = backup / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    for relative, content in changes.items():
        safe_path(root, relative).write_bytes(content)
    print('APPLIED: ' + ', '.join(changes))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        prepare(args.source, args.check)
    except (ValueError, OSError, ET.ParseError, subprocess.SubprocessError) as exc:
        # Never echo config contents or git diagnostics.
        print('REFUSED: ' + (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
        raise SystemExit(1)
