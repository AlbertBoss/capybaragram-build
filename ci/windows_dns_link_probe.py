# SPDX-License-Identifier: MIT
"""Check the three failed DNS imports before a costly complete client build."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

GUARD = 'if errorlevel 1 (exit /b 1) else if not errorlevel 0 (exit /b 1)'
SYMBOLS = ('DnsQueryEx', 'DnsWriteQuestionToBuffer_W', 'DnsExtractRecordsFromMessage_W')


def run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, timeout=90)


def native():
    if os.name != 'nt' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Native probe is restricted to the disposable Windows CI runner.')
    root = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='capy-dns-link-', dir=root) as temp:
        directory = Path(temp).resolve(strict=True)
        assert directory.is_relative_to(root)
        results = []
        for block in (False, True):
            for code in (0, 1, -1):
                body = f'cmd.exe /d /c exit /b {code}\n{GUARD}\n'
                if block:
                    body = 'if "x"=="x" (\n' + body + ')\n'
                path = directory / f'guard-{block}-{code}.cmd'
                path.write_bytes(('@echo off\n' + body + 'exit /b 0\n').replace('\n', '\r\n').encode('ascii'))
                result = run(['cmd.exe', '/d', '/c', str(path)])
                expected = 0 if code == 0 else 1
                assert result.returncode == expected, 'Signed exit guard did not reject a child failure.'
                results.append({'inside_block': block, 'child_exit': code, 'wrapper_exit': result.returncode})
        cpp = directory / 'probe.cpp'
        cpp.write_text('''#include <windows.h>
#include <windns.h>
static decltype(&DnsQueryEx) volatile query = &DnsQueryEx;
static decltype(&DnsWriteQuestionToBuffer_W) volatile write_query = &DnsWriteQuestionToBuffer_W;
static decltype(&DnsExtractRecordsFromMessage_W) volatile extract = &DnsExtractRecordsFromMessage_W;
int main() { return (query && write_query && extract) ? 0 : 2; }
''', encoding='ascii')
        compiled = run(['cl.exe', '/nologo', '/c', '/std:c++17', '/MT', '/W4', '/WX',
                        '/D_WIN32_WINNT=0x0602', str(cpp), '/Foprobe.obj'], directory)
        assert compiled.returncode == 0, 'DNS import probe did not compile.'
        missing = run(['cl.exe', '/nologo', 'probe.obj', '/Feprobe-missing.exe', '/link', '/MACHINE:X64'], directory)
        output = (missing.stdout + missing.stderr).decode('utf-8', errors='replace')
        assert missing.returncode != 0 and all(s in output for s in SYMBOLS), 'Missing-library control did not reproduce all three unresolved imports.'
        linked = run(['cl.exe', '/nologo', 'probe.obj', '/Feprobe.exe', '/link', 'Dnsapi.lib', '/MACHINE:X64', '/WX'], directory)
        assert linked.returncode == 0, 'Explicit Dnsapi.lib did not resolve the failed imports.'
        executed = run([str(directory / 'probe.exe')], directory)
        assert executed.returncode == 0, 'DNS import probe executable failed to load.'
        report = {'dns_imports': list(SYMBOLS), 'missing_import_library_control': 'PASS',
                  'explicit_dnsapi_link_and_load': 'PASS', 'signed_cmd_exit_guard_cases': results,
                  'dns_queries_sent': False, 'whole_client_exe_link_verified': False}
        path = root / 'capy-dns-link-preflight.json'
        path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print('CAPY_DNS_IMPORT_AND_SIGNED_EXIT_PREFLIGHT=PASS')


if __name__ == '__main__':
    if sys.argv[1:] == ['--native']:
        native()
    elif not sys.argv[1:]:
        assert os.name == 'nt' and os.environ.get('GITHUB_ACTIONS') == 'true'
        dev = Path(os.environ['CAPY_VSDEVCMD']).resolve(strict=True)
        assert dev.name == 'VsDevCmd.bat'
        temp = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)
        batch = temp / 'capy-dns-link-probe.cmd'
        batch.write_bytes(('@echo off\r\ncall "' + str(dev) + '" -no_logo -arch=x64 -host_arch=x64 -winsdk=10.0.26100.0 -vcvars_ver=14.44\r\n'
                          + GUARD + '\r\n"' + sys.executable + '" "' + str(Path(__file__).resolve()) + '" --native\r\n'
                          + GUARD + '\r\nexit /b 0\r\n').encode('utf-8'))
        result = run(['cmd.exe', '/d', '/c', str(batch)])
        if result.returncode:
            raise RuntimeError('DNS library/exit-code preflight failed; expensive build not started.')
        assert b'CAPY_DNS_IMPORT_AND_SIGNED_EXIT_PREFLIGHT=PASS' in result.stdout
        print('CAPY_DNS_IMPORT_AND_SIGNED_EXIT_PREFLIGHT=PASS')
    else:
        raise SystemExit('Unexpected arguments.')
