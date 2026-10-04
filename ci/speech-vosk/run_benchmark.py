# SPDX-License-Identifier: MIT
"""Pinned public-data admission test; no Python package install or client change."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
CONTROL = HERE.parent.parent

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def download(item, target):
    request = urllib.request.Request(item['url'],headers={'User-Agent':'CapybaraGram-offline-source-test'})
    start = time.monotonic()
    with urllib.request.urlopen(request,timeout=30) as response, target.open('xb') as out:
        url = urllib.parse.urlparse(response.url)
        assert url.scheme == 'https' and url.hostname in {'files.pythonhosted.org','alphacephei.com'}
        assert not url.username
        count = 0
        digest = hashlib.sha256()
        while chunk := response.read(65536):
            assert time.monotonic() - start < 180 and count + len(chunk) <= item['bytes']
            digest.update(chunk); out.write(chunk); count += len(chunk)
    assert count == item['bytes'] and digest.hexdigest() == item['sha256']

def check_zip(path, expected, limit):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        assert len(entries) <= 100 and len(entries) == len({e.filename for e in entries})
        assert sum(e.file_size for e in entries) < limit and archive.testzip() is None
        actual = {}
        for entry in entries:
            name = PurePosixPath(entry.filename)
            assert not name.is_absolute() and '..' not in name.parts and ':' not in entry.filename
            assert stat.S_IFMT(entry.external_attr >> 16) != stat.S_IFLNK
            if not entry.is_dir():
                raw = archive.read(entry)
                actual[entry.filename] = {'bytes':len(raw),'sha256':sha(raw)}
        assert actual == expected

def run():
    assert sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
    stage = Path(os.environ['RUNNER_TEMP']) / 'capy-vosk-benchmark'
    assert not stage.exists()
    stage.mkdir()
    reports = Path(os.environ['GITHUB_WORKSPACE']) / 'vosk-report'
    reports.mkdir(exist_ok=False)
    admission = json.loads((HERE / 'source-admission.json').read_text())
    assert admission['wheel']['sha256'] == '25e025093c4399d7278f543568ed8cc5460ac3a4bf48c23673ace1e25d26619f'
    assert admission['model']['sha256'] == '961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4'
    fixture_file = CONTROL / 'ci/speech-ru/fixture-manifest.json'
    fixture_raw = fixture_file.read_bytes()
    assert sha(fixture_raw) == '6c6cc9d484fcdbef1efbcff1122cbb0a6a3cdfe0311bc86a77d4f20074f99991'
    fixture = json.loads(fixture_raw)
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg, 'Trusted runner ffmpeg unavailable; no vendor install fallback'
    version = subprocess.run([ffmpeg,'-version'],capture_output=True,check=True,timeout=10).stdout.decode().splitlines()[0]
    preparation = {'created_utc':datetime.now(timezone.utc).isoformat(),'fixture_manifest_sha256':sha(fixture_raw),
                   'source_admission_sha256':sha((HERE / 'source-admission.json').read_bytes()),
                   'wheel_sha256':admission['wheel']['sha256'],'model_sha256':admission['model']['sha256'],
                   'native_sha256':admission['wheel']['native_sha256'],'native_executed':False,
                   'owner_profile_or_audio_used':False,'production_client_changed':False,
                   'state':'PREPARING, not runtime proof','decoder':version,
                   'decoder_different_from_android_mediacodec':True,'same_encoded_clip_hashes':True}
    (reports / 'preparation.json').write_text(json.dumps(preparation,indent=2)+'\n')
    print('Preparing five predefined public clips; no account or owner input.',flush=True)
    for key in ('wheel','model'):
        item = admission[key]
        file = stage / item['filename']
        download(item,file)
        check_zip(file,item['members'],50_000_000 if key == 'wheel' else 150_000_000)
    native = stage / 'libvosk.so'
    with zipfile.ZipFile(stage / admission['wheel']['filename']) as archive:
        native.write_bytes(archive.read('vosk/libvosk.so'))
    assert sha(native.read_bytes()) == admission['wheel']['native_sha256']
    model_root = stage / 'model'
    model_root.mkdir()
    with zipfile.ZipFile(stage / admission['model']['filename']) as archive:
        for name in admission['model']['members']:
            dest = model_root / name
            assert dest.resolve().is_relative_to(model_root.resolve())
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(archive.read(name))
    samples = []
    for row in fixture['samples']:
        encoded = CONTROL / 'ci/speech-ru/clips' / row['opus']['file']
        assert encoded.is_file() and sha(encoded.read_bytes()) == row['opus']['sha256']
        pcm = stage / f'ru-{row["row_index"]}.s16le'
        subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-i',str(encoded),
                        '-vn','-ac','1','-ar','16000','-f','s16le',str(pcm)],check=True,timeout=20)
        raw = pcm.read_bytes()
        assert 32000 <= len(raw) <= 960000 and abs(len(raw)/32000 - row['source_duration_seconds']) <= 0.5
        samples.append({'row_index':row['row_index'],'reference':row['reference'],
                        'source_duration_seconds':row['source_duration_seconds'],
                        'encoded_clip_sha256':row['opus']['sha256'],'pcm_path':str(pcm),
                        'pcm_bytes':len(raw),'pcm_sha256':sha(raw)})
    worker_output = reports / 'partial-observations.json'
    config = {'native_library':str(native),'native_sha256':admission['wheel']['native_sha256'],
              'model_directory':str(model_root / 'vosk-model-small-ru-0.22'),
              'model_members':admission['model']['members'],'samples':samples,'output':str(worker_output)}
    config_file = stage / 'input.json'
    config_file.write_text(json.dumps(config,ensure_ascii=False)+'\n',encoding='utf8')
    env = {key:value for key,value in os.environ.items()
           if not any(marker in key.upper() for marker in ('TOKEN','SECRET','PASSWORD','CAPY_API','KEYSTORE'))}
    env.update(OPENBLAS_NUM_THREADS='2',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    print('Running one network-denied child; five fresh model/recognizer contexts,180s wall bound.',flush=True)
    try:
        result = subprocess.run([sys.executable,'-I',str(HERE / 'worker.py'),str(config_file)],
                                capture_output=True,env=env,cwd=stage,timeout=180)
    except subprocess.TimeoutExpired as failure:
        (reports / 'worker.txt').write_bytes((failure.stdout or b'') + (failure.stderr or b''))
        raise
    assert len(result.stdout) + len(result.stderr) <= 200000
    (reports / 'worker.txt').write_bytes(result.stdout + result.stderr)
    assert result.returncode == 0, 'Native worker failed; preserve partial evidence without retry'
    observed = json.loads(worker_output.read_text(encoding='utf8'))
    assert observed['complete'] and observed['phase'] == 'complete'
    assert observed['sandbox']['verified_before_vendor_load'] and observed['sandbox']['execve_denied']
    assert observed['sandbox']['network_and_unix_socket_creation_denied']
    rows = observed['observations']
    assert [r['row_index'] for r in rows] == list(range(5))
    for row, sample in zip(rows,samples):
        assert row['reference'] == sample['reference'] and row['pcm_sha256'] == sample['pcm_sha256']
    totals = {'sample_count':5,'reference_words':sum(r['reference_words'] for r in rows),
              'word_edits':sum(r['word_edits'] for r in rows),
              'inference_milliseconds_sum':sum(r['inference_milliseconds'] for r in rows),
              'model_load_milliseconds_sum':sum(r['model_load_milliseconds'] for r in rows)}
    assert totals['reference_words'] == 63
    totals['word_error_rate'] = totals['word_edits']/totals['reference_words']
    proof = dict(preparation,native_executed=True,state='TECHNICAL_PASS',observations=rows,totals=totals,
                 sandbox=observed['sandbox'],peak_rss_kib=observed['peak_rss_kib'],
                 real_telegram_ui_or_account_acceptance=False,physical_android=False,
                 general_russian_quality_accepted=False,full_vendor_security_audit=False,
                 speed_comparison_with_arm64_translation_valid=False)
    (reports / 'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'technical_execution':'PASS','totals':totals,'production_client_changed':False}),flush=True)

if __name__ == '__main__':
    run()
