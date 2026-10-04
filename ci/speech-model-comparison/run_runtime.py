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

comparison = Path(__file__).resolve().parent
source = comparison.parent / 'speech-ru'
production = source.parent / 'transcription'
if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != 'Linux':
    raise RuntimeError('Restricted to the disposable Linux CI emulator.')
APK_RUN = 37208052043
APK_SHA = '55be0b59ed089e5867fdc1ed1e6f8fa0ee3b8673dab5f7da38b491f0234a8c2b'
CERT_SHA = '8254ebe4b00d6e4a95ee07dd27a30f8bd95b066b83c72affb39e4d25e7bff282'
out = Path(os.environ['RUNNER_TEMP']) / 'capy-russian-model-comparison'
out.mkdir(exist_ok=False)
sdk = Path(os.environ['ANDROID_HOME'])
build = sdk / 'build-tools/36.0.0'
android = sdk / 'platforms/android-36/android.jar'
java = Path(os.environ['JAVA_HOME']) / 'bin'
report = comparison / 'runtime-results'
report.mkdir(exist_ok=False)
avd_home = out / 'avd'
android_user = out / 'android-user'
avd_home.mkdir()
android_user.mkdir()
tool_env = dict(os.environ, ANDROID_AVD_HOME=str(avd_home), ANDROID_USER_HOME=str(android_user))
tool_env.pop('ANDROID_SDK_HOME', None)
for key in list(tool_env):
    if key.startswith('CAPY_') or key in {'GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
            'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_URL'}:
        tool_env.pop(key, None)

def run(args, *, timeout=120, **kwargs):
    kwargs.setdefault('env', tool_env)
    return subprocess.run(list(map(str, args)), check=True, timeout=timeout, **kwargs)

def text_output(value):
    if value is None:
        return ''
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value

