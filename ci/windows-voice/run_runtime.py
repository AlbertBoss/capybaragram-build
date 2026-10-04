# SPDX-License-Identifier: MIT
"""Disposable native Windows/Linux runtime using public, pinned audio/model only."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import urllib.request
import zipfile

here = Path(__file__).resolve().parent
shared = here.parent / 'transcription'
pins = json.loads((shared / 'source-pins.json').read_text())
root = Path(os.environ['RUNNER_TEMP']) / 'capy-desktop-voice-runtime'
root.mkdir(exist_ok=False)
report = here / 'test-results'; report.mkdir(exist_ok=False)
def download(url, file, expected, maximum):
    count = 0; h = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=90) as response, file.open('xb') as f:
        while chunk := response.read(1048576):
            count += len(chunk)
            if count > maximum: raise ValueError('Pinned download too large')
            h.update(chunk); f.write(chunk)
    if h.hexdigest() != expected: raise ValueError('Pinned download hash differs')
    return count
archive = root / 'whisper.zip'
download('https://codeload.github.com/' + pins['repository'] + '/zip/' + pins['commit'], archive,
    pins['zip_sha256'], 80 * 1048576)
with zipfile.ZipFile(archive) as z:
    prefix = z.namelist()[0].split('/')[0] + '/'
    for entry in z.infolist():
        if entry.is_dir(): continue
        p = PurePosixPath(entry.filename.removeprefix(prefix))
        if not entry.filename.startswith(prefix) or p.is_absolute() or '..' in p.parts or ':' in str(p) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError('Unsafe pinned source path')
        f = root / 'whisper' / str(p); f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(z.read(entry))
model_directory = root / 'Модель голоса'; model_directory.mkdir()
m = pins['model']
count = download('https://huggingface.co/' + m['repository'] + '/resolve/' + m['revision'] + '/' + m['file'],
    model_directory / 'tiny.bin', m['sha256'], m['bytes'])
assert count == m['bytes']
wav = root / 'whisper/samples/jfk.wav'
opus = root / 'voice-opus.ogg'; aac = root / 'voice-aac.m4a'
for target, options in [(opus, ['-ac', '1', '-ar', '48000', '-c:a', 'libopus', '-b:a', '24k']),
                        (aac, ['-ac', '2', '-ar', '44100', '-c:a', 'aac', '-b:a', '64k'])]:
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', str(wav)] + options + [str(target)], check=True, timeout=60)
build = root / 'build'
subprocess.run(['cmake', '-S', str(here), '-B', str(build), '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
    '-DCAPY_WHISPER_SOURCE=' + str(root / 'whisper')], check=True, timeout=180)
subprocess.run(['cmake', '--build', str(build), '--target', 'capy_windows_voice_runtime', '--parallel', '2'], check=True, timeout=1200)
executables = list(build.rglob('capy_windows_voice_runtime.exe' if os.name == 'nt' else 'capy_windows_voice_runtime'))
assert len(executables) == 1
# No user profiles/Telegram API credentials are passed to this executable.
run = subprocess.run([str(executables[0]), str(model_directory), str(opus), str(aac)],
    capture_output=True, encoding='utf8', errors='replace', timeout=300)
(report / 'runtime-result.txt').write_text(run.stdout + run.stderr, encoding='utf8')
if run.returncode or 'CAPY_WINDOWS_VOICE_RUNTIME=PASS checks=' not in run.stdout:
    raise RuntimeError('Desktop speech runtime failed; inspect artifact diagnostics')
result = {'platform': sys.platform, 'result': 'PASS', 'source_commit': pins['commit'],
    'source_archive_sha256': pins['zip_sha256'], 'model_sha256': m['sha256'],
    'fixture_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (opus, aac)},
    'our_source_sha256': {str(p.relative_to(here.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
        for directory in (here, shared) for p in directory.iterdir() if p.is_file()},
    'full_telegram_ui_tested': False, 'russian_voice_accuracy_tested': False,
    'download_ui_and_live_peer_tested': False,
    'test_dependencies': 'Official distribution Qt/FFmpeg packages; not production vendored libraries',
    'checks': run.stdout.strip()}
(report / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(run.stdout, flush=True)
