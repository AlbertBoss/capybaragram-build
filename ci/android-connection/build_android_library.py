# SPDX-License-Identifier: MIT
"""Build the frozen ARM64 transport into a pinned disposable Telegram checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from prepare_android_core import prepare, digest

HERE=Path(__file__).resolve().parent
RUST='1.88.0'
SHA='62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('client',type=Path);args=parser.parse_args()
    client=args.client.resolve(strict=True)
    head=subprocess.run(['git','-C',str(client),'rev-parse','HEAD'],check=True,capture_output=True,text=True,timeout=30).stdout.strip()
    if head!=SHA:raise ValueError('Wrong Android client revision')
    destination=client/'TMessagesProj/jni/arm64-v8a/libcapy_connection_jni.so'
    notice=client/'TMessagesProj/src/main/assets/capy_connection_notices.txt'
    for path in (destination,notice):
        if path.exists() or path.is_symlink() or not path.resolve().is_relative_to(client):
            raise ValueError('Connection install destination already exists or escapes checkout')
    work=Path(os.environ['RUNNER_TEMP'])/'capy-android-connection-production'
    manifest=prepare(work,False)
    env=dict(os.environ)
    for name in list(env):
        if name.startswith('CAPY_') or name in {'GH_TOKEN','GITHUB_TOKEN','ACTIONS_RUNTIME_TOKEN',
                'ACTIONS_ID_TOKEN_REQUEST_TOKEN','ACTIONS_ID_TOKEN_REQUEST_URL'}:env.pop(name,None)
    env.pop('RUSTFLAGS',None);env.pop('CARGO_ENCODED_RUSTFLAGS',None)
    env['CARGO_TARGET_DIR']=str(work/'target');env['CARGO_BUILD_JOBS']='2'

    def run(command,timeout=120,additions=None):
        result=subprocess.run(list(map(str,command)),cwd=work,env=dict(env,**(additions or {})),
                              capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        if result.returncode:
            print((result.stdout+result.stderr)[-12000:],flush=True)
            raise RuntimeError('ARM64 transport build command failed: '+str(command[0]))
        return result.stdout

    if not run(['rustc','+'+RUST,'--version'],30).startswith('rustc '+RUST+' '):raise ValueError('Wrong Rust compiler')
    ndk=Path(os.environ['ANDROID_HOME'])/'ndk/27.2.12479018'
    if not re.search(r'^Pkg.Revision\s*=\s*27\.2\.12479018\s*$',(ndk/'source.properties').read_text(),re.M):
        raise ValueError('Wrong Android NDK')
    tools=ndk/'toolchains/llvm/prebuilt/linux-x86_64/bin'
    additions={'CARGO_TARGET_AARCH64_LINUX_ANDROID_LINKER':str(tools/'aarch64-linux-android23-clang'),
               'CC_aarch64_linux_android':str(tools/'aarch64-linux-android23-clang'),
               'AR_aarch64_linux_android':str(tools/'llvm-ar'),
               'CFLAGS_aarch64_linux_android':'-fPIC','RUSTFLAGS':'-C relocation-model=pic'}
    run(['cargo','+'+RUST,'build','--locked','--no-default-features','--lib','--release',
         '--target','aarch64-linux-android'],900,additions)
    build=work/'jni-arm64-v8a'
    run(['cmake','-G','Ninja','-S',HERE,'-B',build,'-DCMAKE_BUILD_TYPE=Release',
         '-DCMAKE_TOOLCHAIN_FILE='+str(ndk/'build/cmake/android.toolchain.cmake'),
         '-DANDROID_ABI=arm64-v8a','-DANDROID_PLATFORM=android-23','-DANDROID_STL=c++_static',
         '-DCAPY_CONNECTION_LIBRARY='+str(work/'target/aarch64-linux-android/release/libtglock.a'),
         '-DCAPY_CONNECTION_HEADER_DIR='+str(HERE.parent/'connection')])
    run(['cmake','--build',build,'--parallel','2'],180)
    binary=(build/'libcapy_connection_jni.so').read_bytes()
    if binary[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(binary[18:20],'little')!=183:raise ValueError('Wrong ARM64 JNI')
    phoff=int.from_bytes(binary[32:40],'little');phsize=int.from_bytes(binary[54:56],'little');phnum=int.from_bytes(binary[56:58],'little')
    if phsize<56 or phnum>128 or phoff+phsize*phnum>len(binary):raise ValueError('Invalid ELF table')
    align=[int.from_bytes(binary[phoff+i*phsize+48:phoff+i*phsize+56],'little') for i in range(phnum)
           if int.from_bytes(binary[phoff+i*phsize:phoff+i*phsize+4],'little')==1]
    if not align or min(align)<16384:raise ValueError('Connection JNI must support 16 KiB pages')
    imports=set(re.findall(r'Shared library: \[([^\]]+)\]',run([tools/'llvm-readelf','-d',build/'libcapy_connection_jni.so'],30)))
    if not imports<={'libc.so','libm.so','libdl.so','liblog.so','libandroid.so'}:raise ValueError('Unexpected JNI dependency')
    symbols=run([tools/'llvm-nm','-D','--defined-only',build/'libcapy_connection_jni.so'],30)
    if any('Java_org_capybaragram_connection_NativeTunnel_'+method not in symbols for method in ('start','status','stop')):
        raise ValueError('Required JNI symbols missing')
    for name,sha in manifest['prepared_sha256'].items():
        if digest((work/name).read_bytes())!=sha:raise ValueError('Prepared source changed during build')
    from connection_notices import build_notices
    notices=build_notices(work,env)
    destination.parent.mkdir(parents=True,exist_ok=True);notice.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(binary);notice.write_bytes(notices)
    if destination.read_bytes()!=binary or notice.read_bytes()!=notices:raise ValueError('Installed JNI/notice bytes differ')
    report={'result':'COMPILED','client_revision':head,'abi':'arm64-v8a','rust':RUST,
            'cargo_lock_sha256':digest((work/'Cargo.lock').read_bytes()),'source':manifest,
            'jni_sha256':hashlib.sha256(binary).hexdigest(),'jni_bytes':len(binary),'minimum_load_alignment':min(align),
            'imports':sorted(imports),'notice_sha256':hashlib.sha256(notices).hexdigest(),
            'builder_sha256':digest(Path(__file__).read_bytes()),'live_telegram_tested':False,'client_ui_compiled':False}
    (work/'installation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: frozen ARM64 JNI installed with dependency notices; application compile and live tests remain.')

if __name__=='__main__':main()
