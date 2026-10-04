# SPDX-License-Identifier: MIT
"""TLS regressions and real Android JNI cross-build; never uses owner credentials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

from prepare_android_core import prepare, digest

HERE = Path(__file__).resolve().parent
CI = HERE.parent
RUST = '1.88.0'


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--bootstrap-lock-only', action='store_true')
    arguments = parser.parse_args()
    work = Path(os.environ['RUNNER_TEMP']) / 'capy-android-connection'
    report = HERE / 'test-results'
    report.mkdir(exist_ok=False)
    manifest = prepare(work, arguments.bootstrap_lock_only)
    env = dict(os.environ)
    for name in list(env):
        if name.startswith('CAPY_') or name in {'GH_TOKEN','GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN',
                                               'ACTIONS_ID_TOKEN_REQUEST_TOKEN','ACTIONS_ID_TOKEN_REQUEST_URL'}:
            env.pop(name, None)
    env.pop('CARGO_ENCODED_RUSTFLAGS', None)
    env.pop('RUSTFLAGS', None)
    env['CARGO_TARGET_DIR'] = str(work / 'target')

    def run(name, command, timeout=600, additions=None):
        result = subprocess.run(command, cwd=work, env=dict(env, **(additions or {})), capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=timeout)
        text = result.stdout + result.stderr
        (report / (name + '.txt')).write_text(text, encoding='utf-8')
        if result.returncode:
            print(text[-14000:], flush=True)
            raise RuntimeError('Android connection check failed: ' + name)
        print('CAPY_ANDROID_CONNECTION_' + name.upper() + '=PASS', flush=True)
        return text

    result = {'result':'INCOMPLETE','source':manifest,'client_integrated':False,'real_android_runtime':False,
              'live_telegram_tested':False,'vpn_transition_tested':False,
              'bootstrap_dependency_resolution':arguments.bootstrap_lock_only,
              'source_sha256':{p.name:digest(p.read_bytes()) for p in HERE.iterdir() if p.is_file()}}
    try:
        version = run('rustc', ['rustc','+'+RUST,'--version'], 30).strip()
        if not version.startswith('rustc '+RUST+' '):
            raise ValueError('Wrong Rust version')
        common = ['cargo','+'+RUST]
        if arguments.bootstrap_lock_only:
            # Explicit disposable dependency-resolution job. No APK is produced.
            run('resolve_lock', common+['generate-lockfile'], 180)
        lock = (work/'Cargo.lock').read_bytes()
        (report/'Cargo.lock').write_bytes(lock)
        result['cargo_lock_sha256'] = digest(lock)
        packages = tomllib.loads(lock.decode())['package']
        expected = json.loads((HERE/'source-provenance.json').read_text())['tls_registry']
        for name, pin in expected.items():
            matches = [p for p in packages if p['name']==name]
            if len(matches)!=1 or matches[0]['version']!=pin['version'] or matches[0].get('checksum')!=pin['checksum']:
                raise ValueError('TLS dependency registry pin differs: '+name)
        forbidden = {'native-tls','openssl','openssl-sys','tokio-native-tls','aws-lc-rs','aws-lc-sys','tauri','tauri-build'}
        if forbidden & {p['name'] for p in packages}:
            raise ValueError('Unexpected TLS/frontend dependency in Android lock')
        tests = run('runtime', common+['test','--locked','--no-default-features','--lib'])
        suites = re.findall(r'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored',tests)
        if len(suites)!=1 or int(suites[0][1]) or int(suites[0][2])!=2:
            raise ValueError('Runtime suite missing or unexpected failures/skips')
        required = ['capy_android_tls_valid_hostname_and_trusted_certificate',
                    'capy_android_tls_wrong_hostname_is_rejected',
                    'capy_android_tls_production_roots_reject_self_signed_peer',
                    'capy_client_limit_rejects_overflow_and_recovers_capacity',
                    'stop_cancels_incomplete_client_and_is_idempotent',
                    'capy_native_api_owns_endpoint_and_rejects_revoked_handle']
        for name in required:
            if not re.search(r'::'+name+r' \.\.\. ok',tests):
                raise ValueError('Required regression did not run: '+name)
        skipped = re.findall(r'^test ([\w:]+) \.\.\. ignored, requires live Telegram network access$',tests,re.M)
        if set(skipped)!={'proxy::tests::accepts_mtproto_and_builds_live_media_tunnel',
                         'transport::tests::connects_to_all_production_data_centers'}:
            raise ValueError('Unexpected ignored tests')
        result.update(tests_passed=int(suites[0][0]), required_regressions=required, skipped_live_tests=skipped)
        run('clippy',common+['clippy','--locked','--no-default-features','--lib','--tests','--','-D','warnings'])
        run('host_staticlib',common+['build','--release','--locked','--no-default-features','--lib'])
        probe=work/'native-probe'
        run('host_abi_configure',['cmake','-G','Ninja','-S',str(CI/'connection'),'-B',str(probe),
            '-DCMAKE_BUILD_TYPE=Release','-DCAPY_CONNECTION_LIBRARY='+str(work/'target/release/libtglock.a')],120)
        run('host_abi_compile',['cmake','--build',str(probe),'--parallel','2'],120)
        native=run('host_abi_runtime',[str(probe/'capy_connection_native_probe')],120)
        if 'CAPY_NATIVE_CONNECTION_ABI=PASS 632 assertions' not in native:
            raise ValueError('Actual native ABI regression marker missing')
        result['host_cpp_abi_assertions']=632
        classes=work/'java';classes.mkdir()
        run('java_bridge',['javac','--release','8','-Xlint:all','-Werror','-d',str(classes),str(HERE/'NativeTunnel.java')],30)
        ndk = Path(os.environ['ANDROID_HOME'])/'ndk/27.2.12479018'
        properties = (ndk/'source.properties').read_text()
        if not re.search(r'^Pkg.Revision\s*=\s*27\.2\.12479018\s*$',properties,re.M):
            raise ValueError('Wrong Android NDK')
        tools = ndk/'toolchains/llvm/prebuilt/linux-x86_64/bin'
        result['android_libraries'] = {}
        for abi, target, clang_prefix, machine in (
                ('arm64-v8a','aarch64-linux-android','aarch64-linux-android',183),
                ('x86_64','x86_64-linux-android','x86_64-linux-android',62)):
            clang = str(tools/(clang_prefix+'23-clang'))
            ar = str(tools/'llvm-ar')
            additions = {'CARGO_TARGET_'+target.upper().replace('-','_')+'_LINKER':clang,
                         'CC_'+target.replace('-','_'):clang, 'AR_'+target.replace('-','_'):ar,
                         'CFLAGS_'+target.replace('-','_'):'-fPIC', 'RUSTFLAGS':'-C relocation-model=pic'}
            run(abi+'_rust', common+['build','--locked','--no-default-features','--lib','--release','--target',target],900,additions)
            library = work/'target'/target/'release/libtglock.a'
            build = work/('jni-'+abi)
            run(abi+'_configure',['cmake','-G','Ninja','-S',str(HERE),'-B',str(build),
                '-DCMAKE_TOOLCHAIN_FILE='+str(ndk/'build/cmake/android.toolchain.cmake'),
                '-DANDROID_ABI='+abi,'-DANDROID_PLATFORM=android-23','-DANDROID_STL=c++_static',
                '-DCMAKE_BUILD_TYPE=Release','-DCAPY_CONNECTION_LIBRARY='+str(library),
                '-DCAPY_CONNECTION_HEADER_DIR='+str(CI/'connection')],120)
            run(abi+'_jni',['cmake','--build',str(build),'--parallel','2'],180)
            shared = build/'libcapy_connection_jni.so'
            data = shared.read_bytes()
            if data[:4]!=b'\x7fELF' or data[4]!=2 or int.from_bytes(data[18:20],'little')!=machine:
                raise ValueError('Wrong JNI architecture')
            phoff=int.from_bytes(data[32:40],'little');phsize=int.from_bytes(data[54:56],'little');phnum=int.from_bytes(data[56:58],'little')
            if phsize<56 or phnum>128 or phoff+phsize*phnum>len(data):
                raise ValueError('Invalid ELF program table')
            aligns=[int.from_bytes(data[phoff+i*phsize+48:phoff+i*phsize+56],'little') for i in range(phnum)
                    if int.from_bytes(data[phoff+i*phsize:phoff+i*phsize+4],'little')==1]
            if not aligns or min(aligns)<16384:
                raise ValueError('JNI does not support 16 KiB pages')
            dynamic=run(abi+'_imports',[str(tools/'llvm-readelf'),'-d',str(shared)],30)
            imports=set(re.findall(r'Shared library: \[([^\]]+)\]',dynamic))
            if not imports <= {'libc.so','libm.so','libdl.so','liblog.so','libandroid.so'}:
                raise ValueError('Unexpected Android shared dependency')
            symbols=run(abi+'_symbols',[str(tools/'llvm-nm'),'-D','--defined-only',str(shared)],30)
            for method in ('start','status','stop'):
                if 'Java_org_capybaragram_connection_NativeTunnel_'+method not in symbols:
                    raise ValueError('JNI export missing')
            result['android_libraries'][abi]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                                             'minimum_load_alignment':min(aligns),'imports':sorted(imports)}
        for name, sha in manifest['prepared_sha256'].items():
            if digest((work/name).read_bytes())!=sha:
                raise ValueError('Prepared source mutated during checks: '+name)
        result.update(result='PASS',prepared_sources_unchanged=True)
    finally:
        (report/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    main()
