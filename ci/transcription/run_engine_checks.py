# SPDX-License-Identifier: MIT
"""Actual pinned CPU speech inference and Android cross-compilation, not Telegram acceptance."""
import argparse,hashlib,json,os,re,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path,PurePosixPath
source=Path(__file__).resolve().parent
pins=json.loads((source/'source-pins.json').read_text())
out=Path(os.environ['RUNNER_TEMP'])/'capy-speech-native'
out.mkdir(exist_ok=False)
report=source/'test-results';report.mkdir(exist_ok=False)
def download(url,path,expected,maxbytes):
    digest=hashlib.sha256();count=0
    with urllib.request.urlopen(url,timeout=90) as response,path.open('xb') as target:
        while True:
            chunk=response.read(1048576)
            if not chunk:break
            count+=len(chunk)
            if count>maxbytes:raise ValueError('Pinned download exceeds limit')
            digest.update(chunk);target.write(chunk)
    if digest.hexdigest()!=expected:raise ValueError('Pinned dependency hash mismatch')
    return count
archive=out/'whisper.zip'
download('https://codeload.github.com/'+pins['repository']+'/zip/'+pins['commit'],archive,pins['zip_sha256'],80*1048576)
with zipfile.ZipFile(archive) as z:
    prefix=z.namelist()[0].split('/')[0]+'/'
    for entry in z.infolist():
        if entry.is_dir():continue
        p=PurePosixPath(entry.filename.removeprefix(prefix))
        if not entry.filename.startswith(prefix) or p.is_absolute() or '..' in p.parts or (entry.external_attr>>16)&0o170000==0o120000:
            raise ValueError('Unsafe pinned archive')
        if entry.file_size>100*1048576:raise ValueError('Oversized source entry')
        target=out/'whisper'/str(p);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(entry))
build=out/'build'
parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['cpu','android']);parser.add_argument('--install-to',type=Path)
arguments=parser.parse_args();kind=arguments.kind
if arguments.install_to is not None and kind!='android':raise ValueError('Install is Android-only')
args=['cmake','-S',str(source),'-B',str(build),'-DCAPY_WHISPER_SOURCE='+str(out/'whisper'),'-DCMAKE_BUILD_TYPE=Release']
if kind=='android':
    sdk=Path(os.environ['ANDROID_HOME']);ndk=sdk/'ndk/27.2.12479018'
    args+=['-DCMAKE_TOOLCHAIN_FILE='+str(ndk/'build/cmake/android.toolchain.cmake'),'-DANDROID_ABI=arm64-v8a','-DANDROID_PLATFORM=android-23','-DANDROID_STL=c++_static','-G','Ninja']
subprocess.run(args,check=True,timeout=120)
target='capy_voice_jni' if kind=='android' else 'capy_voice_runtime_test'
subprocess.run(['cmake','--build',str(build),'--config','Release','--target',target,'--parallel','2'],check=True,timeout=900)
if kind=='cpu':
    model=out/'tiny.bin';m=pins['model']
    size=download('https://huggingface.co/'+m['repository']+'/resolve/'+m['revision']+'/'+m['file'],model,m['sha256'],m['bytes'])
    assert size==m['bytes']
    candidates=list(build.rglob('capy_voice_runtime_test.exe' if os.name=='nt' else 'capy_voice_runtime_test'))
    assert len(candidates)==1
    result=subprocess.run([str(candidates[0]),str(model),str(out/'whisper/samples/jfk.wav')],capture_output=True,text=True,check=True,timeout=180)
    (report/'engine-result.txt').write_text(result.stdout+result.stderr)
    assert 'CAPY_OFFLINE_ENGINE=PASS' in result.stdout
    print(result.stdout,flush=True)
else:
    libraries=list(build.rglob('libcapy_voice_jni.so'));assert len(libraries)==1
    data=libraries[0].read_bytes();assert data[:4]==b'\x7fELF' and data[4]==2 and int.from_bytes(data[18:20],'little')==183
    readelf=ndk/'toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf'
    dynamic=subprocess.run([str(readelf),'-d',str(libraries[0])],capture_output=True,text=True,check=True,timeout=30).stdout
    needed=set(re.findall(r'Shared library: \[([^\]]+)\]',dynamic))
    if not needed<=set(['libc.so','libm.so','libdl.so','liblog.so','libandroid.so']):raise ValueError('Unexpected JNI runtime dependency')
    phoff=int.from_bytes(data[32:40],'little');phsize=int.from_bytes(data[54:56],'little');phnum=int.from_bytes(data[56:58],'little')
    if phsize<56 or phnum>128 or phoff+phsize*phnum>len(data):raise ValueError('Invalid ELF program table')
    alignments=[int.from_bytes(data[phoff+i*phsize+48:phoff+i*phsize+56],'little') for i in range(phnum)
                if int.from_bytes(data[phoff+i*phsize:phoff+i*phsize+4],'little')==1]
    if not alignments or min(alignments)<16384:raise ValueError('JNI requires 16 KiB load alignment')
    if arguments.install_to is not None:
        client=arguments.install_to.resolve(strict=True)
        head=subprocess.run(['git','-C',str(client),'rev-parse','HEAD'],capture_output=True,text=True,check=True,timeout=30).stdout.strip()
        if head!='62b56a07ca7e30e39f7fd00a6728d6bbd716ca1c':raise ValueError('Wrong production Android revision')
        target=client/'TMessagesProj/jni/arm64-v8a/libcapy_voice_jni.so'
        if target.exists() or target.is_symlink() or not target.resolve().is_relative_to(client):raise ValueError('JNI destination already exists or escapes client')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(libraries[0],target)
        if target.read_bytes()!=data:raise ValueError('Installed JNI bytes differ')
    (report/'engine-result.txt').write_text('CAPY_ANDROID_JNI=COMPILED ARM64 16KiB-aligned\n')
result={'kind':kind,'source_commit':pins['commit'],'source_archive_sha256':pins['zip_sha256'],
        'model':pins['model'] if kind=='cpu' else None,'result':'PASS','client_ui_integrated':False,
        'russian_voice_accuracy_tested':False,'offline_network_packet_capture_performed':False,
        'our_source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}}
(report/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
