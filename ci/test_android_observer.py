# SPDX-License-Identifier: MIT
import ast,itertools,subprocess,tempfile,types,xml.etree.ElementTree as ET
from pathlib import Path

paths=[Path(__file__).resolve().parent/name for name in ['android_client_smoke.py','android_sandbox_smoke.py']]
for path in paths:
    module=ast.parse(path.read_text(encoding='utf-8'))
    function=next(n for n in module.body if isinstance(n,ast.FunctionDef) and n.name=='snapshot')
    code=compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec')
    for mode in ['always_missing','missing_then_fresh','malformed_then_fresh','idle_then_fresh','idle_last_then_fresh','always_idle']:
        with tempfile.TemporaryDirectory(prefix='capy-freshness-') as directory:
            fresh_paths=[]
            remote_files={'/sdcard/capy-ui.xml':'<hierarchy><node text="STALE"/></hierarchy>'}
            def run(args,**kwargs):
                if 'dump' in args:
                    remote=args[-1]
                    fresh_paths.append(remote)
                    if mode in ('idle_then_fresh','idle_last_then_fresh','always_idle') and len(fresh_paths) <= {'idle_then_fresh':5,'idle_last_then_fresh':11,'always_idle':12}[mode]:
                        return types.SimpleNamespace(stdout=b'ERROR: could not get idle state.',stderr=b'')
                    if len(fresh_paths)>1 and mode!='always_missing':
                        remote_files[remote]='<hierarchy><node text="FRESH"/></hierarchy>'
                    elif mode=='malformed_then_fresh':
                        remote_files[remote]='<broken'
                    return types.SimpleNamespace(stdout=b'ui dump returned zero',stderr=b'')
                return types.SimpleNamespace(stdout=b'\x89PNG\r\n\x1a\n',stderr=b'')
            def device(*args):
                if args[-1] not in remote_files:
                    raise subprocess.CalledProcessError(1,['cat',args[-1]])
                return remote_files[args[-1]]
            count=itertools.count(1)
            space=dict(run=run,device=device,adb='adb',report=Path(directory),ET=ET,subprocess=subprocess,
                       time=types.SimpleNamespace(monotonic_ns=lambda:next(count),sleep=lambda duration:None))
            exec(code,space)
            if mode in ('always_missing','always_idle'):
                try: space['snapshot']('test')
                except RuntimeError as error:
                    assert 'No fresh UI hierarchy' in str(error)
                else: raise AssertionError('Stale hierarchy was accepted')
                assert len(fresh_paths)==(12 if mode=='always_idle' else 4) and not (Path(directory)/'test.xml').exists()
            else:
                tree=space['snapshot']('test')
                assert tree.find('node').get('text')=='FRESH' and len(fresh_paths)=={'idle_then_fresh':6,'idle_last_then_fresh':12}.get(mode,2)
            assert len(fresh_paths)==len(set(fresh_paths))
            assert '/sdcard/capy-ui.xml' not in fresh_paths
            print(path.name,mode,'PASS')
print('Twelve observer regression cases passed: zero-exit dump without a new file never reuses stale UI; missing/malformed hierarchy retries require fresh output.')
