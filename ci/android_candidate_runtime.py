# SPDX-License-Identifier: MIT
"""Run one exact release APK on a disposable CI emulator; never enter an account."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_OS')!='Linux':
    raise RuntimeError('This check is restricted to a disposable Linux CI emulator.')
PACKAGE='org.capybaragram'
RUN=37208052043
APK_SHA='55be0b59ed089e5867fdc1ed1e6f8fa0ee3b8673dab5f7da38b491f0234a8c2b'
CERT_SHA='8254ebe4b00d6e4a95ee07dd27a30f8bd95b066b83c72affb39e4d25e7bff282'
sdk=Path(os.environ['ANDROID_HOME'])
scratch=Path(os.environ['RUNNER_TEMP'])/'capy-current-candidate-runtime'
scratch.mkdir(exist_ok=False)
avds=scratch/'avds'; avds.mkdir()
user=scratch/'android-user'; user.mkdir()
report=Path('ci/candidate-runtime-results'); report.mkdir(exist_ok=False)
env=dict(os.environ,ANDROID_AVD_HOME=str(avds),ANDROID_USER_HOME=str(user))
env.pop('ANDROID_SDK_HOME',None)
adb=sdk/'platform-tools/adb'
emulator=sdk/'emulator/emulator'

def run(args,timeout=60,**kwargs):
    return subprocess.run(list(map(str,args)),check=True,timeout=timeout,env=env,**kwargs)
def device(*args,timeout=45):
    return run([adb,'-s','emulator-5554',*args],timeout=timeout,capture_output=True,text=True,encoding='utf-8').stdout
def snapshot(name):
    # Fresh paths avoid accepting a prior hierarchy after a failed stock dump.
    for attempt in range(4):
        remote='/sdcard/capy-current-'+str(time.monotonic_ns())+'.xml'
        response=device('shell','uiautomator','dump',remote)
        if 'ERROR:' in response:
            time.sleep(2)
            continue
        try:
            raw=device('shell','cat',remote)
            tree=ET.fromstring(raw)
        except (subprocess.CalledProcessError,ET.ParseError):
            time.sleep(2)
            continue
        if tree.tag!='hierarchy':
            raise RuntimeError('Unexpected native hierarchy root.')
        png=run([adb,'-s','emulator-5554','exec-out','screencap','-p'],capture_output=True).stdout
        if not png.startswith(b'\x89PNG\r\n\x1a\n'):
            raise RuntimeError('Native capture is not a PNG.')
        (report/(name+'.xml')).write_text(raw,encoding='utf-8')
        (report/(name+'.png')).write_bytes(png)
        return tree
    raise RuntimeError('No fresh native UI hierarchy; no coordinates are reused.')
def own(tree):
    return [n for n in tree.iter('node') if n.get('package')==PACKAGE]
def visible(tree,text):
    return any(n.get('text')==text for n in own(tree))
def action(tree,labels,description=False):
    field='content-desc' if description else 'text'
    choices=[n for n in own(tree) if n.get(field,'').casefold() in {t.casefold() for t in labels} and n.get('enabled')=='true']
    if len(choices)!=1:
        raise RuntimeError('Expected one currently observed native control: '+', '.join(labels))
    bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',choices[0].get('bounds',''))
    if not bounds:
        raise RuntimeError('Observed control has invalid bounds.')
    x1,y1,x2,y2=map(int,bounds.groups())
    if x2<=x1 or y2<=y1:
        raise RuntimeError('Observed control is not visible.')
    device('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))
def open_connection(tree,name):
    action(tree,{'Подключение','Connection'})
    time.sleep(2)
    tree=snapshot(name)
    if not visible(tree,'CapybaraGram · Подключение'):
        raise RuntimeError('Expected native CapybaraGram connection dialog.')
    return tree
def ordinary(tree):
    return any(n.get('text','').startswith('Обычное подключение: напрямую, через VPN') for n in own(tree))
def require_readable_dialog(tree):
    # The old 320dp captures expose a genuinely scrollable message panel, with
    # the account-wide/lifetime paragraph below its initial visible viewport.
    phrase='Режим общий для всех аккаунтов.'
    panels=[n for n in own(tree) if n.get('class','').endswith('ScrollView')
            and any(phrase in c.get('text','') for c in n.iter('node'))]
    if len(panels)!=1 or panels[0].get('scrollable')!='false':
        raise RuntimeError('Connection disclosure still requires scrolling at the tested 320dp width.')

apks=list((Path(os.environ['RUNNER_TEMP'])/'candidate-input').rglob('*.apk'))
if len(apks)!=1 or hashlib.sha256(apks[0].read_bytes()).hexdigest()!=APK_SHA:
    raise RuntimeError('Input is not the exact compiled candidate APK.')
apk=apks[0]
certificate=run([sdk/'build-tools/36.0.0/apksigner','verify','--print-certs',apk],capture_output=True,text=True).stdout
if 'Signer #1 certificate SHA-256 digest: '+CERT_SHA not in certificate:
    raise RuntimeError('APK signer identity differs.')
from collect_android import require_disabled_flag
manifest=run([sdk/'build-tools/36.0.0/aapt','dump','xmltree',apk,'AndroidManifest.xml'],capture_output=True,text=True).stdout
for flag in ('testOnly','debuggable','allowBackup'):
    require_disabled_flag(manifest,flag)
run([sdk/'cmdline-tools/latest/bin/avdmanager','create','avd','--name','capy-current',
     '--package','system-images;android-30;google_apis;x86_64','--path',avds/'capy-current.avd'],input='no\n',text=True)
run([emulator,'-accel-check'])
log=(report/'emulator.log').open('w',encoding='utf-8')
process=subprocess.Popen([str(emulator),'-avd','capy-current','-no-window','-no-audio','-no-boot-anim',
    '-no-snapshot','-gpu','swiftshader_indirect','-memory','2048','-cores','2','-port','5554','-accel','on',
    '-change-locale','ru-RU'],stdout=log,stderr=subprocess.STDOUT,env=env)
result={'apk_run':RUN,'apk_sha256':APK_SHA,'certificate_sha256':CERT_SHA,'install':'PENDING','launch':'PENDING',
    'light_dark_intro':'PENDING','phone_form':'PENDING','connection_dialog':'PENDING','arm64_tunnel_local_start':'PENDING',
    'explicit_route_disable':'PENDING','cold_restart':'PENDING','connection_description_fits':'PENDING','visual_review':'PENDING',
    'real_account_login':False,'real_chat_read_archive_voice_acceptance':False,'provider_vpn_acceptance':False,
    'android_14_capture_hardware_acceptance':False,'physical_arm64_device':False}
try:
    deadline=time.monotonic()+300
    while True:
        if process.poll() is not None:
            raise RuntimeError('Disposable emulator exited before boot.')
        try:
            if device('shell','getprop','sys.boot_completed',timeout=15).strip()=='1' and device('shell','getprop','persist.sys.locale',timeout=15).strip()=='ru-RU':
                break
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
            pass
        if time.monotonic()>deadline:
            raise RuntimeError('Disposable emulator boot timed out.')
        time.sleep(5)
    time.sleep(10)
    result['abi_list']=device('shell','getprop','ro.product.cpu.abilist').strip()
    result['native_bridge']=device('shell','getprop','ro.dalvik.vm.native.bridge').strip()
    result['fingerprint']=device('shell','getprop','ro.build.fingerprint').strip()
    if 'arm64-v8a' not in result['abi_list']:
        raise RuntimeError('This emulator does not advertise ARM64 translation.')
    if 'Success' not in device('install',apk,timeout=150):
        raise RuntimeError('Ordinary APK installation failed.')
    result['install']='PASS'
    component=device('shell','cmd','package','resolve-activity','--brief',PACKAGE).strip().splitlines()[-1]
    if not component.startswith(PACKAGE+'/'):
        raise RuntimeError('No current package launcher activity.')
    device('shell','am','start','-W','-n',component)
    time.sleep(20)
    tree=snapshot('01-intro-light')
    if not visible(tree,'CapybaraGram') or not device('shell','pidof',PACKAGE).strip():
        raise RuntimeError('Release client did not open its observed intro.')
    result['launch']='PASS'
    action(tree,{'switch to night theme','переключить на ночную тему'},description=True)
    time.sleep(5); tree=snapshot('02-intro-dark')
    if not any(n.get('content-desc','').casefold() in {'switch to day theme','переключить на дневную тему'} for n in own(tree)):
        raise RuntimeError('Native theme did not switch to dark.')
    action(tree,{'switch to day theme','переключить на дневную тему'},description=True)
    time.sleep(5); tree=snapshot('03-intro-light-return')
    if not any(n.get('content-desc','').casefold() in {'switch to night theme','переключить на ночную тему'} for n in own(tree)):
        raise RuntimeError('Native theme did not switch back to light.')
    result['light_dark_intro']='PASS (both directions; visual review pending)'
    action(tree,{'start messaging','начать общение'})
    time.sleep(5); tree=snapshot('04-phone-initial')
    for attempt in range(4):
        if any(n.get('class','').endswith('EditText') and n.get('enabled')=='true' for n in own(tree)):
            break
        rationale=any(visible(tree,t) for t in {
            'CapybaraGram может подставить номер телефона с SIM-карты. На следующем экране можно запретить доступ и ввести номер самостоятельно.',
            'CapybaraGram can fill in the phone number from your SIM card. You can deny access on the next screen and enter the number yourself.'})
        if rationale:
            action(tree,{'Continue','Продолжить'})
        else:
            system=[n for n in tree.iter('node') if n.get('package') in {'com.android.permissioncontroller','com.google.android.permissioncontroller'}
                    and n.get('text','').casefold() in {'deny',"don't allow",'запретить','не разрешать'} and n.get('clickable')=='true']
            if len(system)!=1:
                raise RuntimeError('Unexpected phone permission overlay; no input entered.')
            node=system[0]
            # Same observed-control operation, scoped to the permission controller.
            bounds=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
            if not bounds:
                raise RuntimeError('Permission denial control has invalid bounds.')
            x1,y1,x2,y2=map(int,bounds.groups())
            if x2<=x1 or y2<=y1:
                raise RuntimeError('Permission denial control is not visible.')
            device('shell','input','tap',str((x1+x2)//2),str((y1+y2)//2))
        time.sleep(3); tree=snapshot('04-phone-permission-'+str(attempt+1))
    if not any(n.get('class','').endswith('EditText') and n.get('enabled')=='true' for n in own(tree)):
        raise RuntimeError('Native phone entry was not exposed.')
    if any('test backend' in n.get('text','').casefold() for n in own(tree)):
        raise RuntimeError('Release phone form exposed debug backend selection.')
    result['phone_form']='PASS (no phone/code/account entered)'
    tree=open_connection(tree,'05-connection-default')
    if not ordinary(tree):
        raise RuntimeError('Fresh application connection mode was not ordinary.')
    require_readable_dialog(tree)
    result['connection_dialog']='PASS (native prelogin dialog, default ordinary route)'
    action(tree,{'Включить маршрут'})
    time.sleep(12); tree=snapshot('06-route-started-phone')
    tree=open_connection(tree,'07-connection-local-ready')
    if not any(n.get('text','').startswith('Встроенный маршрут запущен.') for n in own(tree)):
        raise RuntimeError('Actual ARM64 native tunnel did not report LOCAL_READY.')
    require_readable_dialog(tree)
    result['arm64_tunnel_local_start']='PASS (actual production APK, translated ARM64 JNI; loopback readiness only)'
    action(tree,{'Обычное подключение'})
    time.sleep(3); tree=snapshot('08-route-disabled-phone')
    tree=open_connection(tree,'09-connection-disabled')
    if not ordinary(tree):
        raise RuntimeError('Explicit ordinary route did not restore native UI state.')
    require_readable_dialog(tree)
    result['connection_description_fits']='PASS (all three initial dialog states non-scrollable at 320dp; account-wide disclosure included)'
    result['explicit_route_disable']='PASS'
    action(tree,{'Отмена','Cancel'})
    device('shell','am','force-stop',PACKAGE)
    device('shell','am','start','-W','-n',component)
    time.sleep(10); tree=snapshot('10-cold-restart')
    if not device('shell','pidof',PACKAGE).strip() or not own(tree):
        raise RuntimeError('Release client exited or lost foreground after restart.')
    crash=device('logcat','-b','crash','-d')
    (report/'crash-buffer.txt').write_text(crash,encoding='utf-8')
    if PACKAGE in crash:
        raise RuntimeError('Current client appeared in Android crash buffer.')
    result['cold_restart']='PASS (accountless application only)'
    print('CAPY_ANDROID_CURRENT_CANDIDATE_RUNTIME=PASS (install, intro themes, phone, ARM64 tunnel start/stop, restart)',flush=True)
finally:
    (report/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    try:
        (report/'crash-buffer.txt').write_text(device('logcat','-b','crash','-d',timeout=15),encoding='utf-8')
        if result['cold_restart']!='PASS (accountless application only)':
            snapshot('failure')
    except (subprocess.CalledProcessError,subprocess.TimeoutExpired,RuntimeError):
        pass
    try:
        device('emu','kill',timeout=20)
    except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
        pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=10)
    log.close()
