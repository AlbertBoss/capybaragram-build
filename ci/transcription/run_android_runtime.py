# SPDX-License-Identifier: MIT
"""Execute actual Android codecs and pinned speech JNI on an ephemeral Linux runner.
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
out = Path(os.environ['RUNNER_TEMP']) / 'capy-speech-test'
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
sources = [source / n for n in ('OfflineSpeech.java', 'AndroidPcmDecoder.java', 'AndroidSpeechDeviceInstrumentation.java')]
compiled = Path(os.environ['RUNNER_TEMP']) / 'capy-speech-native'
libraries = list((compiled / 'build').rglob('libcapy_voice_jni.so'))
if len(libraries) != 1:
    raise RuntimeError('Expected exactly one compiled x86_64 JNI library')
library = libraries[0].read_bytes()
if library[:6] != b'\x7fELF\x02\x01' or int.from_bytes(library[18:20], 'little') != 62:
    raise RuntimeError('Test JNI must target x86_64')
pins = json.loads((source / 'source-pins.json').read_text())
model = out / 'tiny.bin'
m = pins['model']
import urllib.request
with urllib.request.urlopen('https://huggingface.co/' + m['repository'] + '/resolve/' + m['revision'] + '/' + m['file'], timeout=90) as response, model.open('xb') as target:
    digest = hashlib.sha256()
    count = 0
    while True:
        chunk = response.read(1048576)
        if not chunk:
            break
        count += len(chunk)
        if count > m['bytes']:
            raise RuntimeError('Test model exceeds pinned size')
        digest.update(chunk)
        target.write(chunk)
if count != m['bytes'] or digest.hexdigest() != m['sha256']:
    raise RuntimeError('Test model identity mismatch')
fixtures = {}
for name, options in [('speech.ogg', ['-ar', '48000', '-ac', '1', '-c:a', 'libopus', '-b:a', '24k']),
                      ('speech.m4a', ['-ar', '44100', '-ac', '2', '-c:a', 'aac', '-b:a', '64k'])]:
    file = out / name
    run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', compiled / 'whisper/samples/jfk.wav',
         '-map', '0:a:0', '-vn', '-map_metadata', '-1', *options, file])
    fixtures[name] = {'path': file, 'bytes': file.stat().st_size, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
    if not 0 < file.stat().st_size < 1048576:
        raise RuntimeError('Unexpected synthetic speech fixture size')
manifest = (source / 'AndroidManifest-runtime.xml').read_text()
if '<uses-permission' in manifest or 'sharedUserId' in manifest:
    raise RuntimeError('Speech test must not request network or shared identity')
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
    archive.writestr('lib/x86_64/libcapy_voice_jni.so', library)
    archive.write(model, 'assets/tiny.bin')
    for name, fixture in fixtures.items():
        archive.write(fixture['path'], 'assets/' + name)

aligned = out / 'aligned.apk'
run([build / 'zipalign', '-f', '4', unsigned, aligned])
keystore = out / 'synthetic-test.p12'
# Disposable test-only key, not the preview/release key and never uploaded.
run([java / 'keytool', '-genkeypair', '-keystore', keystore, '-storetype', 'PKCS12',
     '-storepass', 'androidtest', '-keypass', 'androidtest', '-alias', 'test',
     '-keyalg', 'RSA', '-keysize', '2048', '-validity', '2', '-dname', 'CN=Synthetic Speech Test'])
apk = out / 'speech-test.apk'
run([build / 'apksigner', 'sign', '--ks', keystore, '--ks-pass', 'pass:androidtest',
     '--out', apk, aligned])
run([build / 'apksigner', 'verify', apk])

manager = sdk / 'cmdline-tools/latest/bin/avdmanager'
run([manager, 'create', 'avd', '--name', 'capy-speech', '--package',
     'system-images;android-30;google_apis;x86_64', '--path', avd_home / 'capy-speech.avd',
     '--force'], input='no\n', text=True)
adb = sdk / 'platform-tools/adb'
emulator = sdk / 'emulator/emulator'
if not (avd_home / 'capy-speech.ini').is_file():
    raise RuntimeError('AVD manager did not create the expected explicit AVD registration')
available = run([emulator, '-list-avds'], capture_output=True, text=True).stdout.splitlines()
if 'capy-speech' not in available:
    raise RuntimeError('Emulator cannot see the created AVD in the shared explicit location')
run([emulator, '-accel-check'])
log = (report / 'emulator.log').open('w')
process = subprocess.Popen([str(emulator), '-avd', 'capy-speech', '-no-window',
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
        '-e', 'model_sha', m['sha256'],
        '-e', 'opus_sha', fixtures['speech.ogg']['sha256'], '-e', 'opus_size', str(fixtures['speech.ogg']['bytes']),
        '-e', 'aac_sha', fixtures['speech.m4a']['sha256'], '-e', 'aac_size', str(fixtures['speech.m4a']['bytes']),
        'org.capybaragram.speechtest/org.capybaragram.voice.AndroidSpeechDeviceInstrumentation'],
        capture_output=True, text=True, timeout=300)
    (report / 'instrumentation.txt').write_text(result.stdout + result.stderr)
    print(result.stdout, flush=True)
    if 'CAPY_ANDROID_SPEECH=PASS' not in result.stdout or 'INSTRUMENTATION_CODE: -1' not in result.stdout:
        raise RuntimeError('Native speech checks did not pass')
    runtime = run([adb, '-s', 'emulator-5554', 'shell', 'getprop', 'ro.build.fingerprint'],
                  capture_output=True, text=True).stdout.strip()
    (report / 'verification.json').write_text(json.dumps({'runtime': runtime,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'test_apk_sha256': hashlib.sha256(apk.read_bytes()).hexdigest(),
        'opus_decode_and_actual_jni_recognition': 'PASS', 'stereo_aac_resampling': 'PASS',
        'test_apk_internet_permission': False, 'telegram_client_integration_tested': False,
        'production_arm64_execution_tested': False, 'russian_voice_accuracy_tested': False,
        'model': m, 'jni_sha256': hashlib.sha256(library).hexdigest(),
        'fixtures': {name: {k: v for k, v in data.items() if k != 'path'} for name, data in fixtures.items()}}, indent=2))
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