def preserve_observations(stdout, stderr, *, complete):
    stdout, stderr = text_output(stdout), text_output(stderr)
    (report / 'instrumentation.txt').write_text(stdout + stderr, encoding='utf-8')
    records = [json.loads(value) for value in re.findall(
        r'CAPY_RUSSIAN_OBSERVATION_JSON=(\{[^\r\n]+\})', stdout)]
    expected = [(m, i, 'opus', 'ru') for m in ('tiny', 'base_q5_1') for i in range(5)]
    actual = [(r['model_id'], r['row_index'], r['codec'], r['language_argument']) for r in records]
    if len(actual) > 10 or actual != expected[:len(actual)]:
        raise RuntimeError('Partial native observations differ from their predefined sequence.')
    for record in records:
        sample = fixture_pin['samples'][record['row_index']]
        if record['reference'] != sample['reference'] or record['reference_words'] <= 0:
            raise RuntimeError('Partial native reference differs.')
    partial = {'complete_instrumentation': complete,
        'production_apk_run': APK_RUN, 'production_apk_sha256': APK_SHA,
        'production_arm64_jni_sha256': hashlib.sha256(library).hexdigest(),
        'fixture_manifest_sha256': hashlib.sha256(fixture_bytes).hexdigest(),
        'model_choices_sha256': hashlib.sha256(choices_bytes).hexdigest(), 'models': choices['models'],
        'phases': re.findall(r'CAPY_RUSSIAN_PHASE=([^\r\n]+)', stdout),
        'observations': records, 'observation_count': len(records),
        'general_russian_quality_proven': False, 'physical_arm64_device': False,
        'live_telegram_chat_voice_acceptance': False, 'test_helper_internet_permission': False}
    (report / 'partial-observations.json').write_text(json.dumps(partial, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def failure_diagnostics(adb):
    # Disposable helper/emulator only. There are no Telegram sessions or owner audio.
    commands = [('helper memory', ['shell', 'dumpsys', 'meminfo', 'org.capybaragram.speechmodeltest']),
                ('emulator CPU', ['shell', 'dumpsys', 'cpuinfo']),
                ('last emulator log records', ['logcat', '-d', '-t', '500'])]
    sections = []
    for label, tail in commands:
        try:
            result = subprocess.run([str(adb), '-s', 'emulator-5554', *tail],
                                    capture_output=True, timeout=20)
            value = text_output(result.stdout) + text_output(result.stderr)
            sections.append(label + '\n' + value[:1000000])
        except subprocess.TimeoutExpired:
            sections.append(label + '\nDiagnostic command timed out; no synthetic result.')
    (report / 'diagnostics.log').write_text('\n\n'.join(sections), encoding='utf-8')

classes = out / 'classes'
dex = out / 'dex'
classes.mkdir()
dex.mkdir()
sources = [production / 'OfflineSpeech.java', production / 'AndroidPcmDecoder.java', comparison / 'RussianModelComparisonInstrumentation.java']
voice_hashes = json.loads((production / 'android-voice-hashes.json').read_text())
for item in sources[:2]:
    key = 'TMessagesProj/src/main/java/org/capybaragram/voice/' + item.name
    if hashlib.sha256(item.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != voice_hashes['added'][key]:
        raise RuntimeError('Production Java wrapper/decoder source differs.')
apks = list((Path(os.environ['RUNNER_TEMP']) / 'candidate-input').rglob('*.apk'))
if len(apks) != 1 or hashlib.sha256(apks[0].read_bytes()).hexdigest() != APK_SHA:
    raise RuntimeError('Expected the exact signed production APK.')
signer = run([build / 'apksigner', 'verify', '--print-certs', apks[0]], capture_output=True, text=True).stdout
if 'Signer #1 certificate SHA-256 digest: ' + CERT_SHA not in signer:
    raise RuntimeError('Production APK signer differs.')
with zipfile.ZipFile(apks[0]) as archive:
    entry = archive.getinfo('lib/arm64-v8a/libcapy_voice_jni.so')
    if not 0 < entry.file_size < 30000000:
        raise RuntimeError('Unexpected production JNI size.')
    library = archive.read(entry)
if library[:6] != b'\x7fELF\x02\x01' or int.from_bytes(library[18:20], 'little') != 183:
    raise RuntimeError('Speech JNI was not the production ARM64 ELF.')
choices_file = comparison / 'model-choices.json'
choices_bytes = choices_file.read_bytes()
choices = json.loads(choices_bytes)
if [m['id'] for m in choices['models']] != ['tiny', 'base_q5_1'] or choices['language'] != 'ru':
    raise RuntimeError('Model comparison selection differs.')
(report / 'preparation.json').write_text(json.dumps({
    'state': 'PREPARING, not runtime proof', 'production_apk_run': APK_RUN,
    'production_apk_sha256': APK_SHA, 'production_arm64_jni_sha256': hashlib.sha256(library).hexdigest(),
    'model_choices_sha256': hashlib.sha256(choices_bytes).hexdigest(), 'models': choices['models'],
    'test_helper_internet_permission': False, 'owner_profile_used': False}, indent=2) + '\n')
import urllib.request
models = {}
for m in choices['models']:
    if not re.fullmatch(r'ggml-(tiny|base-q5_1)\.bin', m['file']) or not 0 < m['bytes'] < 80000000:
        raise RuntimeError('Model identity or size outside the two-case scope.')
    model = out / m['file']
    with urllib.request.urlopen('https://huggingface.co/' + m['repository'] + '/resolve/' + m['revision'] + '/' + m['file'], timeout=90) as response, model.open('xb') as target:
        digest = hashlib.sha256(); count = 0
        while chunk := response.read(1048576):
            count += len(chunk)
            if count > m['bytes']:
                raise RuntimeError('Test model exceeds pinned size')
            digest.update(chunk); target.write(chunk)
    if count != m['bytes'] or digest.hexdigest() != m['sha256']:
        raise RuntimeError('Test model identity mismatch')
    models[m['file']] = model
fixture_manifest = source / 'fixture-manifest.json'
fixture_bytes = fixture_manifest.read_bytes()
fixture_pin = json.loads(fixture_bytes)
if fixture_pin['dataset_revision'] != '8123482db0c6a7b82694c1b92760a7e40e05c428' or len(fixture_pin['samples']) != 5:
    raise RuntimeError('Public Russian dataset identity differs.')
fixtures = {}
for sample in fixture_pin['samples']:
    for codec in ('opus', 'aac'):
        if codec not in sample:
            continue
        record = sample[codec]
        name = record['file']
        if not re.fullmatch(r'ru-[0-4]\.(ogg|m4a)', name) or name in fixtures:
            raise RuntimeError('Unsafe or duplicate public fixture name.')
        file = source / 'clips' / name
        if file.is_symlink() or not file.resolve(strict=True).is_relative_to((source / 'clips').resolve()):
            raise RuntimeError('Public fixture escapes its directory.')
        if file.stat().st_size != record['bytes'] or hashlib.sha256(file.read_bytes()).hexdigest() != record['sha256']:
            raise RuntimeError('Public audio fixture differs.')
        fixtures[name] = dict(record, path=file)
if len(fixtures) != 6:
    raise RuntimeError('Expected five Opus clips and one AAC comparison.')
manifest = (comparison / 'AndroidManifest.xml').read_text()
if '<uses-permission' in manifest or 'sharedUserId' in manifest:
    raise RuntimeError('Speech test must not request network or shared identity')
run([java / 'javac', '-encoding', 'UTF-8', '-source', '8', '-target', '8',
     '-Xlint:all,-options', '-Werror', '-cp', android, '-d', classes, *sources])
run([build / 'd8', '--min-api', '23', '--lib', android, '--output', dex,
     *sorted(classes.rglob('*.class'))])
unsigned = out / 'unsigned.apk'
run([build / 'aapt2', 'link', '-I', android, '--manifest', comparison / 'AndroidManifest.xml',
     '-o', unsigned])
with zipfile.ZipFile(unsigned, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(dex.glob('classes*.dex')):
        archive.write(file, file.name)
    archive.writestr('lib/arm64-v8a/libcapy_voice_jni.so', library)
    archive.write(fixture_manifest, 'assets/fixture-manifest.json')
    archive.write(choices_file, 'assets/model-choices.json')
    archive.write(comparison / 'MODEL-LICENSE.txt', 'assets/MODEL-LICENSE.txt')
    for name, model in models.items():
        archive.write(model, 'assets/' + name)
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
    abi_list = run([adb, '-s', 'emulator-5554', 'shell', 'getprop', 'ro.product.cpu.abilist'], capture_output=True, text=True).stdout.strip()
    native_bridge = run([adb, '-s', 'emulator-5554', 'shell', 'getprop', 'ro.dalvik.vm.native.bridge'], capture_output=True, text=True).stdout.strip()
    if 'arm64-v8a' not in abi_list or not native_bridge:
        raise RuntimeError('Expected real emulator ARM64 native translation.')
    try:
        result = run([adb, '-s', 'emulator-5554', 'shell', 'am', 'instrument', '-w', '-r',
            '-e', 'model_choices_sha', hashlib.sha256(choices_bytes).hexdigest(), '-e', 'fixture_manifest_sha', hashlib.sha256(fixture_bytes).hexdigest(),
            'org.capybaragram.speechmodeltest/org.capybaragram.voice.RussianModelComparisonInstrumentation'],
            capture_output=True, text=True, timeout=2400)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as failure:
        preserve_observations(failure.stdout, failure.stderr, complete=False)
        failure_diagnostics(adb)
        raise
    technical_pass = ('CAPY_ANDROID_RUSSIAN_MODELS=TECHNICAL_PASS' in result.stdout
                      and 'INSTRUMENTATION_CODE: -1' in result.stdout)
    preserve_observations(result.stdout, result.stderr, complete=technical_pass)
    print(result.stdout, flush=True)
    if not technical_pass:
        failure_diagnostics(adb)
        raise RuntimeError('Native speech checks did not pass')
    runtime = run([adb, '-s', 'emulator-5554', 'shell', 'getprop', 'ro.build.fingerprint'],
                  capture_output=True, text=True).stdout.strip()
    match = re.search(r'CAPY_RUSSIAN_MODELS_RESULT_JSON=(\{[^\r\n]+\})', result.stdout)
    if not match:
        raise RuntimeError('No structured actual native observations.')
    observations = json.loads(match[1])
    if observations['technical_execution'] != 'PASS' or len(observations['observations']) != 10:
        raise RuntimeError('Actual native observation inventory differs.')
    verification = {'runtime': runtime, 'production_apk_run': APK_RUN, 'production_apk_sha256': APK_SHA,
        'production_apk_certificate_sha256': CERT_SHA,
        'production_arm64_jni_sha256': hashlib.sha256(library).hexdigest(),
        'production_arm64_jni_executed': True, 'abi_list': abi_list, 'native_bridge': native_bridge,
        'source_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        'test_helper_apk_sha256': hashlib.sha256(apk.read_bytes()).hexdigest(),
        'test_helper_internet_permission': False, 'telegram_client_ui_integrated': False,
        'live_telegram_chat_voice_acceptance': False, 'physical_arm64_device': False,
        'russian_public_samples_measured': True, 'general_russian_quality_proven': False,
        'models': choices['models'], 'model_choices_sha256': hashlib.sha256(choices_bytes).hexdigest(),
        'production_model_changed': False, 'fixture_manifest_sha256': hashlib.sha256(fixture_bytes).hexdigest(),
        'source_dataset': {k: fixture_pin[k] for k in ('dataset', 'dataset_revision', 'license', 'selection', 'source_page')},
        'observations': observations}
    (report / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

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
