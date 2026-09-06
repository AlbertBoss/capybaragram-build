# SPDX-License-Identifier: MIT
"""Exercise native login only on Telegram Test DCs with one disposable reserved test number."""
import hashlib
import secrets
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Linux':
    raise RuntimeError('Sandbox login is restricted to the disposable Linux CI emulator')
LOCALE = os.environ.get('CAPY_TEST_LOCALE','en-US')
if LOCALE != 'en-US': raise ValueError('Sandbox input selectors require the observed English preview UI')
PACKAGE = 'org.capybaragram.preview.beta'
APK_SHA = 'bc368ad62725fc867e819bbe5655cf8133d7cf5027c0d6fd19aa6130df9d35d8'
CERT_SHA = '8254ebe4b00d6e4a95ee07dd27a30f8bd95b066b83c72affb39e4d25e7bff282'
sdk = Path(os.environ['ANDROID_HOME'])
scratch = Path(os.environ['RUNNER_TEMP'])/'capy-client-smoke'
scratch.mkdir(exist_ok=False)
report = Path('ci/sandbox-smoke-results')
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
require_disabled_flag(manifest,'testOnly')
# This exact older Debug preview permits Android backups. It is never used with
# private data here; disable the fresh emulator's backup manager before login.
# Release-candidate smoke retains the separate strict allowBackup=false check.
(report/'preview-manifest-flags.txt').write_text('\n'.join(
    line for line in manifest.splitlines() if any('android:'+flag in line for flag in ('testOnly','debuggable','allowBackup'))
),encoding='utf-8')
run([sdk/'cmdline-tools/latest/bin/avdmanager','create','avd','--name','capy-client',
     '--package','system-images;android-30;google_apis;x86_64','--path',avds/'capy-client.avd'],input='no\n',text=True)
run([emulator,'-accel-check'])
log = (report/'emulator.log').open('w')
process = subprocess.Popen([str(emulator),'-avd','capy-client','-no-window','-no-audio',
    '-no-boot-anim','-no-snapshot','-gpu','swiftshader_indirect','-memory','2048',
    '-cores','2','-port','5554','-accel','on','-change-locale',LOCALE],stdout=log,stderr=subprocess.STDOUT,env=env)
