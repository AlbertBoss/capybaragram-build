# SPDX-License-Identifier: MIT
"""Disposable Linux source build with exact inputs and offline compiler children."""
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import ctypes
import ctypes.util
import errno
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile

HERE=Path(__file__).resolve().parent
MANIFEST_SHA='35849a9e39e7f95161e060d44c49c1ca83cfaf242bec151362eb871fbb566d56'
ALLOWED_SYSTEM_LIBS={'libstdc++.so.6','libm.so.6','libgcc_s.so.1','libc.so.6','libpthread.so.0','libdl.so.2'}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def download(record, path):
    start=time.monotonic();digest=hashlib.sha256();size=0
    request=urllib.request.Request(record['archive_url'],headers={'User-Agent':'CapybaraGram-source-admission'})
    with urllib.request.urlopen(request,timeout=30) as response,path.open('xb') as out:
        assert response.url==record['archive_url']
        while chunk:=response.read(65536):
            size+=len(chunk)
            assert size<=record['archive_bytes'] and time.monotonic()-start<240
            digest.update(chunk);out.write(chunk)
    assert size==record['archive_bytes'] and digest.hexdigest()==record['archive_sha256']

def extract_regular_sources(name, record, archive, destination):
    """Never create archive links or extract training/examples/downloaders for Kaldi/API."""
    seen=set();size=0;copied=0;links=0
    with zipfile.ZipFile(archive) as z:
        entries=z.infolist()
        assert len(entries)<30000 and z.testzip() is None
        for entry in entries:
            parts=PurePosixPath(entry.filename).parts
            assert parts and parts[0]==record['archive_root']
            assert not PurePosixPath(entry.filename).is_absolute() and '..' not in parts
            assert '\\' not in entry.filename and ':' not in entry.filename and not entry.flag_bits&1
            if entry.is_dir():continue
            rel='/'.join(parts[1:]);assert rel and rel not in seen;seen.add(rel)
            size+=entry.file_size;assert size<=record['uncompressed_bytes']
            mode=entry.external_attr>>16
            if stat.S_ISLNK(mode):
                links+=1;continue
            assert stat.S_IFMT(mode) in (stat.S_IFREG,0)
            if name in ('api','kaldi') and not (rel.startswith('src/') or rel=='COPYING'):
                continue
            target=destination/rel
            assert target.resolve().is_relative_to(destination.resolve())
            target.parent.mkdir(parents=True,exist_ok=True)
            raw=z.read(entry)
            if rel in record['selected_review_files']:
                assert sha(raw)==record['selected_review_files'][rel]['sha256']
            with target.open('xb') as out:out.write(raw)
            target.chmod(0o755 if mode&0o111 else 0o644)
            copied+=1
    assert size==record['uncompressed_bytes'] and len(seen)==record['git_blobs_verified']
    assert links==record['symlink_count']
    return {'regular_files_extracted':copied,'symlinks_skipped':links,'archive_sha256':record['archive_sha256']}

def deny_build_network():
    """Filter inherited by compilers; compiler exec remains allowed and is required."""
    name=ctypes.util.find_library('seccomp');assert name
    lib=ctypes.CDLL(name)
    lib.seccomp_init.argtypes=[ctypes.c_uint32];lib.seccomp_init.restype=ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
    lib.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint];lib.seccomp_rule_add.restype=ctypes.c_int
    lib.seccomp_load.argtypes=[ctypes.c_void_p];lib.seccomp_load.restype=ctypes.c_int
    lib.seccomp_release.argtypes=[ctypes.c_void_p];lib.seccomp_release.restype=None
    ctx=lib.seccomp_init(0x7fff0000);assert ctx
    denied=[]
    try:
        for syscall in ('socket','socketpair','connect','bind','listen','accept','accept4','sendto','sendmsg','sendmmsg','recvfrom','recvmsg','recvmmsg'):
            number=lib.seccomp_syscall_resolve_name(syscall.encode())
            if number>=0:
                assert lib.seccomp_rule_add(ctx,0x00050000|errno.EPERM,number,0)==0
                denied.append(syscall)
        assert {'socket','connect'}<=set(denied) and lib.seccomp_load(ctx)==0
    finally:lib.seccomp_release(ctx)
    for family in (socket.AF_INET,socket.AF_UNIX):
        try:s=socket.socket(family,socket.SOCK_STREAM)
        except OSError as failure:assert failure.errno==errno.EPERM
        else:
            s.close();raise AssertionError('Build network prohibition absent')
    return {'verified_before_vendor_build':True,'denied_syscalls':denied,'compiler_exec_allowed':True,
            'full_filesystem_isolation':False}

