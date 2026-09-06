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

LOCALE = os.environ.get('CAPY_TEST_LOCALE','en-US')
if LOCALE not in {'en-US','ru-RU'}: raise ValueError('Unsupported test locale')
PACKAGE = 'org.capybaragram'
APK_SHA = 'fe2d4504c9772ad1c0e83438fa5fe5591dce94542aa0dabcc4e2255b9ea821d4'
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
    try:
        return run([adb,'-s','emulator-5554',*args],timeout=timeout,capture_output=True,text=True).stdout
    except subprocess.CalledProcessError as failure:
        with (report/'adb-failure.txt').open('a',encoding='utf-8') as log:
            log.write('operation='+str(args[0])+'\n'+(failure.stdout or '')+(failure.stderr or '')+'\n')
        raise

def snapshot(name):
    run([adb,'-s','emulator-5554','shell','uiautomator','dump','/sdcard/capy-ui.xml'],capture_output=True,timeout=45)
    xml = device('shell','cat','/sdcard/capy-ui.xml')
    (report/(name+'.xml')).write_text(xml,encoding='utf-8')
    png = run([adb,'-s','emulator-5554','exec-out','screencap','-p'],capture_output=True).stdout
    if not png.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('Screenshot was not a PNG')
    (report/(name+'.png')).write_bytes(png)
    return ET.fromstring(xml)

