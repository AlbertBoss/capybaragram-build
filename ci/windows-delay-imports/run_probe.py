# SPDX-License-Identifier: MIT
"""Finite native MSVC/Rust case-mixed import reproducer, without owner inputs."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, os, subprocess

HERE = Path(__file__).resolve().parent
def run(args, cwd, env, timeout=120):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, timeout=timeout)
    return result, (result.stdout + result.stderr).decode('utf-8', errors='replace')

def main():
    assert os.name == 'nt'
    assert os.environ['VCToolsVersion'].startswith('14.44.')
    assert os.environ['WindowsSDKVersion'].rstrip('\\/') == '10.0.26100.0'
    assert os.environ['VSCMD_ARG_TGT_ARCH'] == 'x64'
    work = Path(os.environ['RUNNER_TEMP']) / 'capy-delay-import-probe'
    work.mkdir(exist_ok=False)
    report_dir = HERE / 'test-results'; report_dir.mkdir(exist_ok=False)
    env = dict(os.environ)
    for key in list(env):
        if key.startswith('CAPY_') or key in ('GH_TOKEN','GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN','ACTIONS_ID_TOKEN_REQUEST_TOKEN'):
            env.pop(key, None)
    version, output = run(['rustc','+1.88.0','-vV'],work,env)
    assert version.returncode == 0 and output.startswith('rustc 1.88.0 ')
    result, output = run(['rustc','+1.88.0','--edition=2021','--crate-type=staticlib',
                          '--target=x86_64-pc-windows-msvc','-C','panic=abort',
                          '-C','target-feature=+crt-static','-O',str(HERE/'raw_registry.rs'),
                          '-o',str(work/'registry_raw.lib')],work,env)
    (report_dir/'rust-compile.txt').write_text(output)
    assert result.returncode == 0, 'Rust probe compile failed'
    state = {'checked_utc':datetime.now(timezone.utc).isoformat(),'toolset':os.environ['VCToolsVersion'],
             'sdk':'10.0.26100.0','rust':'1.88.0','owner_credentials_used':False,
             'registry_mutated':False,'full_client_built':False,'live_accounts_accepted':False,
             'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.is_file()},
             'cases':[]}
    for name, cpp_only, delayed in [('cpp_delayed_control',True,True),
                                    ('mixed_delayed',False,True),('mixed_eager_fix',False,False)]:
        exe=work/(name+'.exe')
        args=['cl.exe','/nologo','/utf-8','/MT','/O2','/EHsc',str(HERE/'registry_probe.cpp'),
              '/Fo'+str(work/(name+'.obj')),'/Fe'+str(exe)]
        if cpp_only:args+=['/DCAPY_CPP_ONLY']
        else:args+=[str(work/'registry_raw.lib')]
        args+=['advapi32.lib','/link','/INCREMENTAL:NO']
        if delayed:args+=['delayimp.lib','/DELAYLOAD:advapi32.dll']
        compiled,output=run(args,work,env)
        (report_dir/(name+'-compile.txt')).write_text(output)
        assert compiled.returncode==0, name+' compilation failed'
        executed,output=run([str(exe)],work,env,30)
        (report_dir/(name+'-runtime.txt')).write_text(output)
        item={'name':name,'returncode':executed.returncode,
              'exit_hex':hex(executed.returncode&0xffffffff),
              'acceptance_marker':output.strip()=='CAPY_REGISTRY_IMPORT_PROBE=PASS',
              'exe_sha256':hashlib.sha256(exe.read_bytes()).hexdigest()}
        state['cases'].append(item)
        (report_dir/'verification.json').write_text(json.dumps(state,indent=2)+'\n')
        print(json.dumps(item),flush=True)
        if name!='mixed_delayed':
            assert executed.returncode==0 and item['acceptance_marker'], name+' runtime failed'
    state['baseline_crash_reproduced']=state['cases'][1]['exit_hex'] in ('0xc0000005','0xc000041d')
    state['eager_import_probe_passed']=True
    state['result']='PASS' if state['baseline_crash_reproduced'] else 'BASELINE_NOT_REPRODUCED'
    (report_dir/'verification.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state),flush=True)
    assert state['baseline_crash_reproduced'], 'No reproduced baseline; do not infer complete client fix'

if __name__=='__main__':main()
