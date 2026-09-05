# SPDX-License-Identifier: MIT
"""Compile and execute synthetic native vault checks on an ephemeral Linux runner.
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
out = Path(os.environ['RUNNER_TEMP']) / 'capy-vault-test'
out.mkdir(exist_ok=False)
sdk = Path(os.environ['ANDROID_HOME'])
build = sdk / 'build-tools/36.0.0'
android = sdk / 'platforms/android-36/android.jar'
java = Path(os.environ['JAVA_HOME']) / 'bin'
report = source / 'test-results'
report.mkdir(exist_ok=False)

def run(args, *, timeout=120, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, timeout=timeout, **kwargs)

# Schema bytes are generated mechanically from the shared contract, not invented DDL.
sql = '\n'.join(line for line in (source / '0001.sql').read_text().splitlines()
                if not line.lstrip().startswith('--'))
statements = [s.strip() for s in sql.split(';') if s.strip()]
assert statements[0] == 'BEGIN' and statements[-2:] == ['PRAGMA user_version=1', 'COMMIT']
embedded = re.findall(r'^        (".*")[,]?$', (source / 'VaultSchema.java').read_text(), re.M)
assert [json.loads(s) for s in embedded] == statements[1:-2]
classes = out / 'classes'
dex = out / 'dex'
classes.mkdir()
dex.mkdir()
sources = sorted(source.glob('*.java'))
run([java / 'javac', '-encoding', 'UTF-8', '-source', '8', '-target', '8',
     '-Xlint:all,-options', '-Werror', '-cp', android, '-d', classes, *sources])
run([java / 'java', '-cp', classes, 'org.capybaragram.local.PayloadCipherTest'])
run([build / 'd8', '--min-api', '23', '--lib', android, '--output', dex,
     *sorted(classes.rglob('*.class'))])
unsigned = out / 'unsigned.apk'
run([build / 'aapt2', 'link', '-I', android, '--manifest', source / 'AndroidManifest.xml',
     '-o', unsigned])
with zipfile.ZipFile(unsigned, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(dex.glob('classes*.dex')):
        archive.write(file, file.name)
aligned = out / 'aligned.apk'
run([build / 'zipalign', '-f', '4', unsigned, aligned])
keystore = out / 'synthetic-test.p12'
# Disposable test-only key, not the preview/release key and never uploaded.
run([java / 'keytool', '-genkeypair', '-keystore', keystore, '-storetype', 'PKCS12',
     '-storepass', 'androidtest', '-keypass', 'androidtest', '-alias', 'test',
     '-keyalg', 'RSA', '-keysize', '2048', '-validity', '2', '-dname', 'CN=Synthetic Vault Test'])
apk = out / 'vault-test.apk'
run([build / 'apksigner', 'sign', '--ks', keystore, '--ks-pass', 'pass:androidtest',
     '--out', apk, aligned])
run([build / 'apksigner', 'verify', apk])

manager = sdk / 'cmdline-tools/latest/bin/avdmanager'
run([manager, 'create', 'avd', '--name', 'capy-vault', '--package',
     'system-images;android-30;google_apis;x86_64', '--force'], input='no\n', text=True)
adb = sdk / 'platform-tools/adb'
emulator = sdk / 'emulator/emulator'
run([emulator, '-accel-check'])
log = (report / 'emulator.log').open('w')
process = subprocess.Popen([str(emulator), '-avd', 'capy-vault', '-no-window',
    '-no-audio', '-no-boot-anim', '-no-snapshot', '-gpu', 'swiftshader_indirect',
    '-memory', '2048', '-cores', '2', '-port', '5554', '-accel', 'on'],
    stdout=log, stderr=subprocess.STDOUT)
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
        'org.capybaragram.vaulttest/org.capybaragram.local.AndroidVaultDeviceInstrumentation'],
        capture_output=True, text=True, timeout=180)
    (report / 'instrumentation.txt').write_text(result.stdout + result.stderr)
    print(result.stdout, flush=True)
    if 'CAPY_VAULT_TESTS=PASS' not in result.stdout or 'INSTRUMENTATION_CODE: -1' not in result.stdout:
        raise RuntimeError('Native vault checks did not pass')
    runtime = run([adb, '-s', 'emulator-5554', 'shell', 'getprop', 'ro.build.fingerprint'],
                  capture_output=True, text=True).stdout.strip()
    (report / 'verification.json').write_text(json.dumps({'runtime': runtime,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'test_apk_sha256': hashlib.sha256(apk.read_bytes()).hexdigest(),
        'native_keystore_sqlite_tests': 'PASS', 'telegram_client_integration_tested': False,
        'hardware_backed_keystore_claimed': False}, indent=2))
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
