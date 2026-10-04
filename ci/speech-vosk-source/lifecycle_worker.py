# SPDX-License-Identifier: MIT
"""Two model release/reload cycles in one process, one public nine-second clip."""
from pathlib import Path
import ctypes
import hashlib
import importlib.util
import json
import resource
import sys
import time

CONTROL=Path(__file__).resolve().parent.parent.parent

def run(config_file):
    assert sys.platform=='linux'
    config=json.loads(config_file.read_text())
    worker=CONTROL/'ci/speech-vosk/worker.py'
    assert hashlib.sha256(worker.read_bytes()).hexdigest()=='2e8d8261b2012554377dcf37adaf15b87c2208a2bb423e0e2881a5e480f926b1'
    spec=importlib.util.spec_from_file_location('bounded_public_worker',worker)
    common=importlib.util.module_from_spec(spec);spec.loader.exec_module(common)
    resource.setrlimit(resource.RLIMIT_CPU,(120,120))
    resource.setrlimit(resource.RLIMIT_AS,(3072*1024*1024,3072*1024*1024))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
    native_path=Path(config['native_library']).resolve(strict=True)
    assert native_path.is_file() and not native_path.is_symlink()
    assert common.sha(native_path.read_bytes())==config['native_sha256']
    model=Path(config['model_directory']).resolve(strict=True)
    for name,expected in config['model_members'].items():
        path=model.parent/name
        assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(model)
        raw=path.read_bytes();assert len(raw)==expected['bytes'] and common.sha(raw)==expected['sha256']
    assert [s['row_index'] for s in config['samples']]==list(range(5))
    sample=config['samples'][4]
    pcm=Path(sample['pcm_path']).read_bytes()
    assert len(pcm)==sample['pcm_bytes'] and common.sha(pcm)==sample['pcm_sha256']
    assert 32000<=len(pcm)<=960000 and len(pcm)%2==0
    output=Path(config['output']).resolve();cycles=[]
    sandbox=common.deny_network_and_exec()
    native=ctypes.CDLL(str(native_path))
    prototypes={
        'vosk_set_log_level':([ctypes.c_int],None),
        'vosk_model_new':([ctypes.c_char_p],ctypes.c_void_p),
        'vosk_model_free':([ctypes.c_void_p],None),
        'vosk_recognizer_new':([ctypes.c_void_p,ctypes.c_float],ctypes.c_void_p),
        'vosk_recognizer_free':([ctypes.c_void_p],None),
        'vosk_recognizer_accept_waveform':([ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int],ctypes.c_int),
        'vosk_recognizer_result':([ctypes.c_void_p],ctypes.c_char_p),
        'vosk_recognizer_final_result':([ctypes.c_void_p],ctypes.c_char_p)}
    for name,(args,result) in prototypes.items():
        function=getattr(native,name);function.argtypes=args;function.restype=result
    native.vosk_set_log_level(0)
    def save(complete,phase):
        report={'complete':complete,'phase':phase,'cycles':cycles,'sandbox':sandbox,
                'sample_row_index':4,'model_lifecycle':'two-load/recognize/free-cycles-in-one-process',
                'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                'actual_client_cancel_or_account_switch':False,'production_admitted':False}
        temp=output.with_suffix('.tmp');temp.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');temp.replace(output)
    def text(value):
        assert value is not None and len(value)<=65536
        parsed=json.loads(value.decode('utf8'))
        assert set(parsed)=={'text'} and isinstance(parsed['text'],str) and len(parsed['text'])<=16000
        return parsed['text'].strip()
    for cycle in range(2):
        save(False,str(cycle)+':model-load-start');start=time.monotonic()
        model_handle=native.vosk_model_new(str(model).encode('utf8'));assert model_handle
        model_ms=round((time.monotonic()-start)*1000,3)
        rec=None
        try:
            rec=native.vosk_recognizer_new(model_handle,ctypes.c_float(16000));assert rec
            save(False,str(cycle)+':recognize-start');start=time.monotonic();parts=[]
            for offset in range(0,len(pcm),6400):
                chunk=pcm[offset:offset+6400]
                result=native.vosk_recognizer_accept_waveform(rec,chunk,len(chunk));assert result in (0,1)
                if result==1:parts.append(text(native.vosk_recognizer_result(rec)))
            parts.append(text(native.vosk_recognizer_final_result(rec)))
            transcript=' '.join(p for p in parts if p)
            cycles.append({'cycle':cycle,'model_load_milliseconds':model_ms,
                           'inference_milliseconds':round((time.monotonic()-start)*1000,3),
                           'transcript':transcript,'pcm_sha256':sample['pcm_sha256'],
                           'word_edits':common.edit_count(common.words(sample['reference']),common.words(transcript)),
                           'reference_words':len(common.words(sample['reference']))})
        finally:
            if rec:native.vosk_recognizer_free(rec)
            save(False,str(cycle)+':model-free-start')
            native.vosk_model_free(model_handle)
        save(False,str(cycle)+':model-freed')
    assert len(cycles)==2
    save(True,'complete')

if __name__=='__main__':
    assert len(sys.argv)==2
    run(Path(sys.argv[1]).resolve(strict=True))
