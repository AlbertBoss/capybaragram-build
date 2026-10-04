# SPDX-License-Identifier: MIT
"""Execute actual Android loopback transport and production JNI on an ephemeral Linux runner.
No Telegram login/API keys, production signing credentials or third-party actions.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import zipfile

source = Path(__file__).resolve().parent
out = Path(os.environ['RUNNER_TEMP']) / 'capy-connection-device-test'
out.mkdir(exist_ok=False)
sdk = Path(os.environ['ANDROID_HOME'])
build = sdk / 'build-tools/36.0.0'
android = sdk / 'platforms/android-36/android.jar'
java = Path(os.environ['JAVA_HOME']) / 'bin'
report = source / 'runtime-results'
report.mkdir(exist_ok=False)
avd_home = out / 'avd'
android_user = out / 'android-user'
avd_home.mkdir()
android_user.mkdir()
tool_env = dict(os.environ, ANDROID_AVD_HOME=str(avd_home), ANDROID_USER_HOME=str(android_user))
tool_env.pop('ANDROID_SDK_HOME', None)

def run(args, *, timeout=120, **kwargs):
    kwargs.setdefault('env', tool_env)
    return subprocess.run(list(map(str, args)), check=True, timeout=timeout, **kwargs)

classes = out / 'classes'
dex = out / 'dex'
classes.mkdir()
dex.mkdir()
sources = [source / n for n in ('NativeTunnel.java', 'AndroidConnectionDeviceInstrumentation.java')]
compiled = Path(os.environ['RUNNER_TEMP']) / 'capy-android-connection'
libraries = list((compiled / 'jni-x86_64').rglob('libcapy_connection_jni.so'))
if len(libraries) != 1:
    raise RuntimeError('Expected exactly one compiled x86_64 JNI library')
library = libraries[0].read_bytes()
if library[:6] != b'\x7fELF\x02\x01' or int.from_bytes(library[18:20], 'little') != 62:
    raise RuntimeError('Test JNI must target x86_64')
native_report=json.loads((source/'test-results/verification.json').read_text())
if native_report['result']!='PASS' or hashlib.sha256(library).hexdigest()!=native_report['android_libraries']['x86_64']['sha256']:
    raise RuntimeError('Compiled JNI does not match the frozen native verification')
manifest = (source / 'AndroidManifest-runtime.xml').read_text()
if re.findall(r'<uses-permission android:name="([^"]+)"',manifest)!=['android.permission.INTERNET'] or 'sharedUserId' in manifest:
    raise RuntimeError('Test may request loopback socket permission only')
run([java / 'javac', '-encoding', 'UTF-8', '-source', '8', '-target', '8',
     '-Xlint:all,-options', '-Werror', '-cp', android, '-d', classes, *sources])
run([build / 'd8', '--min-api', '23', '--lib', android, '--output', dex,
     *sorted(classes.rglob('*.class'))])
unsigned = out / 'unsigned.apk'
run([build / 'aapt2', 'link', '-I', android, '--manifest', source / 'AndroidManifest-runtime.xml',
     '-o', unsigned])
with zipfile.ZipFile(unsigned, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(dex.glob('classes*.dex')):
        archive.write(file, file.name)
    archive.writestr('lib/x86_64/libcapy_connection_jni.so', library)

aligned = out / 'aligned.apk'
run([build / 'zipalign', '-f', '4', unsigned, aligned])
keystore = out / 'synthetic-test.p12'
# Disposable test-only key, not the preview/release key and never uploaded.
run([java / 'keytool', '-genkeypair', '-keystore', keystore, '-storetype', 'PKCS12',
     '-storepass', 'androidtest', '-keypass', 'androidtest', '-alias', 'test',
     '-keyalg', 'RSA', '-keysize', '2048', '-validity', '2', '-dname', 'CN=Synthetic Connection Test'])
apk = out / 'connection-test.apk'
run([build / 'apksigner', 'sign', '--ks', keystore, '--ks-pass', 'pass:androidtest',
     '--out', apk, aligned])
run([build / 'apksigner', 'verify', apk])

manager = sdk / 'cmdline-tools/latest/bin/avdmanager'
run([manager, 'create', 'avd', '--name', 'capy-connection-device', '--package',
     'system-images;android-30;google_apis;x86_64', '--path', avd_home / 'capy-connection-device.avd',
     '--force'], input='no\n', text=True)
adb = sdk / 'platform-tools/adb'
emulator = sdk / 'emulator/emulator'
if not (avd_home / 'capy-connection-device.ini').is_file():
    raise RuntimeError('AVD manager did not create the expected explicit AVD registration')
available = run([emulator, '-list-avds'], capture_output=True, text=True).stdout.splitlines()
if 'capy-connection-device' not in available:
    raise RuntimeError('Emulator cannot see the created AVD in the shared explicit location')
run([emulator, '-accel-check'])
log = (report / 'emulator.log').open('w')
process = subprocess.Popen([str(emulator), '-avd', 'capy-connection-device', '-no-window',
    '-no-audio', '-no-boot-anim', '-no-snapshot', '-gpu', 'swiftshader_indirect',
    '-memory', '2048', '-cores', '2', '-port', '5554', '-accel', 'on'],
    stdout=log, stderr=subprocess.STDOUT, env=tool_env)
try:
    deadline = time.monotonic() + 300
    booted = False
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Emulator exited before boot; see emulator.log')
        try:
            result = subprocess.run([str(adb), '-s', 'emulator-5554', 'shell',
                'getprop', 'sys.boot_completed'], capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip() == '1':
                booted = True
                break
        except subprocess.TimeoutExpired:
            pass
        time.sleep(5)
    if not booted:
        raise RuntimeError('Emulator boot deadline exceeded')
    run([adb, '-s', 'emulator-5554', 'install', apk])
    result = run([adb, '-s', 'emulator-5554', 'shell', 'am', 'instrument', '-w', '-r',
        'org.capybaragram.connectiontest/org.capybaragram.connection.AndroidConnectionDeviceInstrumentation'],
        capture_output=True, text=True, timeout=180)
    (report / 'instrumentation.txt').write_text(result.stdout + result.stderr)
    print(result.stdout, flush=True)
    if 'CAPY_ANDROID_CONNECTION_JNI=PASS' not in result.stdout or 'INSTRUMENTATION_CODE: -1' not in result.stdout:
        raise RuntimeError('Native connection JNI checks did not pass')
    runtime = run([adb, '-s', 'emulator-5554', 'shell', 'getprop', 'ro.build.fingerprint'],
                  capture_output=True, text=True).stdout.strip()
    (report / 'verification.json').write_text(json.dumps({'runtime':runtime,
        'result':'PASS', 'source_sha256':{p.name:hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in sources},
        'manifest_sha256':hashlib.sha256((source/'AndroidManifest-runtime.xml').read_bytes()).hexdigest(),
        'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'test_apk_sha256':hashlib.sha256(apk.read_bytes()).hexdigest(),
        'jni_sha256':hashlib.sha256(library).hexdigest(),
        'assertions':int(re.search(r'CAPY_ANDROID_CONNECTION_JNI=PASS (\d+) assertions',result.stdout).group(1)),
        'native_lock_sha256':native_report['cargo_lock_sha256'],
        'test_apk_internet_permission':True,'outbound_telegram_connection_tested':False,
        'telegram_client_integration_tested':False,'production_arm64_execution_tested':False,
        'account_keys_used':False,'vpn_transition_tested':False},indent=2)+'\n',encoding='utf-8')

finally:
    try:
        subprocess.run([str(adb), '-s', 'emulator-5554', 'emu', 'kill'],
                       capture_output=True, timeout=20)
    except subprocess.TimeoutExpired:
        pass
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    log.close()
