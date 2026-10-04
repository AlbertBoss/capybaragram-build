# SPDX-License-Identifier: MIT
"""Read-only public req_pq network observations through frozen production cores.
Only disposable CI; never opens a Telegram profile or receives owner API inputs.
"""
import argparse
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
RUST = '1.88.0'
EXPECTED = [(1, False), (2, False), (3, False), (4, False), (5, False),
            (203, False), (2, True), (4, True)]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--variant', required=True, choices=('windows', 'android-tls'))
    args = parser.parse_args()
    required_os = 'Windows' if args.variant == 'windows' else 'Linux'
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_OS') != required_os:
        raise RuntimeError('This probe is restricted to the matching disposable CI runner.')
    report = HERE / 'test-results'
    report.mkdir(exist_ok=False)
    work = Path(os.environ['RUNNER_TEMP']) / ('capy-live-' + args.variant)
    parent = CI / ('connection' if args.variant == 'windows' else 'android-connection')
    source_file = parent / ('prepare_core.py' if args.variant == 'windows' else 'prepare_android_core.py')
    module_spec = importlib.util.spec_from_file_location('capy_live_frozen_source', source_file)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    original = module.prepare(work)
    cargo_original = (work / 'Cargo.toml').read_bytes()
    suffix = b'\n[[bin]]\nname = "capy-live-probe"\npath = "src/bin/capy_live_probe.rs"\n'
    if b'capy-live-probe' in cargo_original:
        raise RuntimeError('Unexpected probe in frozen production manifest.')
    (work / 'Cargo.toml').write_bytes(cargo_original + suffix)
    probe = work / 'src/bin/capy_live_probe.rs'
    if probe.exists():
        raise RuntimeError('Probe target already exists.')
    probe.parent.mkdir(exist_ok=True)
    probe.write_bytes((HERE / 'live_probe.rs').read_bytes())
    env = dict(os.environ)
    for key in list(env):
        if key.startswith('CAPY_') or key in {'GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
                'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_URL',
                'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'}:
            env.pop(key, None)
    env.pop('CARGO_ENCODED_RUSTFLAGS', None)
    env.pop('RUSTFLAGS', None)
    if args.variant == 'windows':
        env['RUSTFLAGS'] = '-C target-feature=+crt-static'
    env['CARGO_TARGET_DIR'] = str(work / 'target')
    proof = {'result': 'INCOMPLETE', 'variant': args.variant, 'runner_os': required_os,
        'prepared_production_source': original, 'probe_sha256': sha(probe),
        'manifest_test_only_suffix_sha256': hashlib.sha256(suffix).hexdigest(),
        'cargo_lock_sha256': sha(work / 'Cargo.lock'),
        'telegram_account_used': False, 'authorization_key_created': False,
        'native_client_ui_tested': False, 'actual_android_abi_tested': False,
        'rf_provider_availability_proven': False, 'vpn_transition_tested': False,
        'tls_validation_disabled': False, 'external_proxy_or_worker_configured': False}

    def execute(name, command, timeout):
        try:
            result = subprocess.run(command, cwd=work, env=env, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace', timeout=timeout)
            value = result.stdout + result.stderr
            code = result.returncode
        except subprocess.TimeoutExpired as failure:
            def text(value):
                return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
            value = text(failure.stdout) + text(failure.stderr) + '\nProcess deadline exceeded.\n'
            code = 124
        (report / (name + '.txt')).write_text(value, encoding='utf-8')
        return code, value

    try:
        version = subprocess.run(['rustc', '+' + RUST, '--version'], cwd=work, env=env,
                                 capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        if not version.startswith('rustc ' + RUST + ' '):
            raise RuntimeError('Rust toolchain differs.')
        proof['rustc'] = version
        common = ['cargo', '+' + RUST]
        code, value = execute('parser-test', common + ['test', '--locked', '--no-default-features',
                                                     '--bin', 'capy-live-probe'], 900)
        if code or '2 passed; 0 failed; 0 ignored' not in value:
            print(value[-8000:])
            raise RuntimeError('Bounded response/client framing regression failed.')
        proof['synthetic_parser_and_cipher_regressions'] = 'PASS (two executed tests, no skipped tests)'
        code, value = execute('build', common + ['build', '--release', '--locked', '--no-default-features',
                                               '--bin', 'capy-live-probe'], 900)
        if code:
            print(value[-8000:])
            raise RuntimeError('Public probe compile failed.')
        exe = work / 'target/release' / ('capy-live-probe.exe' if args.variant == 'windows' else 'capy-live-probe')
        proof['probe_binary_sha256'] = sha(exe)
        code, value = execute('live', [str(exe)], 540)
        match = re.search(r'^CAPY_LIVE_RESULT=(\{[^\r\n]+\})$', value, re.M)
        if not match:
            raise RuntimeError('Actual final live network observations missing; inspect preserved output.')
        observation = json.loads(match[1])
        rows = observation['observations']
        if [(r['requested_dc'], r['media_route']) for r in rows] != EXPECTED:
            raise RuntimeError('Live case sequence differs.')
        for key in ('telegram_account_used', 'authorization_key_created', 'external_proxy_or_worker_configured',
                    'tls_validation_disabled', 'vpn_transition_tested', 'native_client_ui_tested'):
            if observation[key] is not False:
                raise RuntimeError('Probe scope differs.')
        proof['actual_public_network_observations'] = observation
        proof['live_returncode'] = code
        proof['successful_round_trips'] = sum(r['fresh_nonce_res_pq_verified'] for r in rows)
        for name, expected in original['prepared_sha256'].items():
            actual = (work / name).read_bytes()
            if name == 'Cargo.toml':
                if actual != cargo_original + suffix:
                    raise RuntimeError('Test-only manifest changed during build.')
            elif hashlib.sha256(actual).hexdigest() != expected:
                raise RuntimeError('Frozen production source changed: ' + name)
        if sha(work / 'Cargo.lock') != proof['cargo_lock_sha256']:
            raise RuntimeError('Frozen Cargo lock changed during build.')
        proof['production_core_sources_and_lock_unchanged'] = True
        proof['result'] = 'PASS' if not code and observation['result'] == 'PASS' else 'FAIL'
        print(json.dumps({'variant': args.variant, 'result': proof['result'],
                          'successful_round_trips': proof['successful_round_trips'], 'cases': len(rows)}))
        if proof['result'] != 'PASS':
            raise RuntimeError('Public connection case(s) did not return a validated fresh-nonce resPQ.')
    finally:
        (report / 'verification.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')

if __name__ == '__main__':
    main()
