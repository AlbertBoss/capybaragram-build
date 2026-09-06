# SPDX-License-Identifier: MIT
"""Pinned Windows notes/templates patch, applied after identity and accounts."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

SOURCE_SHA = '80158983dba09d3bf5d96701f21473d6c34bf5f5'
HERE = Path(__file__).resolve().parent
ADDED = ('vault_store.h', 'vault_store.cpp', 'vault_registry.h', 'vault_registry.cpp',
         'vault_worker.h', 'vault_worker.cpp', 'capy_notes_ui.h', 'capy_notes_ui.cpp')

PREFIX = 'Telegram/SourceFiles/'
FILES = ['Telegram/CMakeLists.txt'] + [PREFIX + name for name in (
    'core/application.h', 'core/application.cpp',
    'main/main_account.h', 'main/main_account.cpp', 'main/main_domain.cpp',
    'window/window_peer_menu.cpp',
    'history/history_widget.cpp',
    'history/view/history_view_top_bar_widget.h',
    'history/view/history_view_top_bar_widget.cpp',
    'history/view/history_view_chat_section.cpp',
    'history/view/controls/history_view_compose_controls.h',
    'history/view/controls/history_view_compose_controls.cpp')]


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Windows notes anchor count differs: ' + old[:90])
    return text.replace(old, new)


def transform(name, text):
    if name == 'Telegram/CMakeLists.txt':
        return replace(text, 'get_filename_component(res_loc Resources REALPATH)\n', '''get_filename_component(res_loc Resources REALPATH)

if (WIN32)
    target_sources(Telegram PRIVATE
        ${src_loc}/capybara/vault_store.cpp
        ${src_loc}/capybara/vault_store.h
        ${src_loc}/capybara/vault_registry.cpp
        ${src_loc}/capybara/vault_registry.h
        ${src_loc}/capybara/vault_worker.cpp
        ${src_loc}/capybara/vault_worker.h
        ${src_loc}/capybara/capy_notes_ui.cpp
        ${src_loc}/capybara/capy_notes_ui.h
    )
    # Plain Win32 storage units do not consume Telegram's Qt precompiled header.
    # They inherit the same /EHsc and static MSVC runtime as the Telegram target.
    set_source_files_properties(
        ${src_loc}/capybara/vault_store.cpp
        ${src_loc}/capybara/vault_registry.cpp
        ${src_loc}/capybara/vault_worker.cpp
        PROPERTIES SKIP_PRECOMPILE_HEADERS ON
    )
    target_link_libraries(Telegram PRIVATE crypt32 bcrypt)
endif()
''')
    if name == PREFIX + 'core/application.h':
        text = replace(text, 'namespace Core {\n', '''namespace Capy::Vault {
class Worker;
} // namespace Capy::Vault

namespace Core {
''')
        text = replace(text, '\tvoid lockByPasscode();', '''\t[[nodiscard]] Capy::Vault::Worker &capyVaultWorker();
\tvoid lockByPasscode();''')
        return replace(text, '\tconst std::unique_ptr<Main::Domain> _domain;', '''\t// Domain accounts must be destroyed while this worker is still alive.
\tstd::unique_ptr<Capy::Vault::Worker> _capyVaultWorker;
\tconst std::unique_ptr<Main::Domain> _domain;''')
    if name == PREFIX + 'core/application.cpp':
        text = replace(text, '#include "core/application.h"', '''#include "core/application.h"
#include "capybara/vault_worker.h"''')
        text = replace(text, 'Application::~Application() {\n', '''Application::~Application() {
\tif (_capyVaultWorker) _capyVaultWorker->setLocked(true);
''')
        text = replace(text, 'void Application::lockByPasscode() {\n', '''Capy::Vault::Worker &Application::capyVaultWorker() {
\tif (!_capyVaultWorker) {
\t\t_capyVaultWorker = std::make_unique<Capy::Vault::Worker>(
\t\t\tstd::filesystem::path((cWorkingDir() + u"tdata/capybara-vault"_q).toStdWString()),
\t\t\tMain::Domain::kMaxAccounts,
\t\t\t[](std::function<void()> callback) {
\t\t\t\tcrl::on_main(std::move(callback));
\t\t\t});
\t\t_capyVaultWorker->setLocked(passcodeLocked());
\t}
\treturn *_capyVaultWorker;
}

void Application::lockByPasscode() {
\tif (_capyVaultWorker) _capyVaultWorker->setLocked(true);
''')
        return replace(text, '\t_passcodeLock = false;\n', '''\tif (_capyVaultWorker) _capyVaultWorker->setLocked(false);
\t_passcodeLock = false;
''')
    if name == PREFIX + 'main/main_account.h':
        text = replace(text, '#pragma once\n', '#pragma once\n\n#include "capybara/vault_worker.h"\n')
        text = replace(text, '\t~Account();', '''\t~Account();
\t[[nodiscard]] const Capy::Vault::Worker::Handle &capyVaultHandle() const {
\t\treturn _capyVaultHandle;
\t}''')
        # Only the private four-argument overload receives the explicit flag.
        before, after = text.split('private:', 1)
        after = replace(after, '\t\tstd::unique_ptr<SessionSettings> settings);',
            '\t\tstd::unique_ptr<SessionSettings> settings,\n\t\tbool freshLogin);')
        text = before + 'private:' + after
        return replace(text, '\tconst not_null<Domain*> _domain;', '''\tconst int _capyAccountIndex;
\tCapy::Vault::Worker::Handle _capyVaultHandle;
\tstd::string _capyAuthorization = Capy::Vault::Registry::LegacyAuthorization;
\tconst not_null<Domain*> _domain;''')
    if name == PREFIX + 'main/main_account.cpp':
        text = replace(text, '#include "main/main_account.h"', '#include "main/main_account.h"\n#include <stdexcept>')
        text = replace(text, ': _domain(domain)\n', ': _capyAccountIndex(index)\n, _domain(domain)\n')
        text = replace(text,
            '\t\tsettings ? std::move(settings) : std::make_unique<SessionSettings>());',
            '\t\tsettings ? std::move(settings) : std::make_unique<SessionSettings>(),\n\t\ttrue);')
        text = replace(text, '\t\tstreamVersion,\n\t\tstd::move(settings));',
            '\t\tstreamVersion,\n\t\tstd::move(settings),\n\t\tfalse);')
        text = replace(text, '''void Account::createSession(
\t\tconst MTPUser &user,
\t\tQByteArray serialized,
\t\tint streamVersion,
\t\tstd::unique_ptr<SessionSettings> settings) {''', '''void Account::createSession(
\t\tconst MTPUser &user,
\t\tQByteArray serialized,
\t\tint streamVersion,
\t\tstd::unique_ptr<SessionSettings> settings,
\t\tbool freshLogin) {''')
        text = replace(text, '\t_session = std::make_unique<Session>(this, user, std::move(settings));', '''\t// Rotate before constructing or exposing a fresh Telegram session. Persist
\t// this identity inside the same encrypted blob as its MTP authorization.
\tif (freshLogin) {
\t\ttry { _capyAuthorization = Capy::Vault::Store::NewId(); }
\t\tcatch (const std::exception &) { _capyAuthorization.clear(); }
\t}
\t_session = std::make_unique<Session>(this, user, std::move(settings));''')
        text = replace(text, '\t\t\twriteKeys(stream, keysToDestroy);', '''\t\t\twriteKeys(stream, keysToDestroy);
\t\t\tstream << quint32(0x43504731); // CPG1 authorization identity trailer
\t\t\tconst auto identity = (_capyAuthorization.size() == 32)
\t\t\t\t? _capyAuthorization : std::string(32, '-');
\t\t\tstream.writeRawData(identity.data(), 32);''')
        text = replace(text, '\tQDataStream stream(serialized);\n', '''\t_capyAuthorization.clear(); // malformed new metadata must never restore old notes
\tQDataStream stream(serialized);
''')
        text = replace(text, '\treadKeys(_mtpKeysToDestroy);', '''\treadKeys(_mtpKeysToDestroy);
\tif (stream.status() == QDataStream::Ok) {
\t\tif (stream.atEnd()) {
\t\t\t// Stable identity for pre-Capy profiles: do not regenerate on restart.
\t\t\t_capyAuthorization = Capy::Vault::Registry::LegacyAuthorization;
\t\t} else {
\t\t\tauto tag = quint32();
\t\t\tstream >> tag;
\t\t\tauto identity = std::string(32, '\\0');
\t\t\tif (tag == 0x43504731 && stream.readRawData(identity.data(), 32) == 32
\t\t\t\t&& stream.status() == QDataStream::Ok && stream.atEnd()) {
\t\t\t\ttry {
\t\t\t\t\t(void)Capy::Vault::Store::Template(identity); // strict 32-hex
\t\t\t\t\t_capyAuthorization = std::move(identity);
\t\t\t\t} catch (const std::exception &) { }
\t\t\t}
\t\t}
\t}''')
        text = replace(text, '\t_sessionValue = _session.get();', '''\t_capyVaultHandle = Core::App().capyVaultWorker().attach(
\t\t_capyAccountIndex, _session->uniqueId(), freshLogin, _capyAuthorization);
\t_sessionValue = _session.get();''')
        return replace(text, 'void Account::destroySession(DestroyReason reason) {\n', '''void Account::destroySession(DestroyReason reason) {
\tif (_capyVaultHandle) {
\t\tCore::App().capyVaultWorker().detach(
\t\t\t_capyVaultHandle, reason == DestroyReason::LoggedOut);
\t\t_capyVaultHandle.reset();
\t}
''')
    if name == PREFIX + 'main/main_domain.cpp':
        return replace(text, 'void Domain::resetWithForgottenPasscode() {\n', '''void Domain::resetWithForgottenPasscode() {
\tCore::App().capyVaultWorker().forgetAll();
''')
    if name == PREFIX + 'window/window_peer_menu.cpp':
        text = replace(text, '#include "window/window_peer_menu.h"',
            '#include "window/window_peer_menu.h"\n#include "capybara/capy_notes_ui.h"')
        return replace(text, '\tFiller(controller, request, callback).fill();',
            '\tFiller(controller, request, callback).fill();\n\tCapy::AddNoteAction(controller, request, callback);')
    if name == PREFIX + 'history/view/history_view_top_bar_widget.h':
        text = replace(text, '\tvoid showPeerMenu();', '''\tvoid showPeerMenu();
\tvoid setCapyDraftInserter(Fn<bool(QString)> insert) {
\t\t_capyDraftInserter = std::move(insert);
\t}''')
        return replace(text, '\tbase::unique_qptr<Ui::PopupMenu> _menu;', '''\tbase::unique_qptr<Ui::PopupMenu> _menu;
\tFn<bool(QString)> _capyDraftInserter;
\tuint64 _capyContextEpoch = 0;''')
    if name == PREFIX + 'history/view/history_view_top_bar_widget.cpp':
        text = replace(text, '#include "history/view/history_view_top_bar_widget.h"',
            '#include "history/view/history_view_top_bar_widget.h"\n#include "capybara/capy_notes_ui.h"\n#include <QPointer>')
        text = replace(text, '\t_sendAction = sendAction;\n', '''\tif (_activeChat != activeChat) ++_capyContextEpoch;
\t_sendAction = sendAction;
''')
        return replace(text, '\tWindow::FillDialogsEntryMenu(_controller, _activeChat, addAction);', '''\tWindow::FillDialogsEntryMenu(_controller, _activeChat, addAction);
\tif (_capyDraftInserter) {
\t\tconst auto weak = QPointer<TopBarWidget>(this);
\t\tconst auto epoch = _capyContextEpoch;
\t\tCapy::AddTemplatesAction(_controller, _activeChat, [weak, epoch](QString text) {
\t\t\treturn weak && weak->_capyContextEpoch == epoch
\t\t\t\t&& weak->_capyDraftInserter
\t\t\t\t&& weak->_capyDraftInserter(std::move(text));
\t\t}, addAction);
\t}''')
    if name == PREFIX + 'history/history_widget.cpp':
        text = replace(text, '#include "history/history_widget.h"',
            '#include "history/history_widget.h"\n#include <QPointer>')
        return replace(text, '\t_topBar->forwardSelectionRequest(\n', '''\t_topBar->setCapyDraftInserter([weak = QPointer<HistoryWidget>(this)](QString text) {
\t\tif (!weak || !weak->_history || weak->_editMsgId || !weak->_canSendTexts
\t\t\t|| weak->_field->isHidden() || !weak->_field->isEnabled()) return false;
\t\t// Keep selected draft text: insert at the caret without replacing it.
\t\tauto cursor = weak->_field->textCursor();
\t\tcursor.clearSelection();
\t\tweak->_field->setTextCursor(cursor);
\t\tweak->insertTextAtCursor(text);
\t\treturn true;
\t});
\t_topBar->forwardSelectionRequest(
''')
    if name == PREFIX + 'history/view/history_view_chat_section.cpp':
        text = replace(text, '#include "history/view/history_view_chat_section.h"',
            '#include "history/view/history_view_chat_section.h"\n#include <QPointer>')
        return replace(text, '\t_topBar->deleteSelectionRequest(\n', '''\t_topBar->setCapyDraftInserter([weak = QPointer<ChatWidget>(this)](QString text) {
\t\treturn weak && weak->_composeControls
\t\t\t&& weak->_composeControls->insertCapyTemplate(text);
\t});
\t_topBar->deleteSelectionRequest(
''')
    if name == PREFIX + 'history/view/controls/history_view_compose_controls.h':
        return replace(text, '\tvoid insertTextToField(const QString &text);',
            '\tvoid insertTextToField(const QString &text);\n\t[[nodiscard]] bool insertCapyTemplate(const QString &text);')
    if name == PREFIX + 'history/view/controls/history_view_compose_controls.cpp':
        return replace(text, 'void ComposeControls::insertTextToField(const QString &text) {', '''bool ComposeControls::insertCapyTemplate(const QString &text) {
\tif (!_canSendTexts.current() || isEditingMessage() || isRecording()
\t\t|| fieldDisabledShown() || _field->isHidden() || !_field->isEnabled()) return false;
\tauto cursor = _field->textCursor();
\tcursor.clearSelection();
\t_field->setTextCursor(cursor);
\tinsertTextToField(text);
\treturn true;
}

void ComposeControls::insertTextToField(const QString &text) {''')
    raise ValueError('Unexpected Windows notes target')


def normalized(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


def read_manifest():
    result = json.loads((HERE/'host-input-hashes.json').read_text(encoding='utf-8'))
    if result['source_sha'] != SOURCE_SHA or set(result['patch']) != set(FILES) or set(result['added']) != set(ADDED):
        raise ValueError('Windows notes manifest allowlist differs')
    return result


def payloads():
    storage = HERE.parent/'windows-vault'
    if not storage.is_dir():
        storage = HERE.parent/'local' # project review copy
    expected = read_manifest()['added']
    result = {}
    for name in ADDED:
        path = (HERE if name.startswith('capy_notes_ui.') else storage)/name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(path.parent.resolve(strict=True)):
            raise ValueError('Payload path escapes package')
        raw = normalized(path)
        if hashlib.sha256(raw).hexdigest() != expected[name]:
            raise ValueError('Notes payload differs from reviewed source')
        result[PREFIX+'capybara/'+name] = raw
    return result


def plan(source, check=False):
    root = Path(source).resolve(strict=True)
    manifest = read_manifest()
    prepared = {}
    for name in FILES:
        path = root/name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise ValueError('Notes source path escapes checkout')
        raw = normalized(path)
        expected = manifest['patch'][name]['after' if check else 'before']
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Notes source differs from reviewed composed input: '+name)
        if not check:
            patched = transform(name,raw.decode('utf-8')).encode('utf-8')
            if hashlib.sha256(patched).hexdigest() != manifest['patch'][name]['after']:
                raise ValueError('Notes transformation output differs')
            prepared[name] = patched
    for name, raw in payloads().items():
        path = root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Added source path escapes checkout')
        if check:
            if not path.is_file() or normalized(path) != raw:
                raise ValueError('Added notes source differs')
        else:
            if path.exists():
                raise ValueError('Will not overwrite existing added source')
            prepared[name] = raw
    return prepared


def apply(source):
    root = Path(source).resolve(strict=True)
    prepared = plan(root) # Validate every input and payload before writing.
    for name, raw in prepared.items():
        path = root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw.replace(b'\n',b'\r\n') if os.name == 'nt' else raw)
    return len(prepared)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    root = args.source.resolve(strict=True)
    head = subprocess.run(['git','-C',str(root),'rev-parse','HEAD'],capture_output=True,check=True,timeout=30).stdout.decode().strip()
    if head != SOURCE_SHA:
        raise SystemExit('REFUSED: Desktop source revision differs')
    if args.check:
        plan(root,check=True)
        print('PASS:13 patched and8 added native Windows notes/template files verified')
    else:
        print('PASS:',apply(root),'native Windows notes/template files prepared')
