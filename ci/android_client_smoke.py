# SPDX-License-Identifier: MIT
"""Install the exact reviewed APK on a disposable emulator, with no Telegram login."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

PACKAGE = 'org.capybaragram.preview.beta'
APK_SHA = 'e210b6033eb578d9cfbfce28b793c69861b466ff5de133b2aa51c26876134ec1'
CERT_SHA = '8254ebe4b00d6e4a95ee07dd27a30f8bd95b066b83c72affb39e4d25e7bff282'
sdk = Path(os.environ['ANDROID_HOME'])
scratch = Path(os.environ['RUNNER_TEMP'])/'capy-client-smoke'
scratch.mkdir(exist_ok=False)
report = Path('ci/client-smoke-results')
report.mkdir(exist_ok=False)
avds = scratch/'avd'
user = scratch/'android-user'
avds.mkdir()
user.mkdir()
env = dict(os.environ, ANDROID_AVD_HOME=str(avds), ANDROID_USER_HOME=str(user))
env.pop('ANDROID_SDK_HOME',None)
adb = sdk/'platform-tools/adb'
emulator = sdk/'emulator/emulator'

def run(args, timeout=90, **kwargs):
    return subprocess.run(list(map(str,args)), check=True, timeout=timeout, env=env, **kwargs)

def device(*args, timeout=60):
    return run([adb,'-s','emulator-5554',*args],timeout=timeout,capture_output=True,text=True).stdout

def snapshot(name):
    run([adb,'-s','emulator-5554','shell','uiautomator','dump','/sdcard/capy-ui.xml'],capture_output=True,timeout=45)
    xml = device('shell','cat','/sdcard/capy-ui.xml')
    (report/(name+'.xml')).write_text(xml,encoding='utf-8')
    png = run([adb,'-s','emulator-5554','exec-out','screencap','-p'],capture_output=True).stdout
    if not png.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('Screenshot was not a PNG')
    (report/(name+'.png')).write_bytes(png)
    return ET.fromstring(xml)

apks = list((Path(os.environ['RUNNER_TEMP'])/'client-input').rglob('*.apk'))
if len(apks) != 1 or hashlib.sha256(apks[0].read_bytes()).hexdigest() != APK_SHA:
    raise RuntimeError('Artifact is not the exact reviewed Android notes APK')
apk = apks[0]
certificate = run([sdk/'build-tools/36.0.0/apksigner','verify','--print-certs',apk],capture_output=True,text=True).stdout
if f'Signer #1 certificate SHA-256 digest: {CERT_SHA}' not in certificate:
    raise RuntimeError('APK signing identity differs')
run([sdk/'cmdline-tools/latest/bin/avdmanager','create','avd','--name','capy-client',
     '--package','system-images;android-30;google_apis;x86_64','--path',avds/'capy-client.avd'],input='no\n',text=True)
run([emulator,'-accel-check'])
log = (report/'emulator.log').open('w')
process = subprocess.Popen([str(emulator),'-avd','capy-client','-no-window','-no-audio',
    '-no-boot-anim','-no-snapshot','-gpu','swiftshader_indirect','-memory','2048',
    '-cores','2','-port','5554','-accel','on'],stdout=log,stderr=subprocess.STDOUT,env=env)
result = {'apk_sha256':APK_SHA,'certificate_sha256':CERT_SHA,'artifact_run':33983323983,
          'real_account_login_tested':False,'notes_ui_tested':False,'visual_review':'PENDING',
          'install':'PENDING','launch':'PENDING','login_screen':'PENDING','cold_restart':'PENDING'}
try:
    deadline = time.monotonic()+300
    while True:
        if process.poll() is not None:
            raise RuntimeError('Emulator stopped before boot')
        try:
            if device('shell','getprop','sys.boot_completed',timeout=15).strip() == '1': break
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
            pass
        if time.monotonic() > deadline: raise RuntimeError('Emulator boot timed out')
        time.sleep(5)
    result['fingerprint'] = device('shell','getprop','ro.build.fingerprint').strip()
    result['abi_list'] = device('shell','getprop','ro.product.cpu.abilist').strip()
    result['native_bridge'] = device('shell','getprop','ro.dalvik.vm.native.bridge').strip()
    if 'arm64-v8a' not in result['abi_list']:
        raise RuntimeError('This emulator image does not advertise ARM64 compatibility')
    install = device('install',str(apk),timeout=150)
    (report/'install.txt').write_text(install)
    if 'Success' not in install: raise RuntimeError('APK installation did not succeed')
    result['install'] = 'PASS'
    component = device('shell','cmd','package','resolve-activity','--brief',PACKAGE).strip().splitlines()[-1]
    if not component.startswith(PACKAGE+'/'): raise RuntimeError('No package launcher activity')
    launch = device('shell','am','start','-W','-n',component)
    (report/'launch.txt').write_text(launch)
    if 'Status: ok' not in launch: raise RuntimeError('Launcher did not report success')
    time.sleep(20)
    if not device('shell','pidof',PACKAGE).strip(): raise RuntimeError('Client exited after launch')
    hierarchy = snapshot('01-onboarding')
    if not any(n.get('package') == PACKAGE for n in hierarchy.iter('node')):
        raise RuntimeError('Client UI is not foreground')
    result['launch'] = 'PASS'
    # Only tap a label observed in the actual hierarchy. Never enter a phone,
    # request a login code, grant contacts, or send a Telegram message.
    start = next((n for n in hierarchy.iter('node') if n.get('package') == PACKAGE
                  and n.get('text','').strip().casefold() in {'start messaging','начать общение'}),None)
    if start is None: raise RuntimeError('Expected onboarding action was not exposed')
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',start.get('bounds',''))
    if not match: raise RuntimeError('Onboarding action has no valid bounds')
    x1,y1,x2,y2 = map(int,match.groups())
    if x2 <= x1 or y2 <= y1: raise RuntimeError('Onboarding action is not visible')
    device('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))
    time.sleep(5)
    hierarchy = snapshot('02-login')
    fields = [n for n in hierarchy.iter('node') if n.get('package') == PACKAGE
              and n.get('class','').endswith('EditText') and n.get('enabled') == 'true']
    if not fields: raise RuntimeError('Phone entry fields were not exposed; inspect screenshot')
    result['login_screen'] = 'PASS (entry fields only; no phone entered)'
    device('shell','am','force-stop',PACKAGE)
    device('shell','am','start','-W','-n',component)
    time.sleep(10)
    if not device('shell','pidof',PACKAGE).strip(): raise RuntimeError('Client exited after cold restart')
    hierarchy = snapshot('03-cold-restart')
    if not any(n.get('package') == PACKAGE for n in hierarchy.iter('node')):
        raise RuntimeError('Client UI not foreground after restart')
    crash = device('logcat','-b','crash','-d')
    (report/'crash-buffer.txt').write_text(crash,encoding='utf-8')
    if PACKAGE in crash: raise RuntimeError('Client appeared in the crash buffer')
    result['cold_restart'] = 'PASS'
    print('CAPY_ANDROID_CLIENT_SMOKE=PASS (fresh install, onboarding, phone entry, cold restart)',flush=True)
finally:
    (report/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    try: device('emu','kill',timeout=20)
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError): pass
    if process.poll() is None:
        process.terminate()
        try: process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    log.close()
