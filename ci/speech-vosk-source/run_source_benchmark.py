# SPDX-License-Identifier: MIT
"""Source-built public-data admission test; no wheel or client change."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import shutil
import signal
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

def execute_worker(args, env, stage, reports):
    """Retain exact outcome and bounded /proc telemetry even after native termination."""
    log = reports / 'worker.txt'
    start = time.monotonic()
    clock_ticks = os.sysconf('SC_CLK_TCK')
    peak = {'virtual_kib':0,'resident_kib':0,'threads':0,'cpu_seconds':0.0}
    last = None
    timed_out = False
    with log.open('xb') as output:
        child = subprocess.Popen(args,stdout=output,stderr=subprocess.STDOUT,env=env,cwd=stage)
        while child.poll() is None:
            try:
                status = Path(f'/proc/{child.pid}/status').read_text()
                values = {line.split(':',1)[0]:line.split(':',1)[1].strip() for line in status.splitlines() if ':' in line}
                stat_text = Path(f'/proc/{child.pid}/stat').read_text()
                fields = stat_text[stat_text.rindex(')')+2:].split()
                last = {'virtual_kib':int(values.get('VmSize','0').split()[0]),
                        'resident_kib':int(values.get('VmRSS','0').split()[0]),
                        'threads':int(values.get('Threads','0')),
                        'cpu_seconds':(int(fields[11])+int(fields[12]))/clock_ticks}
                for name,value in last.items():
                    peak[name] = max(peak[name],value)
            except (FileNotFoundError,ProcessLookupError):
                pass  # Reap authoritative child status; an observation race is not success.
            if time.monotonic()-start >= 180:
                timed_out = True
                child.kill()
                break
            time.sleep(.2)
        result = child.wait(timeout=5)
    outcome = {'returncode':result,'signal_name':signal.Signals(-result).name if result < 0 else None,
               'parent_wall_timeout':timed_out,'wall_seconds':round(time.monotonic()-start,3),
               'observed_peaks':peak,'last_observed':last,'telemetry_interval_seconds':.2,
               'address_space_limit_mib':3072,'cpu_limit_seconds':120,
               'network_prohibition_removed':False,'production_changed':False}
    (reports/'process-outcome.json').write_text(json.dumps(outcome,indent=2)+'\n')
    assert log.stat().st_size <= 200000, 'Oversized public worker log retained, no inference success'
    assert result == 0 and not timed_out, 'Native worker failed; inspect exact outcome, preserve evidence without retry'
    return outcome

def run():
    assert sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
    stage = Path(os.environ['RUNNER_TEMP']) / 'capy-vosk-source-benchmark'
    assert not stage.exists()
    stage.mkdir()
    reports = Path(os.environ['GITHUB_WORKSPACE']) / 'vosk-source-benchmark-report'
    reports.mkdir(exist_ok=False)
    admission = json.loads((CONTROL / 'ci/speech-vosk/source-admission.json').read_text())
    assert admission['wheel']['sha256'] == '25e025093c4399d7278f543568ed8cc5460ac3a4bf48c23673ace1e25d26619f'
    assert admission['model']['sha256'] == '961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4'
    fixture_file = CONTROL / 'ci/speech-ru/fixture-manifest.json'
    fixture_raw = fixture_file.read_bytes()
    assert sha(fixture_raw) == '6c6cc9d484fcdbef1efbcff1122cbb0a6a3cdfe0311bc86a77d4f20074f99991'
    fixture = json.loads(fixture_raw)
    ffmpeg = shutil.which('ffmpeg')
    source_manifest = (HERE / 'sources.json').read_bytes()
    assert sha(source_manifest) == '242b50774e2a986274a5f632df7a8bbc91105c3fe8f1c5883adb2bdac53b8464'
    build_file = Path(os.environ['GITHUB_WORKSPACE']) / 'vosk-source-build-report/source-build.json'
    build = json.loads(build_file.read_text())
    assert build['source_build_completed'] and build['phase'] == 'complete'
    assert build['source_manifest_sha256'] == sha(source_manifest)
    assert build['sandbox']['verified_before_vendor_build'] and not build['production_admitted']
    native = Path(os.environ['RUNNER_TEMP']) / 'capy-vosk-source-build/native/libvosk.so'
    assert native.is_file() and not native.is_symlink() and sha(native.read_bytes()) == build['native_sha256']
    worker = CONTROL / 'ci/speech-vosk/worker.py'
    assert sha(worker.read_bytes()) == '2e8d8261b2012554377dcf37adaf15b87c2208a2bb423e0e2881a5e480f926b1'
    preparation = {'created_utc':datetime.now(timezone.utc).isoformat(),'fixture_manifest_sha256':sha(fixture_raw),
                   'source_manifest_sha256':sha(source_manifest),'source_build_report_sha256':sha(build_file.read_bytes()),
                   'model_sha256':admission['model']['sha256'],'library_origin':'five-hash-pinned-source-archives',
                   'native_sha256':build['native_sha256'],'native_executed':False,
                   'owner_profile_or_audio_used':False,'production_client_changed':False,
                   'state':'PREPARING, not runtime proof','decoder':None,
                   'decoder_different_from_android_mediacodec':True,'same_encoded_clip_hashes':True}
    (reports / 'preparation.json').write_text(json.dumps(preparation,indent=2)+'\n')
    assert ffmpeg, 'Ubuntu decoder unavailable; preparation report retained, no binary-wheel fallback'
    version = subprocess.run([ffmpeg,'-version'],capture_output=True,check=True,timeout=10).stdout.decode().splitlines()[0]
    packages = subprocess.run(['dpkg-query','-W','-f=${Package} ${Version}\n','ffmpeg','libseccomp2'],
                              capture_output=True,check=True,timeout=10).stdout.decode().splitlines()
    preparation.update(decoder=version,decoder_executable_sha256=sha(Path(ffmpeg).read_bytes()),
                       host_packages=packages,host_packages_from_ubuntu_repository=True,
                       host_package_versions_pinned=False)
    (reports / 'preparation.json').write_text(json.dumps(preparation,indent=2)+'\n')
    print('Preparing five predefined public clips; no account or owner input.',flush=True)
    for key in ('model',):
        item = admission[key]
        file = stage / item['filename']
        download(item,file)
        check_zip(file,item['members'],50_000_000 if key == 'wheel' else 150_000_000)
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
    config = {'native_library':str(native),'native_sha256':build['native_sha256'],
              'model_directory':str(model_root / 'vosk-model-small-ru-0.22'),
              'model_members':admission['model']['members'],'samples':samples,'output':str(worker_output)}
    config_file = stage / 'input.json'
    config_file.write_text(json.dumps(config,ensure_ascii=False)+'\n',encoding='utf8')
    env = {key:value for key,value in os.environ.items()
           if not any(marker in key.upper() for marker in ('TOKEN','SECRET','PASSWORD','CAPY_API','KEYSTORE'))}
    env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    print('Running one network-denied child; one static model and five fresh recognizers,180s wall bound.',flush=True)
    outcome = execute_worker([sys.executable,'-I',str(worker),str(config_file)],env,stage,reports)
    observed = json.loads(worker_output.read_text(encoding='utf8'))
    assert observed['complete'] and observed['phase'] == 'complete'
    assert observed['model_lifecycle'] == 'one-static-model/fresh-recognizer-per-clip'
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
    lifecycle_reports = reports / 'lifecycle'
    lifecycle_reports.mkdir()
    lifecycle_config = dict(config,output=str(lifecycle_reports/'partial-observations.json'))
    lifecycle_file = stage/'lifecycle-input.json'
    lifecycle_file.write_text(json.dumps(lifecycle_config,ensure_ascii=False)+'\n',encoding='utf8')
    lifecycle_outcome = execute_worker([sys.executable,'-I',str(HERE/'lifecycle_worker.py'),str(lifecycle_file)],env,stage,lifecycle_reports)
    lifecycle = json.loads((lifecycle_reports/'partial-observations.json').read_text(encoding='utf8'))
    assert lifecycle['complete'] and len(lifecycle['cycles']) == 2
    assert lifecycle['sandbox']['verified_before_vendor_load']
    proof = dict(preparation,native_executed=True,state='TECHNICAL_PASS',observations=rows,totals=totals,
                 sandbox=observed['sandbox'],peak_rss_kib=observed['peak_rss_kib'],
                 process_outcome=outcome,
                 model_lifecycle=observed['model_lifecycle'],
                 repeated_model_unload_reload_accepted=True,lifecycle=lifecycle,lifecycle_process_outcome=lifecycle_outcome,
                 real_telegram_ui_or_account_acceptance=False,physical_android=False,
                 general_russian_quality_accepted=False,full_vendor_security_audit=False,
                 speed_comparison_with_arm64_translation_valid=False)
    (reports / 'verification.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'technical_execution':'PASS','totals':totals,'production_client_changed':False}),flush=True)

if __name__ == '__main__':
    run()
