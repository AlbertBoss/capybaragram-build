# SPDX-License-Identifier: MIT
"""Collect checksummed notices for normal/build dependencies of the ARM64 library."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tomllib

HERE=Path(__file__).resolve().parent
ALLOWED={'MIT','Apache-2.0','ISC','BSD-2-Clause','BSD-3-Clause','0BSD','Zlib','Unlicense',
         'CC0-1.0','CDLA-Permissive-2.0','BSL-1.0','Unicode-3.0','Unicode-DFS-2016'}

def checked_notice(crate,name,version,checksum,relative):
    # .cargo-checksum.json belongs to `cargo vendor`, not the ordinary registry cache.
    # Verify the cached original .crate archive instead of trusting loose cache files.
    archive=crate.parent.parent.parent/'cache'/crate.parent.name/(name+'-'+version+'.crate')
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_size>50*1048576:
        raise ValueError('Missing or unsafe cached registry archive: '+name)
    raw=archive.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=checksum:raise ValueError('Registry archive checksum differs: '+name)
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as tar:
        member=tar.getmember(name+'-'+version+'/'+relative)
        if not member.isfile() or member.size>262144:raise ValueError('Unsafe archived dependency notice')
        handle=tar.extractfile(member)
        if handle is None:raise ValueError('Unreadable archived dependency notice')
        with handle:return handle.read()

def build_notices(work,env):
    work=Path(work).resolve(strict=True)
    result=subprocess.run(['cargo','+1.88.0','metadata','--locked','--no-default-features',
        '--format-version','1','--filter-platform','aarch64-linux-android'],cwd=work,env=env,
        check=True,capture_output=True,text=True,encoding='utf-8',timeout=180)
    metadata=json.loads(result.stdout)
    resolve=metadata['resolve'];root=resolve['root']
    if not root:raise ValueError('Missing library dependency root')
    nodes={node['id']:node for node in resolve['nodes']}
    reached=set();pending=[root]
    while pending:
        identifier=pending.pop()
        if identifier in reached:continue
        reached.add(identifier)
        for dependency in nodes[identifier]['deps']:
            if any(kind['kind'] in (None,'build') for kind in dependency['dep_kinds']):pending.append(dependency['pkg'])
    packages={package['id']:package for package in metadata['packages']}
    locks={(entry['name'],entry['version']):entry for entry in tomllib.loads((work/'Cargo.lock').read_text())['package']}
    pieces=['CapybaraGram built-in connection: third-party notices\n',
            'This notice bundle preserves upstream licensing and copyright text. It does not replace the client license or source distribution.\n',
            'The combined Android candidate requires a compatible GPLv3 distribution path because the transport includes Apache-2.0 code. Public release remains gated on a complete source/notice/license package.\n']
    for path in (HERE.parent/'connection/upstream/LICENSE',HERE.parent.parent/'LICENSE'):
        pieces.append('\n'+path.read_text(encoding='utf-8')+'\n')
    index=[]
    for identifier in sorted(reached-{root},key=lambda value:(packages[value]['name'],packages[value]['version'])):
        package=packages[identifier];name=package['name'];version=package['version']
        locked=locks[(name,version)]
        if package['source']!='registry+https://github.com/rust-lang/crates.io-index' or locked.get('source')!=package['source']:
            raise ValueError('Non-registry transport dependency')
        expression=package.get('license')
        identifiers=set(re.findall(r'[A-Za-z0-9][A-Za-z0-9.+-]*',expression or ''))-{'OR','AND'}
        if not identifiers or not identifiers<=ALLOWED:raise ValueError('Unreviewed transport license: '+name+' '+str(expression))
        crate=Path(package['manifest_path']).resolve(strict=True).parent
        files=set()
        if package.get('license_file'):
            path=Path(package['license_file'])
            if not path.is_absolute():path=crate/path
            files.add(path)
        for path in crate.rglob('*'):
            if path.is_file() and any(re.match(r'^(licen[sc]e|copying|copyright|notice)(?:[._-]|$)',part,re.I)
                                      for part in path.relative_to(crate).parts):files.add(path)
        if not files or len(files)>100:raise ValueError('Missing or excessive dependency notices: '+name)
        pieces.append('\n\n==== '+name+' '+version+' | '+expression+' ====\n')
        reviewed={}
        for path in sorted(files):
            if path.is_symlink() or not path.resolve(strict=True).is_relative_to(crate) or path.stat().st_size>262144:
                raise ValueError('Unsafe dependency notice')
            relative=path.relative_to(crate).as_posix();raw=path.read_bytes();sha=hashlib.sha256(raw).hexdigest()
            if raw!=checked_notice(crate,name,version,locked['checksum'],relative):
                raise ValueError('Dependency notice content differs from registry archive')
            pieces.append('\n-- '+relative+' --\n'+raw.decode('utf-8')+'\n');reviewed[relative]=sha
        index.append({'name':name,'version':version,'license':expression,'archive_sha256':locked['checksum'],'notice_sha256':reviewed})
    text=''.join(pieces).encode('utf-8')
    if len(text)>4*1048576:raise ValueError('Dependency notice bundle exceeds limit')
    (work/'dependency-notices.json').write_text(json.dumps({'packages':index,'sha256':hashlib.sha256(text).hexdigest(),
         'dev_dependencies_included':False,'complete_client_license_review':False},indent=2)+'\n')
    return text
