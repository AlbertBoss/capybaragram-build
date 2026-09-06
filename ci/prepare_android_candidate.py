# SPDX-License-Identifier: MIT
"""Prepare a release candidate after the validated online/account/notes/brand steps.

Does not read, alter or report the owner API credentials in BuildVars.java.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import prepare_android_baseline as baseline

ROOT = Path(__file__).resolve().parent
FILES = ['TMessagesProj_App/build.gradle','gradle.properties',
    'TMessagesProj/config/release/AndroidManifest.xml',
    'TMessagesProj/config/release/AndroidManifest_SDK23.xml']

def replace(text,old,new):
    if text.count(old) != 1:
        raise ValueError('Candidate preparation anchor differs')
    return text.replace(old,new)

def transform(name,text):
    if name == FILES[0]:
        old = '''        release {
            storeFile file("../TMessagesProj/config/release.keystore")
            storePassword RELEASE_STORE_PASSWORD
            keyAlias RELEASE_KEY_ALIAS
            keyPassword RELEASE_KEY_PASSWORD
        }'''
        new = '''        release {
            storeFile file(System.getenv("CAPY_ANDROID_KEYSTORE_PATH"))
            storePassword System.getenv("CAPY_ANDROID_KEYSTORE_PASSWORD")
            keyAlias "capybaragram-preview"
            keyPassword System.getenv("CAPY_ANDROID_KEYSTORE_PASSWORD")
        }'''
        text = replace(text,old,new)
        return replace(text,'        minSdkVersion 21','        minSdkVersion 23')
    if name == FILES[1]:
        return replace(text,'APP_PACKAGE=org.capybaragram.preview','APP_PACKAGE=org.capybaragram')
    if name in FILES[2:]:
        # Reuse the reviewed metadata removal, operating on the release overlay.
        doc = ET.fromstring(baseline.transform_manifest(text))
        android = '{'+baseline.ANDROID+'}'
        tools = '{'+baseline.TOOLS+'}'
        removals = [e for e in doc.findall('uses-permission') if e.get(android+'name') == 'android.permission.INTERNET']
        if len(removals) != 1 or removals[0].get(tools+'node') != 'remove':
            raise ValueError('Expected temporary offline marker')
        del removals[0].attrib[tools+'node']
        app = doc.find('application')
        app.set(android+'label','CapybaraGram')
        app.set(android+'icon','@drawable/capy_icon_sand')
        app.set(android+'roundIcon','@drawable/capy_icon_sand')
        for alias,key in [('DefaultIcon','sand'),('VintageIcon','forest'),('AquaIcon','water'),
                          ('PremiumIcon','clay'),('TurboIcon','lilac'),('NoxIcon','night')]:
            ET.SubElement(app,'activity-alias',{
                android+'name':'org.telegram.messenger.'+alias,
                android+'icon':'@drawable/capy_icon_'+key,
                android+'roundIcon':'@drawable/capy_icon_'+key,
                tools+'replace':'android:icon,android:roundIcon'})
        app.set(android+'allowBackup','false')
        app.set(android+'debuggable','false')
        app.set(android+'testOnly','false')
        replacements = [v.strip() for v in app.get(tools+'replace','').split(',') if v.strip()]
        for value in ['android:allowBackup']:
            if value not in replacements: replacements.append(value)
        app.set(tools+'replace',','.join(replacements))
        return '<?xml version="1.0" encoding="utf-8"?>\n'+ET.tostring(doc,encoding='unicode')+'\n'
    raise ValueError('Unexpected candidate file')

def digest(raw): return hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()

def plan(source,check=False):
    root = Path(source).resolve(strict=True)
    hashes = json.loads((ROOT/'candidate-input-hashes.json').read_text())
    if set(hashes['pre']) != set(FILES) or set(hashes['post']) != set(FILES):
        raise ValueError('Candidate file allowlist differs')
    result = {}
    for name in FILES:
        raw = baseline.safe_path(root,name).read_bytes().replace(b'\r\n',b'\n')
        if digest(raw) != hashes['post' if check else 'pre'][name]:
            raise ValueError('Candidate input differs: '+name)
        output = raw if check else transform(name,raw.decode('utf-8')).encode('utf-8')
        if digest(output) != hashes['post'][name]:
            raise ValueError('Candidate output differs: '+name)
        result[name] = output
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    if subprocess.run(['git','-C',str(args.source),'rev-parse','HEAD'],capture_output=True,text=True,check=True,timeout=30).stdout.strip() != baseline.SHA:
        raise ValueError('Unexpected Android revision')
    result = plan(args.source,args.check)
    if not args.check:
        for name,data in result.items(): (args.source/name).write_bytes(data)
    print('PASS: candidate release configuration', 'verified' if args.check else 'prepared')
