# SPDX-License-Identifier: MIT
"""Resolve the frozen Windows normal/build graph and preserve original source/notices.

No client build, Rust build script, Telegram session or owner API key is used.
This is a source/notice supplement, not a whole-client license or security audit.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tomllib
import zipfile

HERE=Path(__file__).resolve().parent
CI=HERE.parent
TARGET='x86_64-pc-windows-msvc'
RUST='1.88.0'
REGISTRY='registry+https://github.com/rust-lang/crates.io-index'
def digest(raw):
    return hashlib.sha256(raw).hexdigest()
def normalized(path):
    return digest(path.read_bytes().replace(b'\r\n',b'\n'))

def inspect_crate(raw,name,version,checksum):
    """Read a checksum-bound crate without extracting files or accepting links."""
    if len(raw)>50*1024*1024 or digest(raw)!=checksum:
        raise ValueError('Registry source checksum/size differs: '+name)
    prefix=name+'-'+version+'/'
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as tar:
        members=tar.getmembers();seen=set();files={};total=0
        for entry in members:
            pp=PurePosixPath(entry.name)
            if entry.name in seen or not entry.name.startswith(prefix) or pp.is_absolute() or '..' in pp.parts or '\\' in entry.name or ':' in entry.name:
                raise ValueError('Unsafe/duplicate registry source member: '+name)
            seen.add(entry.name)
            if not (entry.isfile() or entry.isdir()) or entry.size<0 or entry.size>50*1024*1024:
                raise ValueError('Unreviewed registry member type/size: '+name)
            total+=entry.size
            if total>200*1024*1024 or len(seen)>20000:
                raise ValueError('Registry source expansion exceeds bound: '+name)
            if entry.isfile():
                files[entry.name[len(prefix):]]=entry
        def content(relative):
            pp=PurePosixPath(relative)
            if pp.is_absolute() or '..' in pp.parts or '\\' in relative or ':' in relative:
                raise ValueError('Unsafe archived notice path: '+name)
            entry=files.get(relative)
            if entry is None or entry.size>262144:
                raise ValueError('Missing/oversized source notice: '+name)
            handle=tar.extractfile(entry)
            if handle is None:
                raise ValueError('Unreadable archived notice: '+name)
            with handle:
                return handle.read()
        package=tomllib.loads(content('Cargo.toml').decode('utf-8'))['package']
        if package['name']!=name or package['version']!=version:
            raise ValueError('Registry manifest identity differs: '+name)
        expression=package.get('license')
        if not expression and not package.get('license-file'):
            raise ValueError('Missing registry license declaration: '+name)
        paths={p for p in files if any(re.match(r'^(licen[sc]e|copying|copyright|notice)(?:[._-]|$)',part,re.I) for part in PurePosixPath(p).parts)}
        if package.get('license-file'):
            paths.add(package['license-file'])
        if not paths or len(paths)>100:
            raise ValueError('Missing/excessive source notice inventory: '+name)
        notices={p:content(p) for p in sorted(paths)}
        for raw_notice in notices.values():
            raw_notice.decode('utf-8')
    return {'declared_license':expression,'license_file':package.get('license-file'),
            'source_members':len(files),'unpacked_bytes':total,
            'notice_sha256':{p:digest(data) for p,data in notices.items()}},notices

def main():
    if os.name!='nt' or os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_OS')!='Windows':
        raise ValueError('Run only on a disposable Windows CI runner.')
    pins=json.loads((CI/'windows-connection-native/source-provenance.json').read_text())
    core=CI/'connection'
    observed={p.relative_to(core).as_posix():normalized(p) for p in core.rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and 'test-results' not in p.parts}
    if observed!=pins['core_source_sha256']:
        raise ValueError('Frozen Windows core source inventory differs.')
    scratch=Path(os.environ['RUNNER_TEMP'])/'capy-windows-connection-source-inventory'
    if scratch.exists() or scratch.is_symlink():
        raise ValueError('Disposable inventory destination already exists.')
    scratch.mkdir(exist_ok=False)
    work=scratch/'prepared'
    spec=importlib.util.spec_from_file_location('capy_prepare_core',core/'prepare_core.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    prepared=module.prepare(work)
    if prepared!=pins['prepared_source'] or not prepared['cargo_lock_unchanged']:
        raise ValueError('Prepared source differs from the production Windows library.')
    cargo_home=scratch/'cargo-home';cargo_home.mkdir()
    env=dict(os.environ)
    for key in list(env):
        if key.startswith('CAPY_') or key in {'GH_TOKEN','GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN',
            'ACTIONS_ID_TOKEN_REQUEST_TOKEN','ACTIONS_ID_TOKEN_REQUEST_URL','CARGO_ENCODED_RUSTFLAGS'} or (key.startswith('CARGO_REGISTRIES_') and key.endswith('_TOKEN')):
            env.pop(key,None)
    env.update(CARGO_HOME=str(cargo_home),CARGO_TARGET_DIR=str(scratch/'target'),
               RUSTFLAGS='-C target-feature=+crt-static',CARGO_NET_OFFLINE='false')
    compiler=subprocess.run(['rustc','+'+RUST,'-vV'],cwd=work,env=env,capture_output=True,text=True,timeout=30)
    if compiler.returncode or not compiler.stdout.startswith('rustc '+RUST+' ') or 'host: '+TARGET not in compiler.stdout:
        raise ValueError('Expected pinned Rust and native Windows host.')
    command=['cargo','+'+RUST,'metadata','--locked','--no-default-features','--format-version','1','--filter-platform',TARGET]
    process=subprocess.run(command,cwd=work,env=env,capture_output=True,text=True,encoding='utf-8',errors='strict',timeout=300)
    if process.returncode:
        raise ValueError('Locked metadata request failed; environment and raw diagnostics are not printed.')
    if len(process.stdout.encode('utf-8'))>12*1024*1024:
        raise ValueError('Unexpected Cargo metadata size.')
    metadata=json.loads(process.stdout)
    resolve=metadata.get('resolve')
    if not resolve or not resolve.get('root'):
        raise ValueError('Missing normal library dependency root.')
    root=resolve['root'];nodes={n['id']:n for n in resolve['nodes']}
    packages={p['id']:p for p in metadata['packages']}
    if packages[root]['name']!='tglock' or any(f in nodes[root]['features'] for f in ('gui','cli')):
        raise ValueError('Unexpected root GUI/CLI features.')
    reached=set();pending=[root]
    while pending:
        identifier=pending.pop()
        if identifier in reached:
            continue
        reached.add(identifier)
        if identifier not in nodes:
            raise ValueError('Missing selected graph node.')
        for dep in nodes[identifier]['deps']:
            if any(kind['kind'] in (None,'build') for kind in dep['dep_kinds']):
                pending.append(dep['pkg'])
    lock_raw=(work/'Cargo.lock').read_bytes()
    if normalized(work/'Cargo.lock')!=pins['prepared_source']['prepared_sha256']['Cargo.lock']:
        raise ValueError('Metadata changed the frozen Cargo lock.')
    lock=tomllib.loads(lock_raw.decode('utf-8'))
    locked={(p['name'],p['version']):p for p in lock['package'] if p.get('source')==REGISTRY}
    if len(locked)!=464 or not 1<len(reached)<=150:
        raise ValueError('Unexpected frozen/selected package count.')
    report=HERE/'results'
    report.mkdir(exist_ok=False)
    records=[];attachments={};notice_parts=[
        'CapybaraGram built-in connection: Windows third-party notices\n',
        'Original notices from the frozen normal/build graph are preserved below. This does not replace the Telegram license or establish full client license compatibility.\n']
    for p in (core/'upstream/LICENSE',CI.parent/'LICENSE'):
        notice_parts+=['\n'+p.read_text(encoding='utf-8')+'\n']
    graph=[]
    for identifier in sorted(reached,key=lambda x:(packages[x]['name'],packages[x]['version'])):
        package=packages[identifier]
        deps=[dep for dep in nodes[identifier]['deps'] if dep['pkg'] in reached and any(k['kind'] in (None,'build') for k in dep['dep_kinds'])]
        graph.append({'package':package['name']+'@'+package['version'],'features':nodes[identifier]['features'],
                      'normal_build_dependencies':sorted(packages[d['pkg']]['name']+'@'+packages[d['pkg']]['version'] for d in deps)})
        if identifier==root:
            continue
        name=package['name'];version=package['version']
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',name) or not re.fullmatch(r'[0-9][0-9A-Za-z.+_-]{0,100}',version):
            raise ValueError('Unsafe registry package identifier.')
        pinned=locked.get((name,version))
        if package['source']!=REGISTRY or not pinned or not re.fullmatch(r'[a-f0-9]{64}',pinned['checksum']):
            raise ValueError('Selected dependency is outside the frozen public registry.')
        crate=Path(package['manifest_path']).resolve(strict=True).parent
        if not crate.is_relative_to(cargo_home/'registry/src'):
            raise ValueError('Selected crate escapes isolated registry source cache.')
        archive=crate.parent.parent.parent/'cache'/crate.parent.name/(name+'-'+version+'.crate')
        if archive.is_symlink() or not archive.resolve(strict=True).is_relative_to(cargo_home/'registry/cache') or archive.stat().st_size>50*1024*1024:
            raise ValueError('Unsafe original registry archive path.')
        raw=archive.read_bytes()
        details,notices=inspect_crate(raw,name,version,pinned['checksum'])
        if details['declared_license']!=package.get('license'):
            raise ValueError('Cargo license metadata differs from original archive.')
        for rel,value in notices.items():
            loose=crate/rel
            if loose.is_symlink() or not loose.resolve(strict=True).is_relative_to(crate) or loose.read_bytes()!=value:
                raise ValueError('Loose license source differs from original registry archive.')
        member='crates/'+archive.name
        if member in attachments:
            raise ValueError('Duplicate selected source archive.')
        attachments[member]=(archive,pinned['checksum'])
        records.append(dict(name=name,version=version,source=REGISTRY,archive_member=member,
                            archive_sha256=pinned['checksum'],archive_bytes=len(raw),**details))
        notice_parts+=['\n\n==== '+name+' '+version+' | '+str(details['declared_license'])+' ====\n']
        for rel,value in notices.items():
            notice_parts+=['\n-- '+rel+' --\n'+value.decode('utf-8')+'\n']
    notice=''.join(notice_parts).encode('utf-8')
    if len(notice)>4*1024*1024 or sum(p.stat().st_size for p,_ in attachments.values())>256*1024*1024:
        raise ValueError('Unexpected source/notice supplement size.')
    manifest={'format':1,'kind':'frozen-windows-connection-normal-build-source-inventory',
        'created_utc':datetime.now(timezone.utc).isoformat(),'inventory_head':os.environ['GITHUB_SHA'],
        'production_build_control_reference':'cb7f3187ab28a61129bd1f49243a0735eabd26ce',
        'production_build_run_reference':37201211653,'target':TARGET,'host':TARGET,'rust':RUST,
        'rustflags':env['RUSTFLAGS'],'prepared_source':prepared,'cargo_lock_sha256':digest(lock_raw),
        'full_lock_registry_entries':len(locked),'normal_build_registry_packages':len(records),
        'metadata_command':command,'selected_graph':graph,'packages':records,'notice_sha256':digest(notice),
        'dev_dependency_edges_included':False,'gui_cli_features_enabled':False,
        'client_or_vendor_build_scripts_executed':False,'actual_binary_link_inclusion_verified':False,
        'complete_client_source':False,'whole_client_license_compatibility_review':False,
        'limitations':['This resolves the frozen production-source metadata graph on the native Windows host; it does not independently establish linked binary inclusion.',
            'Cargo metadata may unify features requested by development declarations; normal/build reachable sources are preserved conservatively, not claimed as an exact release link graph.',
            'Build-only dependencies are preserved as well as normal dependencies.',
            'The Windows executable and the other Telegram/Qt/FFmpeg dependencies are separate artifacts.',
            'Registry checksum/notice identity is not a source vulnerability audit or a whole-client legal assessment.']}
    manifest_raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    readme='''# CapybaraGram — исходники сетевых Rust-зависимостей Windows

Это дополнение к сборке 37201211653. Подготовленный исходный код, Cargo.lock,
платформа x86_64-pc-windows-msvc, Rust 1.88.0, отключённые GUI/CLI и static CRT
совпадают с входами производственной сетевой библиотеки. Граф получен через
cargo metadata --locked на отдельном Windows runner. EXE здесь не собирался.

Включены исходные .crate-архивы выбранных normal/build-компонентов, точные
SHA-256 из замороженного lock, оригинальные тексты уведомлений, Cargo.lock,
SOURCE-MANIFEST.json и CONNECTION-NOTICES.txt. Контрольная сумма каждого архива
и соответствие его уведомлений оригинальному содержимому проверены. Зависимости
для сборки также сохранены; это не утверждение, что они все статически входят в EXE.

Управляющие исходники, tglock и инструкции находятся в основном комплекте.
Этот архив не заменяет источники остальных компонентов Telegram, Qt и FFmpeg
и не завершает проверку лицензий всего приложения. Код библиотек и build.rs
при инвентаризации не запускались. Авторизация Telegram и закрытые API-значения
не использовались. Проверка безопасности исходного кода сюда не входит.

Формат графа сверён с официальным Cargo Book:
https://doc.rust-lang.org/cargo/commands/cargo-metadata.html
'''
    (report/'SOURCE-MANIFEST.json').write_bytes(manifest_raw)
    (report/'CONNECTION-NOTICES.txt').write_bytes(notice)
    (report/'README-RU.md').write_text(readme,encoding='utf-8')
    bundle=report/'CapybaraGram-Windows-Connection-DependencySources.zip'
    extras={'SOURCE-MANIFEST.json':manifest_raw,'CONNECTION-NOTICES.txt':notice,'Cargo.lock':lock_raw,
            'README-RU.md':readme.encode('utf-8'),'tglock-LICENSE.txt':(core/'upstream/LICENSE').read_bytes(),
            'CapybaraGram-control-LICENSE.txt':(CI.parent/'LICENSE').read_bytes()}
    with zipfile.ZipFile(bundle,'x',compression=zipfile.ZIP_STORED) as z:
        for member,(path,_) in sorted(attachments.items()):
            z.write(path,member)
        for member,value in extras.items():
            z.writestr(member,value)
    with zipfile.ZipFile(bundle) as z:
        if z.testzip() is not None or set(z.namelist())!=set(attachments)|set(extras):
            raise ValueError('Source supplement CRC/membership differs.')
        for member,(_,checksum) in attachments.items():
            if digest(z.read(member))!=checksum:
                raise ValueError('Packed source archive checksum differs.')
        for member,value in extras.items():
            if z.read(member)!=value:
                raise ValueError('Packed notice/metadata bytes differ.')
    verification={'result':'PASS','inventory_head':os.environ['GITHUB_SHA'],'target':TARGET,
        'production_prepared_source_exact':True,'frozen_lock_unchanged':True,
        'normal_build_registry_packages':len(records),'source_members':sum(r['source_members'] for r in records),
        'notice_files':sum(len(r['notice_sha256']) for r in records),'notices_sha256':digest(notice),
        'all_original_crate_checksums_verified':True,'all_notice_bytes_match_original_crates':True,
        'bundle_sha256':digest(bundle.read_bytes()),'bundle_bytes':bundle.stat().st_size,
        'vendor_build_code_executed':False,'client_compiled':False,'complete_client_license_inventory':False}
    (report/'VERIFICATION.json').write_text(json.dumps(verification,indent=2)+'\n',encoding='utf-8')
    (report/'SHA256SUMS.txt').write_text(''.join(f'{digest(p.read_bytes())}  {p.name}\n' for p in
        (bundle,report/'SOURCE-MANIFEST.json',report/'CONNECTION-NOTICES.txt',report/'README-RU.md',report/'VERIFICATION.json')),encoding='ascii')
    print('CAPY_WINDOWS_CONNECTION_SOURCE_INVENTORY=PASS normal_build_packages='+str(len(records)),flush=True)

if __name__=='__main__':
    main()