def tap(node):
    match = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
    if not match: raise RuntimeError('Observed action has no valid bounds')
    x1,y1,x2,y2 = map(int,match.groups())
    if x2 <= x1 or y2 <= y1: raise RuntimeError('Observed action is not visible')
    device('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))

apks = list((Path(os.environ['RUNNER_TEMP'])/'client-input').rglob('*.apk'))
if len(apks) != 1 or hashlib.sha256(apks[0].read_bytes()).hexdigest() != APK_SHA:
    raise RuntimeError('Artifact is not the exact reviewed Android notes APK')
apk = apks[0]
certificate = run([sdk/'build-tools/36.0.0/apksigner','verify','--print-certs',apk],capture_output=True,text=True).stdout
if f'Signer #1 certificate SHA-256 digest: {CERT_SHA}' not in certificate:
    raise RuntimeError('APK signing identity differs')
from collect_android import require_disabled_flag
manifest = run([sdk/'build-tools/36.0.0/aapt','dump','xmltree',apk,'AndroidManifest.xml'],capture_output=True,text=True).stdout
for flag in ('testOnly','debuggable','allowBackup'):
    require_disabled_flag(manifest,flag)
run([sdk/'cmdline-tools/latest/bin/avdmanager','create','avd','--name','capy-client',
     '--package','system-images;android-30;google_apis;x86_64','--path',avds/'capy-client.avd'],input='no\n',text=True)
run([emulator,'-accel-check'])
log = (report/'emulator.log').open('w')
process = subprocess.Popen([str(emulator),'-avd','capy-client','-no-window','-no-audio',
    '-no-boot-anim','-no-snapshot','-gpu','swiftshader_indirect','-memory','2048',
    '-cores','2','-port','5554','-accel','on','-change-locale',LOCALE],stdout=log,stderr=subprocess.STDOUT,env=env)
result = {'apk_sha256':APK_SHA,'certificate_sha256':CERT_SHA,'artifact_run':34007280482,
          'package':PACKAGE,'release_manifest_flags':'PASS (testOnly/debuggable/allowBackup disabled)',
          'real_account_login_tested':False,'notes_ui_tested':False,'visual_review':'PENDING',
          'install':'PENDING','launch':'PENDING','login_screen':'PENDING','cold_restart':'PENDING'}
try:
    deadline = time.monotonic()+300
    while True:
        if process.poll() is not None:
            raise RuntimeError('Emulator stopped before boot')
        try:
            if (device('shell','getprop','sys.boot_completed',timeout=15).strip() == '1'
                and device('shell','getprop','persist.sys.locale',timeout=15).strip() == LOCALE): break
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
            pass
        if time.monotonic() > deadline: raise RuntimeError('Emulator boot timed out')
        time.sleep(5)
    time.sleep(10)  # Locale selection restarts the disposable emulator framework.
    result['locale'] = device('shell','getprop','persist.sys.locale').strip()
    result['fingerprint'] = device('shell','getprop','ro.build.fingerprint').strip()
    result['abi_list'] = device('shell','getprop','ro.product.cpu.abilist').strip()
    result['native_bridge'] = device('shell','getprop','ro.dalvik.vm.native.bridge').strip()
    if 'arm64-v8a' not in result['abi_list']:
        raise RuntimeError('This emulator image does not advertise ARM64 compatibility')
    # Ordinary installation is required: no test-only installation override.
    result['test_only_apk'] = False
    install = device('install',str(apk),timeout=150)
    (report/'install.txt').write_text(install)
    if 'Success' not in install: raise RuntimeError('APK installation did not succeed')
    result['install'] = 'PASS'
    component = device('shell','cmd','package','resolve-activity','--brief',PACKAGE).strip().splitlines()[-1]
    if not component.startswith(PACKAGE+'/'): raise RuntimeError('No package launcher activity')
    launch = device('shell','am','start','-W','-n',component)
    (report/'launch.txt').write_text(launch)
    # am's own first-frame wait can time out under ARM translation. It is not
    # sufficient evidence that the app exited: verify process and actual UI next.
    if 'Status: ok' not in launch and 'Status: timeout' not in launch:
        raise RuntimeError('Launcher rejected the activity start')
    time.sleep(20)
    if not device('shell','pidof',PACKAGE).strip(): raise RuntimeError('Client exited after launch')
    hierarchy = snapshot('01-onboarding')
    if not any(n.get('package') == PACKAGE for n in hierarchy.iter('node')):
        raise RuntimeError('Client UI is not foreground')
    result['launch'] = 'PASS'

    def require_title(tree, title):
        if not any(n.get('package') == PACKAGE and n.get('text') == title for n in tree.iter('node')):
            raise RuntimeError('Expected visible intro page: '+title)

    def change_theme(tree, current_description, next_description, snapshot_name):
        node = next((n for n in tree.iter('node') if n.get('package') == PACKAGE
                     and n.get('content-desc','').casefold() == current_description),None)
        if node is None: raise RuntimeError('Observed theme toggle is missing')
        tap(node)
        time.sleep(5)
        tree = snapshot(snapshot_name)
        if not any(n.get('content-desc','').casefold() == next_description for n in tree.iter('node')):
            raise RuntimeError('Theme toggle did not change state')
        require_title(tree,'CapybaraGram')
        return tree

    def swipe_page(tree, forward=True):
        pager = next((n for n in tree.iter('node') if n.get('package') == PACKAGE
                      and n.get('class','').endswith('.ViewPager')),None)
        if pager is None: raise RuntimeError('Observed intro pager is missing')
        bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',pager.get('bounds',''))
        if not bounds: raise RuntimeError('Intro pager has invalid bounds')
        x1,y1,x2,y2 = map(int,bounds.groups())
        left,right = x1+(x2-x1)//6,x2-(x2-x1)//6
        y = y1+(y2-y1)//2
        start,end = (right,left) if forward else (left,right)
        device('shell','input','swipe',str(start),str(y),str(end),str(y),'350')
        time.sleep(2)

    require_title(hierarchy,'CapybaraGram')
    hierarchy = change_theme(hierarchy,'switch to night theme','switch to day theme','01-theme-dark')
    hierarchy = change_theme(hierarchy,'switch to day theme','switch to night theme','01-theme-light')
    result['theme_switch'] = 'PASS (both directions; visual review pending)'
    titles = (['CapybaraGram','Всё под рукой','Ответ без спешки','Каждому своё','Знакомые папки','Как вам удобно']
              if LOCALE == 'ru-RU' else ['CapybaraGram','Keep the context','Prepare your reply','Separate accounts','Familiar folders','Make it yours'])
    result['intro_pages'] = [titles[0]]
    for index,title in enumerate(titles[1:],2):
        swipe_page(hierarchy)
        hierarchy = snapshot('01-page-'+str(index))
        require_title(hierarchy,title)
        result['intro_pages'].append(title)
    for _ in range(5):
        swipe_page(hierarchy,False)
    hierarchy = snapshot('01-return-first')
    require_title(hierarchy,'CapybaraGram')
    result['intro_return'] = 'PASS'
    # Only tap a label observed in the actual hierarchy. Never enter a phone,
    # request a login code, grant contacts, or send a Telegram message.
    start = next((n for n in hierarchy.iter('node') if n.get('package') == PACKAGE
                  and n.get('text','').strip().casefold() in {'start messaging','начать общение'}),None)
    if start is None: raise RuntimeError('Expected onboarding action was not exposed')
    tap(start)
    time.sleep(5)
    hierarchy = snapshot('02-login')
    result['phone_permission_denials'] = 0
    for attempt in range(4):
        fields = [n for n in hierarchy.iter('node') if n.get('package') == PACKAGE
                  and n.get('class','').endswith('EditText') and n.get('enabled') == 'true']
        if fields: break
        # Source LoginActivity.fillNumber and the captured first-run UI show a
        # rationale before Android's phone permission. Continue only that exact
        # rationale; always deny the system permission. No auto-filled SIM number.
        rationale = any(n.get('text') == 'Please allow Telegram to receive calls so that we can automatically confirm your phone number.'
                        and n.get('package') == PACKAGE for n in hierarchy.iter('node'))
        action = None
        if rationale:
            action = next((n for n in hierarchy.iter('node') if n.get('package') == PACKAGE
                           and n.get('text') == 'Continue' and n.get('clickable') == 'true'),None)
        else:
            action = next((n for n in hierarchy.iter('node')
                           if n.get('package') in {'com.android.permissioncontroller','com.google.android.permissioncontroller'}
                           and n.get('text','').casefold() in {'deny',"don't allow",'запретить','не разрешать'}
                           and n.get('clickable') == 'true'),None)
            if action is not None: result['phone_permission_denials'] += 1
        if action is None: raise RuntimeError('Unexpected overlay blocks phone entry; inspect screenshot')
        tap(action)
        time.sleep(3)
        hierarchy = snapshot('02-login-permission-'+str(attempt+1))
    fields = [n for n in hierarchy.iter('node') if n.get('package') == PACKAGE
              and n.get('class','').endswith('EditText') and n.get('enabled') == 'true']
    if not fields: raise RuntimeError('Phone entry fields were not exposed; inspect screenshot')
    if any('test backend' in n.get('text','').casefold() for n in hierarchy.iter('node')):
        raise RuntimeError('Release login must not expose the debug test backend option')
    result['debug_backend_option_absent'] = 'PASS (visible phone form)'
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
    # Capture failure evidence before emulator shutdown. No account is logged in.
    for name,args in [('crash-buffer.txt',('logcat','-b','crash','-d')),
                      ('activity-state.txt',('shell','dumpsys','activity','activities'))]:
        try: (report/name).write_text(device(*args,timeout=15),encoding='utf-8')
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError): pass
    if result['cold_restart'] != 'PASS':
        try: snapshot('failure')
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError,RuntimeError,ET.ParseError): pass
    try: device('emu','kill',timeout=20)
    except (subprocess.TimeoutExpired,subprocess.CalledProcessError): pass
    if process.poll() is None:
        process.terminate()
        try: process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    log.close()
