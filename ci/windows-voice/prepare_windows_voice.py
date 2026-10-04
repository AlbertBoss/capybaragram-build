# SPDX-License-Identifier: MIT
"""Apply native desktop voice UI only to the verified post-read-mode sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / 'transcription'
SOURCE_SHA = '80158983dba09d3bf5d96701f21473d6c34bf5f5'
PREFIX = 'Telegram/SourceFiles/'
FILES = ['Telegram/CMakeLists.txt'] + [PREFIX + p for p in (
    'core/application.h', 'core/application.cpp', 'history/view/history_view_context_menu.cpp')]
ADDED = {PREFIX + 'capybara/' + p: HERE / p for p in (
    'voice_worker.h', 'voice_worker.cpp', 'voice_decoder.h', 'voice_decoder.cpp',
    'capy_voice_ui.h', 'capy_voice_ui.cpp')}
ADDED.update({PREFIX + 'capybara/offline_voice/' + p: SHARED / p for p in (
    'CMakeLists.txt', 'offline_engine.cpp', 'offline_engine.h', 'UPSTREAM-LICENSE.txt')})

def digest(data):
    # Git converts checked-out text to CRLF on Windows; pins bind normalized text.
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()

def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Windows voice anchor differs: ' + before[:80])
    return text.replace(before, after)

def transform(name, text):
    if name == 'Telegram/CMakeLists.txt':
        text = replace(text, '        ${src_loc}/capybara/capy_read_mode_ui.cpp\n',
            '        ${src_loc}/capybara/capy_voice_ui.cpp\n'
            '        ${src_loc}/capybara/capy_voice_ui.h\n'
            '        ${src_loc}/capybara/capy_read_mode_ui.cpp\n')
        return replace(text, '    target_link_libraries(Telegram PRIVATE crypt32 bcrypt)', '''    set(CAPY_WHISPER_SOURCE "$ENV{CAPY_WINDOWS_WHISPER_SOURCE}")
    set(CAPY_VOICE_EMBEDDED ON)
    add_subdirectory(${src_loc}/capybara/offline_voice capy-offline-voice)
    add_library(capy_windows_voice STATIC
        ${src_loc}/capybara/voice_worker.cpp
        ${src_loc}/capybara/voice_decoder.cpp)
    init_target(capy_windows_voice)
    target_include_directories(capy_windows_voice PUBLIC ${src_loc}/capybara)
    target_link_libraries(capy_windows_voice PUBLIC capy_offline_voice
        desktop-app::external_qt desktop-app::lib_ffmpeg)
    set_source_files_properties(${src_loc}/capybara/voice_worker.cpp
        ${src_loc}/capybara/voice_decoder.cpp PROPERTIES SKIP_PRECOMPILE_HEADERS ON)
    target_link_libraries(Telegram PRIVATE crypt32 bcrypt capy_windows_voice)''')
    if name == PREFIX + 'core/application.h':
        text = replace(text, 'namespace Capy::Vault {',
            'namespace Capy::Voice { class Worker; }\n\nnamespace Capy::Vault {')
        text = replace(text, '\t[[nodiscard]] Capy::Vault::Worker &capyVaultWorker();',
            '\t[[nodiscard]] Capy::Voice::Worker &capyVoiceWorker();\n'
            '\t[[nodiscard]] Capy::Vault::Worker &capyVaultWorker();')
        return replace(text, '\tstd::unique_ptr<Capy::Vault::Worker> _capyVaultWorker;',
            '\tstd::unique_ptr<Capy::Voice::Worker> _capyVoiceWorker;\n'
            '\tstd::unique_ptr<Capy::Vault::Worker> _capyVaultWorker;')
    if name == PREFIX + 'core/application.cpp':
        text = replace(text, '#include "capybara/vault_worker.h"',
            '#include "capybara/vault_worker.h"\n#include "capybara/voice_worker.h"')
        text = replace(text, 'Application::~Application() {\n',
            'Application::~Application() {\n\t_capyVoiceWorker.reset(); // cancel/join before Qt/window teardown\n')
        return replace(text, 'Capy::Vault::Worker &Application::capyVaultWorker() {', '''Capy::Voice::Worker &Application::capyVoiceWorker() {
    if (!_capyVoiceWorker) {
        _capyVoiceWorker = std::make_unique<Capy::Voice::Worker>(
            (cWorkingDir() + u"tdata/capybara-speech"_q).toUtf8().toStdString(),
            [](std::function<void()> callback) { crl::on_main(std::move(callback)); });
    }
    return *_capyVoiceWorker;
}

Capy::Vault::Worker &Application::capyVaultWorker() {''')
    if name == PREFIX + 'history/view/history_view_context_menu.cpp':
        text = replace(text, '#include "history/view/history_view_context_menu.h"',
            '#include "history/view/history_view_context_menu.h"\n#include "capybara/capy_voice_ui.h"')
        return replace(text, '\tAddSaveDocumentAction(menu, item, document, list);',
            '\tCapy::AddVoiceAction(menu, document, item, controller);\n'
            '\tAddSaveDocumentAction(menu, item, document, list);')
    raise ValueError('Unexpected native host')

def plan(root, check=False):
    manifest = json.loads((HERE / 'windows-voice-hashes.json').read_text())
    if manifest['source_sha'] != SOURCE_SHA:
        raise ValueError('Wrong manifest revision')
    output = {}
    for name in FILES:
        data = (root / name).read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['post' if check else 'pre'][name]:
            raise ValueError('Native source changed: ' + name)
        if not check:
            data = transform(name, data.decode('utf8')).encode('utf8')
            if digest(data) != manifest['post'][name]: raise ValueError('Wrong patch result')
            output[name] = data
    for name, source in ADDED.items():
        data = source.read_bytes().replace(b"\r\n", b"\n")
        if digest(data) != manifest['added'][name]: raise ValueError('Payload changed: ' + name)
        target = root / name
        if check:
            if target.read_bytes().replace(b"\r\n", b"\n") != data: raise ValueError('Installed payload changed')
        elif target.exists() or target.is_symlink():
            raise ValueError('Refusing overwrite')
        else: output[name] = data
    return output

def prepare_dependency():
    pins = json.loads((SHARED / 'source-pins.json').read_text())
    target = Path(os.environ['CAPY_WINDOWS_WHISPER_SOURCE'])
    temporary = Path(os.environ['RUNNER_TEMP']).resolve()
    if target.exists() or target.is_symlink() or not target.resolve().is_relative_to(temporary):
        raise ValueError('Pinned source directory is not a fresh runner-local directory')
    archive = temporary / 'capy-windows-whisper.zip'
    h = hashlib.sha256(); count = 0
    with urllib.request.urlopen('https://codeload.github.com/' + pins['repository'] + '/zip/' + pins['commit'], timeout=90) as response, archive.open('xb') as f:
        while data := response.read(1048576):
            count += len(data)
            if count > 80 * 1048576: raise ValueError('Pinned source too large')
            h.update(data); f.write(data)
    if h.hexdigest() != pins['zip_sha256']: raise ValueError('Pinned source archive differs')
    with zipfile.ZipFile(archive) as z:
        prefix = z.namelist()[0].split('/')[0] + '/'
        for entry in z.infolist():
            if entry.is_dir(): continue
            path = PurePosixPath(entry.filename.removeprefix(prefix))
            if not entry.filename.startswith(prefix) or path.is_absolute() or '..' in path.parts or ':' in str(path) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe pinned source entry')
            if entry.file_size > 100 * 1048576: raise ValueError('Source entry too large')
            file = target / str(path); file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(z.read(entry))
    if (target / 'LICENSE').read_bytes().replace(b'\r\n', b'\n') != (SHARED / 'UPSTREAM-LICENSE.txt').read_bytes().replace(b'\r\n', b'\n'):
        raise ValueError('Pinned notice differs')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('root', type=Path)
    parser.add_argument('--check', action='store_true'); args = parser.parse_args()
    head = subprocess.run(['git', '-C', str(args.root), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    if head != SOURCE_SHA: raise ValueError('Wrong desktop revision')
    planned = plan(args.root, args.check)
    if not args.check:
        prepare_dependency()
        for name, data in planned.items():
            target = args.root / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
    print('CAPY_WINDOWS_VOICE_SOURCE=' + ('CHECKED' if args.check else 'PREPARED'))
