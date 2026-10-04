# SPDX-License-Identifier: MIT
"""Five fresh recognizers sharing one static model in a bounded network-denied child."""
import ctypes
import ctypes.util
import errno
import hashlib
import json
import os
from pathlib import Path
import resource
import socket
import sys
import time
import unicodedata


def words(text):
    text = text.lower().replace('ё', 'е')
    text = ''.join(c if unicodedata.category(c).startswith('L')
                   or unicodedata.category(c) == 'Nd' else ' ' for c in text)
    value = text.split()
    assert len(value) <= 500
    return value


def edit_count(reference, actual):
    previous = list(range(len(actual) + 1))
    for index, expected in enumerate(reference, 1):
        current = [index]
        for j, heard in enumerate(actual, 1):
            current.append(min(previous[j] + 1, current[j-1] + 1,
                               previous[j-1] + (expected != heard)))
        previous = current
    return previous[-1]


def deny_network_and_exec():
    # libseccomp is the trusted OS sandbox library, not part of the vendor wheel.
    filename = ctypes.util.find_library('seccomp')
    assert filename, 'libseccomp unavailable; do not execute the vendor library'
    library = ctypes.CDLL(filename)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_load.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    library.seccomp_release.restype = None
    context = library.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    assert context
    denied = []
    try:
        for name in ('socket','socketpair','connect','bind','listen','accept','accept4',
                     'sendto','sendmsg','sendmmsg','recvfrom','recvmsg','recvmmsg','execve','execveat'):
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number >= 0:
                assert library.seccomp_rule_add(context, 0x00050000 | errno.EPERM, number, 0) == 0
                denied.append(name)
        assert {'socket','connect','execve'} <= set(denied)
        assert library.seccomp_load(context) == 0
    finally:
        library.seccomp_release(context)
    for family in (socket.AF_INET, socket.AF_UNIX):
        try:
            probe = socket.socket(family, socket.SOCK_STREAM)
        except OSError as failure:
            assert failure.errno == errno.EPERM
        else:
            probe.close()
            raise AssertionError('Network/IPC prohibition not enforced')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.execve.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_char_p)]
    libc.execve.restype = ctypes.c_int
    argv = (ctypes.c_char_p * 2)(b'capy-nonexistent-sandbox-probe', None)
    environ = (ctypes.c_char_p * 1)(None)
    assert libc.execve(b'/nonexistent-capy-sandbox-probe', argv, environ) == -1
    assert ctypes.get_errno() == errno.EPERM
    return {'network_and_unix_socket_creation_denied':True,'execve_denied':True,
            'verified_before_vendor_load':True,'denied_syscalls':denied}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(config_path):
    assert sys.platform == 'linux'
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_AS, (3072 * 1024 * 1024, 3072 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    config = json.loads(config_path.read_text())
    assert [s['row_index'] for s in config['samples']] == list(range(5))
    output = Path(config['output']).resolve()
    native_path = Path(config['native_library']).resolve(strict=True)
    assert native_path.is_file() and not native_path.is_symlink()
    assert sha(native_path.read_bytes()) == config['native_sha256']
    model = Path(config['model_directory']).resolve(strict=True)
    for name, expected in config['model_members'].items():
        path = model.parent / name
        assert path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(model)
        data = path.read_bytes()
        assert len(data) == expected['bytes'] and sha(data) == expected['sha256']
    observations = []
    sandbox = deny_network_and_exec()
    native = ctypes.CDLL(str(native_path))
    prototypes = {
        'vosk_set_log_level':([ctypes.c_int],None),
        'vosk_model_new':([ctypes.c_char_p],ctypes.c_void_p),
        'vosk_model_free':([ctypes.c_void_p],None),
        'vosk_recognizer_new':([ctypes.c_void_p,ctypes.c_float],ctypes.c_void_p),
        'vosk_recognizer_free':([ctypes.c_void_p],None),
        'vosk_recognizer_accept_waveform':([ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int],ctypes.c_int),
        'vosk_recognizer_result':([ctypes.c_void_p],ctypes.c_char_p),
        'vosk_recognizer_final_result':([ctypes.c_void_p],ctypes.c_char_p),
    }
    for name, (args, result) in prototypes.items():
        function = getattr(native, name)
        function.argtypes = args
        function.restype = result
    native.vosk_set_log_level(0)  # Public-data test only: preserve the last native loading stage.

    def save(complete, phase):
        result = {'complete':complete,'phase':phase,'sandbox':sandbox,'observations':observations,
                  'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  'address_space_limit_mib':3072,'cpu_limit_seconds':120,
                  'model_lifecycle':'one-static-model/fresh-recognizer-per-clip'}
        temp = output.with_suffix('.tmp')
        temp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        temp.replace(output)

    def text_from(value):
        assert value is not None and len(value) <= 65536
        result = json.loads(value.decode('utf8'))
        assert set(result) == {'text'} and isinstance(result['text'],str)
        assert len(result['text']) <= 16000
        return result['text'].strip()

    save(False, 'shared-model:start')
    start = time.monotonic()
    model_handle = native.vosk_model_new(str(model).encode('utf8'))
    assert model_handle, 'Pinned static model could not load'
    shared_load_ms = round((time.monotonic() - start) * 1000, 3)
    try:
        for sample in config['samples']:
            pcm_path = Path(sample['pcm_path']).resolve(strict=True)
            pcm = pcm_path.read_bytes()
            assert len(pcm) == sample['pcm_bytes'] and sha(pcm) == sample['pcm_sha256']
            assert 32000 <= len(pcm) <= 2 * 16000 * 30 and len(pcm) % 2 == 0
            assert abs(len(pcm) / 32000 - sample['source_duration_seconds']) <= 0.5
            recognizer = None
            load_ms = shared_load_ms if sample['row_index'] == 0 else 0.0
            try:
                recognizer = native.vosk_recognizer_new(model_handle, ctypes.c_float(16000))
                assert recognizer
                save(False, str(sample['row_index']) + ':recognize-start')
                inference_start = time.monotonic()
                parts = []
                for offset in range(0, len(pcm), 6400):
                    chunk = pcm[offset:offset + 6400]
                    status = native.vosk_recognizer_accept_waveform(recognizer, chunk, len(chunk))
                    assert status in (0, 1)
                    if status == 1:
                        parts.append(text_from(native.vosk_recognizer_result(recognizer)))
                parts.append(text_from(native.vosk_recognizer_final_result(recognizer)))
                inference_ms = round((time.monotonic() - inference_start) * 1000, 3)
                transcript = ' '.join(p for p in parts if p)
                reference, actual = words(sample['reference']), words(transcript)
                errors = edit_count(reference, actual)
                observations.append({'row_index':sample['row_index'],'reference':sample['reference'],
                                     'transcript':transcript,'reference_words':len(reference),
                                     'hypothesis_words':len(actual),'word_edits':errors,
                                     'word_error_rate':errors / len(reference),'model_load_milliseconds':load_ms,
                                     'model_reused':sample['row_index'] != 0,
                                     'inference_milliseconds':inference_ms,'pcm_bytes':len(pcm),
                                     'pcm_sha256':sample['pcm_sha256']})
                save(False, str(sample['row_index']) + ':complete')
            finally:
                if recognizer:
                    native.vosk_recognizer_free(recognizer)
                pcm = b''
    finally:
        native.vosk_model_free(model_handle)
    assert len(observations) == 5
    save(True, 'complete')


if __name__ == '__main__':
    assert len(sys.argv) == 2
    run(Path(sys.argv[1]).resolve(strict=True))