result = {'apk_sha256':APK_SHA,'certificate_sha256':CERT_SHA,'artifact_run':34005401918,
          'package':PACKAGE,'preview_only':True,'test_server_login':'PENDING','test_number_count':1,
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
    device('shell','bmgr','enable','false')
    backup_state = device('shell','bmgr','enabled').strip()
    if 'disabled' not in backup_state.casefold():
        raise RuntimeError('Disposable emulator backup manager did not disable')
    result['emulator_backup_manager'] = backup_state
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

    # This fresh disposable profile never receives a real phone number or user data.
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
                           and n.get('text') in {'Continue','Продолжить'} and n.get('clickable') == 'true'),None)
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

    def own_nodes(tree):
        return [n for n in tree.iter('node') if n.get('package') == PACKAGE]

    def action(tree, label):
        choices = [n for n in own_nodes(tree) if n.get('clickable') == 'true'
                   and label in {n.get('text'), n.get('content-desc')}]
        if len(choices) != 1: raise RuntimeError('Expected one observed action: '+label)
        tap(choices[0])

    def input_field(tree, description, value):
        choices = [n for n in own_nodes(tree) if n.get('class','').endswith('EditText')
                   and n.get('content-desc') == description and n.get('enabled') == 'true']
        if len(choices) != 1 or choices[0].get('text'):
            raise RuntimeError('Expected one empty '+description+' field')
        if not re.fullmatch(r'[0-9A-Za-z]+',value): raise RuntimeError('Only controlled test input is allowed')
        tap(choices[0])
        device('shell','input','text',value)

    def check_server_errors(tree):
        texts = ' '.join(n.get('text','') for n in own_nodes(tree)).casefold()
        if any(label in texts for label in ('too many attempts','flood_wait','phone_number_flood','phone number banned')):
            raise RuntimeError('Telegram reported a rate limit or rejection; stop without retrying or changing numbers')

    # LoginActivity.java at the pinned source toggles ConnectionsManager.switchBackend(false)
    # from this exact checkbox. Require its checked state before entering any number.
    backend = [n for n in own_nodes(hierarchy) if n.get('text') == 'Test Backend' and n.get('checkable') == 'true']
    if len(backend) != 1 or backend[0].get('checked') != 'false':
        raise RuntimeError('Expected an unchecked native test-backend selector on the fresh preview')
    tap(backend[0])
    time.sleep(10)
    hierarchy = snapshot('03-test-backend')
    backend = [n for n in own_nodes(hierarchy) if n.get('text') == 'Test Backend' and n.get('checkable') == 'true']
    if len(backend) != 1 or backend[0].get('checked') != 'true':
        raise RuntimeError('Native test-backend selection was not confirmed; no number entered')
    result['test_backend_selected'] = 'PASS'
    # Official docs reserve 99966XYYYY on Test DCs; use X=2 and one random suffix.
    # No production phone or contact is accepted as an input to this script.
    suffix = f'{secrets.randbelow(10000):04d}'
    test_phone = '999662'+suffix
    input_field(hierarchy,'Country code','999')
    hierarchy = snapshot('04-test-country')
    input_field(hierarchy,'Phone number','662'+suffix)
    hierarchy = snapshot('04-test-number')
    country = next(n for n in own_nodes(hierarchy) if n.get('content-desc') == 'Country code')
    phone = next(n for n in own_nodes(hierarchy) if n.get('content-desc') == 'Phone number')
    displayed = re.sub(r'\D','',country.get('text','')+phone.get('text',''))
    if displayed != test_phone or not re.fullmatch(r'999662[0-9]{4}',displayed):
        raise RuntimeError('Displayed test number differs; no request sent')
    action(hierarchy,'Done')
    time.sleep(3)
    hierarchy = snapshot('05-number-confirmation')
    action(hierarchy,'Yes')
    result['test_code_request'] = 'submitted once on selected Test Backend'
    time.sleep(12)
    hierarchy = snapshot('06-code-response')
    for attempt in range(10):
        check_server_errors(hierarchy)
        code_fields = [n for n in own_nodes(hierarchy) if n.get('class','').endswith('EditText')
                       and n.get('enabled') == 'true']
        # Never enter a code into the phone form, password, email or another flow.
        is_code_screen = any(n.get('text') == 'Phone verification' for n in own_nodes(hierarchy))
        if is_code_screen and code_fields: break
        time.sleep(5)
        hierarchy = snapshot('06-code-wait-'+str(attempt+1))
    if not is_code_screen or not code_fields:
        raise RuntimeError('Expected native test-code input did not appear; inspect server response')
    if any(n.get('text') or n.get('password') == 'true' for n in code_fields):
        raise RuntimeError('Unexpected code input state')
    tap(code_fields[0])
    device('shell','input','text','22222')
    time.sleep(12)
    hierarchy = snapshot('07-after-test-code')
    check_server_errors(hierarchy)
    if not any(n.get('text') == 'Your name' for n in own_nodes(hierarchy)):
        raise RuntimeError('A fresh test signup was not offered; do not inspect an existing test account')
    result['test_code_accepted'] = 'PASS (server advanced to fresh signup)'
    name_fields = [n for n in own_nodes(hierarchy) if n.get('class','').endswith('EditText') and n.get('enabled') == 'true']
    if len(name_fields) != 2 or any(n.get('text') for n in name_fields):
        raise RuntimeError('Expected empty first/last-name fields for fresh test signup')
    own_name = 'CapyCI'+os.environ['GITHUB_RUN_ID'][-6:]
    tap(name_fields[0])
    device('shell','input','text',own_name)
    hierarchy = snapshot('08-test-name')
    if not any(n.get('text') == own_name for n in own_nodes(hierarchy)):
        raise RuntimeError('Native test name input was not retained')
    action(hierarchy,'Done')
    time.sleep(15)
    hierarchy = snapshot('09-after-signup')
    check_server_errors(hierarchy)
    result['signup_submitted'] = True
    # Stop here unless the fresh account's main interface is actually observed.
    navigation = [n for n in own_nodes(hierarchy) if n.get('clickable') == 'true'
                  and n.get('content-desc') in {'Open navigation menu','Open menu'}]
    if len(navigation) != 1:
        raise RuntimeError('Expected authenticated navigation control missing; inspect post-signup state')
    tap(navigation[0])
    time.sleep(3)
    hierarchy = snapshot('10-test-account-menu')
    if not any(n.get('text') == own_name for n in own_nodes(hierarchy)):
        raise RuntimeError('Fresh test account name not visible in account menu')
    result['test_server_login'] = 'PASS (native signup and own account menu observed on Test Backend)'
    result['production_login_tested'] = False
    device('shell','am','force-stop',PACKAGE)
    device('shell','am','start','-W','-n',component)
    time.sleep(12)
    hierarchy = snapshot('11-test-account-restart')
    if any(n.get('text') == 'Start Messaging' for n in own_nodes(hierarchy)):
        raise RuntimeError('Test account was lost after restart')
    navigation = [n for n in own_nodes(hierarchy) if n.get('clickable') == 'true'
                  and n.get('content-desc') in {'Open navigation menu','Open menu'}]
    if len(navigation) != 1: raise RuntimeError('Authenticated navigation missing after restart')
    tap(navigation[0])
    time.sleep(3)
    hierarchy = snapshot('12-restarted-account-menu')
    if not any(n.get('text') == own_name for n in own_nodes(hierarchy)):
        raise RuntimeError('Own test account did not survive restart')
    result['cold_restart'] = 'PASS'
    print('CAPY_ANDROID_SANDBOX_LOGIN=PASS (one fresh reserved Test DC account; no production login)',flush=True)

finally:
    (report/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    # Only disposable Test DC data can exist; never upload preferences, sessions or native debug logs.
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