def run():
    assert sys.platform=='linux' and os.environ.get('GITHUB_ACTIONS')=='true' and os.geteuid()!=0
    assert platform.machine()=='x86_64'
    raw=(HERE/'sources.json').read_bytes();assert sha(raw)==MANIFEST_SHA
    inputs=json.loads(raw)['source_inputs'];assert set(inputs)=={'api','kaldi','openfst','openblas','clapack'}
    stage=Path(os.environ['RUNNER_TEMP'])/'capy-vosk-source-build'
    stage.mkdir(exist_ok=False)
    reports=Path(os.environ['GITHUB_WORKSPACE'])/'vosk-source-build-report'
    reports.mkdir(exist_ok=False)
    state={'created_utc':datetime.now(timezone.utc).isoformat(),'source_manifest_sha256':MANIFEST_SHA,
           'production_admitted':False,'owner_input_used':False,'source_build_completed':False,
           'full_security_audit':False,'phase':'downloads','steps':[],'extraction':{}}
    def save():
        temp=reports/'source-build.tmp';temp.write_text(json.dumps(state,indent=2)+'\n');temp.replace(reports/'source-build.json')
    save()
    for name,r in inputs.items():
        archive=stage/(name+'.zip');download(r,archive)
        source=stage/name;source.mkdir()
        state['extraction'][name]=extract_regular_sources(name,r,archive,source)
        save()
    state['host_packages']=subprocess.run(['dpkg-query','-W','-f=${Package} ${Version}\n','gcc-12','g++-12','make','cmake','autoconf','automake','libtool','libseccomp2'],capture_output=True,check=True,timeout=15).stdout.decode().splitlines()
    state['host_package_versions_pinned']=False
    state['tool_versions']={name:subprocess.run([name,'--version'],capture_output=True,check=True,timeout=15).stdout.decode().splitlines()[0] for name in ('gcc-12','g++-12','cmake','make')}
    state['sandbox']=deny_build_network();save()
    # Whitelist child environment; no GitHub credentials/output files or owner secrets.
    env={'PATH':os.environ['PATH'],'LANG':'C.UTF-8','LC_ALL':'C.UTF-8','TMPDIR':str(stage),
         'CC':'gcc-12','CXX':'g++-12','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
    deadline=time.monotonic()+80*60
    def step(label,args,cwd,seconds,extra=None):
        state['phase']=label;save();print('Source build phase: '+label,flush=True)
        log=reports/(str(len(state['steps'])).zfill(2)+'-'+label+'.txt')
        start=time.monotonic();timeout=min(seconds,max(1,deadline-start))
        with log.open('xb') as output:
            child=subprocess.Popen(args,cwd=cwd,env=dict(env,**(extra or {})),stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            timed_out=False
            try:result=child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True;os.killpg(child.pid,signal.SIGKILL);result=child.wait(timeout=10)
        state['steps'].append({'phase':label,'argv':args,'returncode':result,'wall_seconds':round(time.monotonic()-start,3),
                               'timed_out':timed_out,'log_bytes':log.stat().st_size,'log_sha256':sha(log.read_bytes())})
        save()
        assert log.stat().st_size<20*1024*1024
        assert result==0 and not timed_out,'Source build phase failed: '+label+'; no implicit retry'
    prefix=stage/'local';prefix.mkdir()
    blas_args=['ONLY_CBLAS=1','NO_LAPACK=1','NO_LAPACKE=1','NO_FORTRAN=1','USE_THREAD=0','USE_LOCKING=1',
               'NUM_THREADS=1','DYNAMIC_ARCH=0','TARGET=NEHALEM','BINARY=64','CC=gcc-12','HOSTCC=gcc-12',
               'PREFIX='+str(prefix)]
    step('openblas',['make','-j2',*blas_args,'all'],stage/'openblas',900)
    step('openblas-install',['make','-j2',*blas_args,'install'],stage/'openblas',120)
    clapack_build=stage/'clapack-build'
    step('clapack-configure',['cmake','-S',str(stage/'clapack'),'-B',str(clapack_build),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_C_COMPILER=gcc-12','-DCMAKE_POSITION_INDEPENDENT_CODE=ON','-DBUILD_TESTING=OFF'],stage,90)
    step('clapack',['cmake','--build',str(clapack_build),'--target','f2c','blas','lapack','--parallel','2'],stage,900)
    for component in ('f2c','blas','lapack'):
        libraries=list(clapack_build.rglob('lib'+component+'.a'));assert len(libraries)==1
        shutil.copyfile(libraries[0],prefix/'lib'/libraries[0].name)
    # The CBLAS-only OpenBLAS intentionally has no LAPACKE. Use real CLAPACK
    # declarations together with its actual f2c implementation, not a fake header.
    for header in ('f2c.h','clapack.h'):
        original=stage/'clapack/INCLUDE'/header
        expected=inputs['clapack']['selected_review_files']['INCLUDE/'+header]['sha256']
        assert sha(original.read_bytes())==expected
        shutil.copyfile(original,prefix/'include'/header)
    step('openfst-autoreconf',['autoreconf','-fi'],stage/'openfst',120)
    step('openfst-configure',['bash','./configure','--prefix='+str(prefix),'--enable-static','--enable-shared','--with-pic','--disable-bin','--enable-lookahead-fsts','--enable-ngram-fsts'],stage/'openfst',180,{'CXXFLAGS':'-O2 -g0 -DFST_NO_DYNAMIC_LINKING'})
    step('openfst',['make','-j2'],stage/'openfst',1800)
    step('openfst-install',['make','-j2','install'],stage/'openfst',120)
    kaldi=stage/'kaldi/src'
    step('kaldi-configure',['bash','./configure','--shared','--use-cuda=no','--mathlib=OPENBLAS_CLAPACK','--openblas-clapack-root='+str(prefix),'--fst-root='+str(prefix),'--fst-version=1.8.0'],kaldi,120,{'CXXFLAGS':'-O2 -g0 -DFST_NO_DYNAMIC_LINKING'})
    # This pinned configure selects linux_openblas.mk even for OPENBLAS_CLAPACK.
    # Correct the generated macro for CBLAS + real CLAPACK on this Linux host.
    generated=kaldi/'kaldi.mk';original=generated.read_text()
    assert original.count('-DHAVE_OPENBLAS')==1 and '-DHAVE_CLAPACK' not in original
    corrected=original.replace('-DHAVE_OPENBLAS','-DHAVE_CLAPACK')
    generated.write_text(corrected)
    state['math_configuration']={'mode':'CBLAS-only OpenBLAS plus CLAPACK/f2c',
        'generated_kaldi_mk_before_sha256':sha(original.encode()),
        'generated_kaldi_mk_after_sha256':sha(corrected.encode()),
        'have_openblas_macro':False,'have_clapack_macro':True,'dummy_lapacke_header':False}
    save()
    smoke=stage/'math-abi.cpp'
    smoke.write_text('''#include "matrix/kaldi-blas.h"
#include <cmath>
#include <cstdio>
static_assert(sizeof(KaldiBlasInt)==sizeof(int), "Kaldi/CLAPACK integer ABI");
int main() {
  const double a[]={1,2,3,4}, b[]={5,6,7,8}; double c[4]={};
  cblas_dgemm(CblasRowMajor,CblasNoTrans,CblasNoTrans,2,2,2,1.0,a,2,b,2,0.0,c,2);
  const double expected[]={19,22,43,50};
  for(int i=0;i<4;++i) if(std::fabs(c[i]-expected[i])>1e-10) return 11;
  integer n=2,nrhs=1,lda=2,ldb=2,info=-1,pivots[2]={};
  double matrix[]={3,1,1,2}, rhs[]={9,8};
  dgesv_(&n,&nrhs,matrix,&lda,pivots,rhs,&ldb,&info);
  if(info!=0 || std::fabs(rhs[0]-2)>1e-10 || std::fabs(rhs[1]-3)>1e-10) return 12;
  std::puts("CAPY_CBLAS_CLAPACK_ABI=PASS");return 0;
}
''')
    math_libs=[str(prefix/'lib'/('lib'+name+'.a')) for name in ('openblas','lapack','blas','f2c')]
    smoke_exe=stage/'math-abi'
    step('math-abi-build',['g++-12','-std=c++17','-DHAVE_CLAPACK','-I'+str(kaldi),
        '-I'+str(prefix/'include'),str(smoke),*math_libs,'-lm','-lpthread','-ldl','-o',str(smoke_exe)],stage,90)
    step('math-abi-run',[str(smoke_exe)],stage,15)
    state['math_configuration']['actual_cblas_and_clapack_abi_smoke']='PASS';save()
    step('kaldi',['make','-j2','online2','lm','rnnlm'],kaldi,2400)
    native_dir=stage/'native';native_dir.mkdir()
    step('vosk-api',['make','-j2','KALDI_ROOT='+str(stage/'kaldi'),'OPENFST_ROOT='+str(prefix),'OPENBLAS_ROOT='+str(prefix),
                     'OUTDIR='+str(native_dir),'CXX=g++-12','USE_SHARED=0','HAVE_CUDA=0',
                     'EXTRA_CFLAGS=-DHAVE_CLAPACK -DKALDI_DOUBLEPRECISION=0 -O2 -g0',
                     'EXTRA_LDFLAGS=-lm -lpthread -ldl -Wl,-z,defs,-z,relro,-z,now,-soname,libvosk.so'],stage/'api/src',240)
    native=native_dir/'libvosk.so';raw=native.read_bytes()
    assert raw[:5]==b'\x7fELF\x02' and raw[18:20]==b'\x3e\x00'
    dynamic=subprocess.run(['readelf','-d',str(native)],capture_output=True,check=True,timeout=15).stdout.decode()
    symbols=subprocess.run(['nm','-D','--defined-only',str(native)],capture_output=True,check=True,timeout=15).stdout.decode()
    needed=re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic)
    assert needed and set(needed)<=ALLOWED_SYSTEM_LIBS and 'libvosk.so' in dynamic
    for symbol in ('vosk_model_new','vosk_model_free','vosk_recognizer_new','vosk_recognizer_free','vosk_recognizer_accept_waveform','vosk_recognizer_result','vosk_recognizer_final_result'):
        assert re.search(r'\b'+symbol+r'\s*$',symbols,re.M)
    state.update(phase='complete',source_build_completed=True,native_sha256=sha(raw),native_bytes=len(raw),
                 needed_system_libraries=needed,source_manifest_sha256=MANIFEST_SHA,
                 private_data_used=False,platform_library_accepted=False,production_admitted=False)
    save();print(json.dumps({'source_build_completed':True,'native_sha256':sha(raw),'production_admitted':False}),flush=True)

if __name__=='__main__':run()
