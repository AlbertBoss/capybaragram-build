# SPDX-License-Identifier: MIT
"""Build the exact verified transport with the native client's release CRT."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
CI = HERE.parent
TARGET = 'x86_64-pc-windows-msvc'
RUST = '1.88.0'


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def run(name, arguments, work, report, env, timeout=600):
    process = subprocess.run(arguments, cwd=work, env=env, capture_output=True,
                             text=True, encoding='utf-8', errors='replace', timeout=timeout)
    output = process.stdout + process.stderr
    (report / (name + '.txt')).write_text(output, encoding='utf-8')
    if process.returncode:
        print(output[-12000:], flush=True)
        raise RuntimeError('Connection release build failed: ' + name)
    if re.search(r'warning LNK[0-9]+', output, re.IGNORECASE):
        raise RuntimeError('Unexpected linker warning: ' + name)
    print('CAPY_CONNECTION_RELEASE_' + name.upper() + '=PASS', flush=True)
    return output


def build(work, report):
    if os.name != 'nt' or not os.environ.get('VCToolsVersion', '').startswith('14.44.'):
        raise ValueError('Initialize the production x64 MSVC 14.44 environment first')
    if os.environ.get('VSCMD_ARG_TGT_ARCH', '').lower() != 'x64':
        raise ValueError('Expected x64 MSVC target')
    if os.environ.get('WindowsSDKVersion', '').rstrip('\\/') != '10.0.26100.0':
        raise ValueError('Expected production Windows SDK 10.0.26100.0')
    toolset = os.environ['VCToolsVersion'].rstrip('\\/')
    pins = json.loads((HERE / 'source-provenance.json').read_text(encoding='utf-8'))
    for folder, field in [('connection', 'core_source_sha256'), ('windows-connection', 'worker_source_sha256')]:
        path = CI / folder
        files = {p.relative_to(path).as_posix(): digest(p) for p in path.rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and 'test-results' not in p.parts}
        if files != pins[field]:
            raise ValueError('Verified connection source differs: ' + folder)
    spec = importlib.util.spec_from_file_location('capy_connection_prepare', CI / 'connection/prepare_core.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prepared = module.prepare(work)
    if prepared != pins['prepared_source']:
        raise ValueError('Prepared connection differs from the reviewed revision')
    report.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    # Vendor build scripts receive neither owner API keys nor Actions tokens.
    for name in list(env):
        if name.startswith('CAPY_') or name in {
                'GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
                'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_URL'}:
            env.pop(name, None)
    env.pop('CARGO_ENCODED_RUSTFLAGS', None)
    env['RUSTFLAGS'] = '-C target-feature=+crt-static'
    env['CARGO_TARGET_DIR'] = str(work / 'target')
    cl = run('compiler_path', ['where.exe', 'cl.exe'], work, report, env, 30).splitlines()[0]
    if '/msvc/14.44.' not in cl.replace('\\', '/').lower():
        raise ValueError('PATH selects a different C++ compiler')
    compiler = run('rust_version', ['rustc', '+' + RUST, '-vV'], work, report, env, 30)
    if not compiler.startswith('rustc ' + RUST + ' ') or ('host: ' + TARGET) not in compiler:
        raise ValueError('Wrong Rust toolchain or host')
    # Explicit target keeps host proc-macro crates out of the static CRT profile.
    run('transport', ['cargo', '+' + RUST, 'build', '--target', TARGET, '--release',
                      '--locked', '--no-default-features', '--lib'], work, report, env)
    library = work / 'target' / TARGET / 'release/tglock.lib'
    if not library.is_file() or library.stat().st_size < 100000:
        raise ValueError('Connection static library missing')
    result = {'result': 'PASS', 'rust_version': RUST, 'target': TARGET,
              'toolset': toolset, 'sdk': '10.0.26100.0',
              'crt': 'static release', 'rustflags': env['RUSTFLAGS'], 'compiler_path': cl,
              'library_path': str(library), 'library_bytes': library.stat().st_size,
              'library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
              'core_proof_run': pins['core_proof_run'], 'worker_proof_run': pins['worker_proof_run'],
              'prepared_source': prepared, 'client_compiled': False, 'live_telegram_tested': False}
    (report / 'library-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result, env


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = __import__('argparse').ArgumentParser()
    parser.add_argument('--probe', action='store_true')
    args = parser.parse_args()
    work = Path(os.environ['RUNNER_TEMP']) / 'capy-connection-release-source'
    report = HERE / 'test-results'
    result, env = build(work, report)
    result['native_source_sha256'] = {p.name: digest(p) for p in HERE.iterdir() if p.is_file()}
    if args.probe:
        for module_name, executable, marker in (
                ('connection', 'capy_connection_native_probe', 'CAPY_NATIVE_CONNECTION_ABI=PASS 632 assertions'),
                ('windows-connection', 'capy_connection_worker_probe', 'CAPY_CONNECTION_WORKER=PASS 13 assertions')):
            native = work.parent / ('capy-release-' + module_name)
            run(module_name + '_configure', ['cmake', '-G', 'Ninja', '-S', str(CI / module_name), '-B', str(native),
                '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded',
                '-DCMAKE_EXE_LINKER_FLAGS=/WX', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                '-DCAPY_CONNECTION_LIBRARY=' + result['library_path'],
                '-DCAPY_CONNECTION_HEADER_DIR=' + str(CI / 'connection')], work, report, env, 120)
            run(module_name + '_compile', ['cmake', '--build', str(native), '--parallel', '2', '--verbose'],
                work, report, env, 180)
            commands = json.loads((native / 'compile_commands.json').read_text(encoding='utf-8'))
            if not commands or any(not re.search(r'(?:^|\s)/MT(?:\s|$)', c['command'])
                                   or re.search(r'(?:^|\s)/MD', c['command']) for c in commands):
                raise ValueError('C++ probe does not use the static release CRT')
            binary = native / (executable + '.exe')
            output = run(module_name + '_runtime', [str(binary)], work, report, env, 60)
            if marker not in output:
                raise ValueError('Native release acceptance marker missing')
            deps = run(module_name + '_imports', ['dumpbin.exe', '/dependents', str(binary)], work, report, env, 30)
            if re.search(r'(?:vcruntime\d*|msvcp\d*|ucrtbase|api-ms-win-crt)[^\s]*\.dll', deps, re.IGNORECASE):
                raise ValueError('Unexpected dynamic C/C++ runtime in native probe')
        result.update(abi_and_worker_real_runtime='PASS', cpp_crt='static release',
                      dynamic_crt_imports=False, linker_warnings=False)
    if os.environ.get('GITHUB_ENV'):
        with Path(os.environ['GITHUB_ENV']).open('a', encoding='utf-8') as output:
            output.write('CAPY_WINDOWS_CONNECTION_LIBRARY=' + result['library_path'] + '\n')
            output.write('CAPY_WINDOWS_CONNECTION_LIBRARY_SHA=' + result['library_sha256'] + '\n')
    (report / 'verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
