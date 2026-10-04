# SPDX-License-Identifier: MIT
"""Connect the Windows archive only to pinned, composed native client sources."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE_SHA = '80158983dba09d3bf5d96701f21473d6c34bf5f5'
PREFIX = 'Telegram/SourceFiles/'
FILES = ['Telegram/CMakeLists.txt'] + [PREFIX + p for p in (
    'core/application.h', 'core/application.cpp',
    'main/main_account.h', 'main/main_account.cpp', 'main/main_domain.cpp',
    'main/main_session_settings.h', 'main/main_session_settings.cpp',
    'window/window_peer_menu.cpp', 'history/view/history_view_top_bar_widget.cpp',
    'data/data_session.cpp', 'history/history_item.cpp',
    'media/view/media_view_overlay_widget.cpp', 'chat_helpers/ttl_media_layer_widget.cpp',
    'ffmpeg/ffmpeg_utility.cpp', 'media/streaming/media_streaming_file.cpp',
    'media/streaming/media_streaming_loader_local.cpp')]
ADDED = {PREFIX + 'capybara/' + p: HERE / p for p in (
    'archive_store.h', 'archive_store.cpp', 'archive_worker.h', 'archive_worker.cpp',
    'verified_input.h', 'verified_input.cpp', 'capy_archive_ui.h', 'capy_archive_ui.cpp',
    'capy_archive_bridge.h', 'capy_archive_bridge.cpp',
    'capy_archive_settings.h', 'capy_archive_settings_test.cpp',
    'capy_archive_player.h', 'capy_archive_player.cpp')}


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def replace(text, before, after, count=1):
    if text.count(before) != count:
        raise ValueError('Windows archive anchor differs: ' + before[:90])
    return text.replace(before, after)


def transform(name, text):
    if name == 'Telegram/CMakeLists.txt':
        text = replace(text, '        ${src_loc}/capybara/capy_voice_ui.cpp\n',
            ''.join('        ${src_loc}/capybara/' + p + '\n' for p in (
                'archive_store.cpp', 'archive_store.h', 'archive_worker.cpp', 'archive_worker.h',
                'verified_input.cpp', 'verified_input.h', 'capy_archive_ui.cpp', 'capy_archive_ui.h',
                'capy_archive_bridge.cpp', 'capy_archive_bridge.h', 'capy_archive_settings.h',
                'capy_archive_player.cpp', 'capy_archive_player.h'))
            + '        ${src_loc}/capybara/capy_voice_ui.cpp\n')
        text = replace(text, '        ${src_loc}/capybara/vault_store.cpp\n        ${src_loc}/capybara/vault_registry.cpp',
            '        ${src_loc}/capybara/archive_store.cpp\n'
            '        ${src_loc}/capybara/archive_worker.cpp\n'
            '        ${src_loc}/capybara/verified_input.cpp\n'
            '        ${src_loc}/capybara/vault_store.cpp\n        ${src_loc}/capybara/vault_registry.cpp')
        return replace(text, '    add_executable(capy-auth-test EXCLUDE_FROM_ALL', '''    add_executable(capy-archive-settings-test EXCLUDE_FROM_ALL
        ${src_loc}/capybara/capy_archive_settings_test.cpp)
    init_target(capy-archive-settings-test)
    target_link_libraries(capy-archive-settings-test PRIVATE desktop-app::external_qt)
    set_source_files_properties(${src_loc}/capybara/capy_archive_settings_test.cpp
        PROPERTIES SKIP_PRECOMPILE_HEADERS ON)
    set_target_properties(capy-archive-settings-test PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/capy-tests")
    add_executable(capy-auth-test EXCLUDE_FROM_ALL''')
    if name == PREFIX + 'core/application.h':
        text = replace(text, 'namespace Capy::Voice { class Worker; }',
            'namespace Capy::Archive { class Worker; }\nnamespace Capy::Voice { class Worker; }')
        text = replace(text, '\t[[nodiscard]] Capy::Voice::Worker &capyVoiceWorker();',
            '\t[[nodiscard]] Capy::Archive::Worker &capyArchiveWorker();\n'
            '\t[[nodiscard]] Capy::Voice::Worker &capyVoiceWorker();')
        return replace(text, '\tstd::unique_ptr<Capy::Voice::Worker> _capyVoiceWorker;',
            '\tstd::unique_ptr<Capy::Archive::Worker> _capyArchiveWorker;\n'
            '\tstd::unique_ptr<Capy::Voice::Worker> _capyVoiceWorker;')
    if name == PREFIX + 'core/application.cpp':
        text = replace(text, '#include "capybara/vault_worker.h"',
            '#include "capybara/vault_worker.h"\n#include "capybara/archive_worker.h"')
        text = replace(text, '\tif (_capyVaultWorker) _capyVaultWorker->setLocked(true);',
            '\tif (_capyArchiveWorker) _capyArchiveWorker->setLocked(true);\n'
            '\tif (_capyVaultWorker) _capyVaultWorker->setLocked(true);', 2)
        text = replace(text, '\tif (_capyVaultWorker) _capyVaultWorker->setLocked(false);',
            '\tif (_capyArchiveWorker) _capyArchiveWorker->setLocked(false);\n'
            '\tif (_capyVaultWorker) _capyVaultWorker->setLocked(false);')
        return replace(text, 'Capy::Vault::Worker &Application::capyVaultWorker() {', '''Capy::Archive::Worker &Application::capyArchiveWorker() {
	if (!_capyArchiveWorker) {
		_capyArchiveWorker = std::make_unique<Capy::Archive::Worker>(
			std::filesystem::path((cWorkingDir() + u"tdata/capybara-archive"_q).toStdWString()),
			Main::Domain::kMaxAccounts,
			[](std::function<void()> callback) { crl::on_main(std::move(callback)); });
		_capyArchiveWorker->setLocked(passcodeLocked());
	}
	return *_capyArchiveWorker;
}

Capy::Vault::Worker &Application::capyVaultWorker() {''')
    if name == PREFIX + 'main/main_account.h':
        text = replace(text, '#include "capybara/vault_worker.h"',
            '#include "capybara/vault_worker.h"\n#include "capybara/archive_worker.h"')
        text = replace(text, '\t[[nodiscard]] const Capy::Vault::Worker::Handle &capyVaultHandle() const {',
            '\t[[nodiscard]] const Capy::Archive::Worker::Handle &capyArchiveHandle() const {\n'
            '\t\treturn _capyArchiveHandle;\n\t}\n'
            '\t[[nodiscard]] const Capy::Vault::Worker::Handle &capyVaultHandle() const {')
        return replace(text, '\tCapy::Vault::Worker::Handle _capyVaultHandle;',
            '\tCapy::Vault::Worker::Handle _capyVaultHandle;\n'
            '\tCapy::Archive::Worker::Handle _capyArchiveHandle;')
    if name == PREFIX + 'main/main_account.cpp':
        text = replace(text, '\t_sessionValue = _session.get();', '''	_capyArchiveHandle = Core::App().capyArchiveWorker().attach(
		_capyAccountIndex, _session->uniqueId(), freshLogin, _capyAuthorization);
	Core::App().capyArchiveWorker().setEnabled(
		_capyArchiveHandle, _session->settings().capyArchiveEnabled());
	_sessionValue = _session.get();''')
        return replace(text, 'void Account::destroySession(DestroyReason reason) {\n', '''void Account::destroySession(DestroyReason reason) {
	if (_capyArchiveHandle) {
		Core::App().capyArchiveWorker().detach(
			_capyArchiveHandle, reason == DestroyReason::LoggedOut);
		_capyArchiveHandle.reset();
	}
''')
    if name == PREFIX + 'main/main_domain.cpp':
        return replace(text, 'void Domain::resetWithForgottenPasscode() {\n',
            'void Domain::resetWithForgottenPasscode() {\n\tCore::App().capyArchiveWorker().forgetAll();\n')
    if name == PREFIX + 'main/main_session_settings.h':
        text = replace(text, '\tvoid setCapySilentRead(bool value)',
            '\tvoid setCapyArchiveEnabled(bool value) { _capyArchiveEnabled = value; }\n'
            '\t[[nodiscard]] bool capyArchiveEnabled() const { return _capyArchiveEnabled; }\n'
            '\tvoid setCapySilentRead(bool value)')
        return replace(text, '\tbool _capySilentRead = false;',
            '\tbool _capySilentRead = false;\n\tbool _capyArchiveEnabled = false;')
    if name == PREFIX + 'main/main_session_settings.cpp':
        text = replace(text, '#include "main/main_session_settings.h"',
            '#include "main/main_session_settings.h"\n#include "capybara/capy_archive_settings.h"')
        text = replace(text, '\tsize += 3 * sizeof(qint32); // Capy extension tag, version, silent-read',
            '\tsize += Capy::ArchiveSettings::SerializedSize;\n'
            '\tsize += 3 * sizeof(qint32); // Capy extension tag, version, silent-read')
        text = replace(text, '\t\tstream << qint32(0x43524731) << qint32(1) << qint32(_capySilentRead ? 1 : 0);',
            '\t\tstream << qint32(0x43524731) << qint32(1) << qint32(_capySilentRead ? 1 : 0);\n'
            '\t\tCapy::ArchiveSettings::Write(stream, _capyArchiveEnabled);')
        text = replace(text, '\tbool capySilentRead = false;',
            '\tbool capySilentRead = false;\n\tbool capyArchiveEnabled = false;')
        text = replace(text,
            '\t\t\t&& capyTag == 0x43524731 && capyVersion == 1 && capyValue == 1);\n\t}',
            '\t\t\t&& capyTag == 0x43524731 && capyVersion == 1 && capyValue == 1);\n'
            '\t\tif (stream.status() == QDataStream::Ok && capyTag == 0x43524731\n'
            '\t\t\t&& capyVersion == 1 && (capyValue == 0 || capyValue == 1)) {\n'
            '\t\t\tcapyArchiveEnabled = Capy::ArchiveSettings::Read(stream);\n\t\t}\n\t}')
        return replace(text, '\t_capySilentRead = capySilentRead;',
            '\t_capySilentRead = capySilentRead;\n\t_capyArchiveEnabled = capyArchiveEnabled;')
    if name == PREFIX + 'window/window_peer_menu.cpp':
        text = replace(text, '#include "capybara/capy_read_mode_ui.h"',
            '#include "capybara/capy_read_mode_ui.h"\n#include "capybara/capy_archive_ui.h"')
        return replace(text, '\tCapy::AddReadModeAction(controller, request, callback);',
            '\tCapy::AddReadModeAction(controller, request, callback);\n'
            '\tCapy::AddArchiveAction(controller, request, callback);')
    if name == PREFIX + 'history/view/history_view_top_bar_widget.cpp':
        text = replace(text, '#include "capybara/capy_read_mode_ui.h"',
            '#include "capybara/capy_read_mode_ui.h"\n#include "capybara/capy_archive_ui.h"')
        text = replace(text, '\tCapy::AddReadModeAction(_controller, _activeChat, addAction);',
            '\tCapy::AddReadModeAction(_controller, _activeChat, addAction);\n'
            '\tCapy::AddArchiveAction(_controller, _activeChat, addAction);')
        text = replace(text, 'u"CapybaraGram · Notes / Templates / Silent reading"_q',
            'u"CapybaraGram · Notes / Templates / Silent reading / Archive"_q')
        return replace(text, 'u"CapybaraGram · Заметки / Шаблоны / Нечиталка"_q',
            'u"CapybaraGram · Заметки / Шаблоны / Нечиталка / Архив"_q')
    if name == PREFIX + 'data/data_session.cpp':
        text = replace(text, '#include "data/data_session.h"',
            '#include "data/data_session.h"\n#include "capybara/capy_archive_bridge.h"')
        # Capture before mutation, even if applyEdition dispatches further updates.
        text = replace(text, '\tif (existing->isLocalUpdateMedia() && data.type() == mtpc_message) {',
            '\tCapy::CaptureArchive(existing, Capy::Archive::Reason::Edited);\n'
            '\tif (existing->isLocalUpdateMedia() && data.type() == mtpc_message) {')
        text = replace(text, '\tif (!toDestroy.empty()) {\n\t\tnotifyItemsAboutToBeDestroyed(toDestroy);',
            '\tif (!toDestroy.empty()) {\n'
            '\t\tfor (const auto &item : toDestroy) {\n'
            '\t\t\tCapy::CaptureArchive(item, Capy::Archive::Reason::Deleted);\n\t\t}\n'
            '\t\tnotifyItemsAboutToBeDestroyed(toDestroy);', 2)
        return replace(text, '\tif (!expired.empty()) {\n\t\tnotifyItemsAboutToBeDestroyed(expired);',
            '\tif (!expired.empty()) {\n'
            '\t\tfor (const auto &item : expired) {\n'
            '\t\t\tCapy::CaptureArchive(item, Capy::Archive::Reason::Expired);\n\t\t}\n'
            '\t\tnotifyItemsAboutToBeDestroyed(expired);')
    if name == PREFIX + 'history/history_item.cpp':
        text = replace(text, '#include "history/history_item.h"',
            '#include "history/history_item.h"\n#include "capybara/capy_archive_bridge.h"')
        return replace(text, '\tif (!media || !media->ttlSeconds()) {\n\t\treturn;\n\t}\n\tunarmMediaDestroy();',
            '\tif (!media || !media->ttlSeconds()) {\n\t\treturn;\n\t}\n'
            '\tCapy::CaptureArchive(this, Capy::Archive::Reason::Expired);\n\tunarmMediaDestroy();')
    if name == PREFIX + 'media/view/media_view_overlay_widget.cpp':
        text = replace(text, '#include "media/view/media_view_overlay_widget.h"',
            '#include "media/view/media_view_overlay_widget.h"\n#include "capybara/capy_archive_bridge.h"')
        return replace(text, '\t} else if (item->isIncomingUnreadMedia()) {\n\t\titem->history()->session().api().markContentsRead(item);',
            '\t} else if (item->isIncomingUnreadMedia()) {\n'
            '\t\tCapy::CaptureArchive(item, Capy::Archive::Reason::Expired);\n'
            '\t\titem->history()->session().api().markContentsRead(item);')
    if name == PREFIX + 'chat_helpers/ttl_media_layer_widget.cpp':
        text = replace(text, '#include "chat_helpers/ttl_media_layer_widget.h"',
            '#include "chat_helpers/ttl_media_layer_widget.h"\n#include "capybara/capy_archive_bridge.h"')
        return replace(text, '\t\tnot_null<HistoryItem*> item) {\n\tconst auto parent = controller->content();',
            '\t\tnot_null<HistoryItem*> item) {\n'
            '\tCapy::CaptureArchive(item, Capy::Archive::Reason::Expired);\n'
            '\tconst auto parent = controller->content();')
    # Unmodified pinned dependencies: bind the safety path used by our player.
    if name == PREFIX + 'ffmpeg/ffmpeg_utility.cpp':
        replace(text, '\tav_opt_set(format, "protocol_whitelist", "", 0);',
            '\tav_opt_set(format, "protocol_whitelist", "", 0);')
        replace(text, '\tRestrictToCustomIO(result);', '\tRestrictToCustomIO(result);')
        return text
    if name == PREFIX + 'media/streaming/media_streaming_file.cpp':
        replace(text, '\tauto format = FFmpeg::MakeFormatPointer(', '\tauto format = FFmpeg::MakeFormatPointer(')
        return text
    if name == PREFIX + 'media/streaming/media_streaming_loader_local.cpp':
        replace(text, '\tauto device = std::make_unique<QBuffer>();', '\tauto device = std::make_unique<QBuffer>();')
        return text
    raise ValueError('Unexpected native archive host')


def plan(source, check=False):
    source = Path(source).resolve(strict=True)
    manifest = json.loads((HERE / 'windows-archive-hashes.json').read_text(encoding='utf-8'))
    if (manifest['source_sha'] != SOURCE_SHA or set(manifest['pre']) != set(FILES)
            or set(manifest['post']) != set(FILES) or set(manifest['added']) != set(ADDED)):
        raise ValueError('Windows archive allowlist differs')
    result = {}
    for name in FILES:
        path = source / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):
            raise ValueError('Archive source path escapes checkout')
        data = path.read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['post' if check else 'pre'][name]:
            raise ValueError('Native archive input changed: ' + name)
        output = data if check else transform(name, data.decode('utf-8')).encode('utf-8')
        if digest(output) != manifest['post'][name]:
            raise ValueError('Native archive transformation differs: ' + name)
        if not check:
            result[name] = output
    for name, path in ADDED.items():
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(HERE):
            raise ValueError('Archive payload path escapes package')
        data = path.read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['added'][name]:
            raise ValueError('Native archive payload changed: ' + name)
        target = source / name
        if target.is_symlink() or not target.resolve().is_relative_to(source):
            raise ValueError('Installed archive path escapes checkout')
        if check:
            if not target.is_file() or digest(target.read_bytes()) != digest(data):
                raise ValueError('Installed archive payload changed: ' + name)
        elif target.exists():
            raise ValueError('Refusing to overwrite existing archive payload')
        else:
            result[name] = data
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    head = subprocess.run(['git', '-C', str(args.source), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    if head != SOURCE_SHA:
        raise ValueError('Wrong Desktop source revision')
    changes = plan(args.source, args.check)  # Validate everything before any write.
    if not args.check:
        for name, data in changes.items():
            target = args.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    print('CAPY_WINDOWS_ARCHIVE_SOURCE=' + ('CHECKED' if args.check else 'PREPARED'))
