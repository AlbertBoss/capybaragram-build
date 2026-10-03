# SPDX-License-Identifier: MIT
"""Native per-account read gate, applied after Windows appearance preparation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
SOURCE_SHA = '80158983dba09d3bf5d96701f21473d6c34bf5f5'
PREFIX = 'Telegram/SourceFiles/'
FILES = ['Telegram/CMakeLists.txt'] + [PREFIX + p for p in (
    'mtproto/mtp_instance.h', 'mtproto/mtp_instance.cpp',
    'main/main_session_settings.h', 'main/main_session_settings.cpp',
    'main/main_session.cpp', 'main/main_account.cpp', 'window/window_peer_menu.cpp',
    'history/view/history_view_top_bar_widget.cpp', 'data/data_histories.cpp',
    'data/data_replies_list.cpp', 'data/data_saved_sublist.cpp')]
ADDED = {PREFIX + 'capybara/' + p: HERE / p for p in (
    'read_receipt_policy.h', 'read_receipt_policy_test.cpp', 'capy_read_mode_ui.h', 'capy_read_mode_ui.cpp')}


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Windows read-mode anchor differs: ' + before[:90])
    return text.replace(before, after)


def transform(name, text):
    if name == 'Telegram/CMakeLists.txt':
        text = replace(text, '        ${src_loc}/capybara/capy_notes_ui.cpp\n',
            '        ${src_loc}/capybara/capy_read_mode_ui.cpp\n'
            '        ${src_loc}/capybara/capy_read_mode_ui.h\n'
            '        ${src_loc}/capybara/read_receipt_policy.h\n'
            '        ${src_loc}/capybara/capy_notes_ui.cpp\n')
        return replace(text, '    add_executable(capy-auth-test EXCLUDE_FROM_ALL', '''    add_executable(capy-read-policy-test EXCLUDE_FROM_ALL
        ${src_loc}/capybara/read_receipt_policy_test.cpp)
    init_target(capy-read-policy-test)
    set_source_files_properties(${src_loc}/capybara/read_receipt_policy_test.cpp
        PROPERTIES SKIP_PRECOMPILE_HEADERS ON)
    set_target_properties(capy-read-policy-test PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/capy-tests")
    add_executable(capy-auth-test EXCLUDE_FROM_ALL''')
    if name == PREFIX + 'mtproto/mtp_instance.h':
        text = replace(text, '#pragma once\n', '#pragma once\n\n#include "capybara/read_receipt_policy.h"\n')
        text = replace(text, '\t[[nodiscard]] rpl::lifetime &lifetime();', '''	void setCapySilentRead(bool silent) { _capyReadPolicy.setSilent(silent); }
	void resetCapyReadMode() { _capyReadPolicy.reset(); }
	[[nodiscard]] bool capySilentRead() const { return _capyReadPolicy.silent(); }
	[[nodiscard]] bool capySuppressRead(mtpRequestId request, uint32 constructor, bool isRead) {
		return _capyReadPolicy.suppress(request, constructor, isRead);
	}
	template <typename Request>
	mtpRequestId sendCapyExplicitRead(const Request &request, ResponseHandler &&callbacks) {
		const auto id = details::GetNextRequestId();
		_capyReadPolicy.allow(id, request.type());
		return send(request, std::move(callbacks), 0, 0, 0, id);
	}

	[[nodiscard]] rpl::lifetime &lifetime();''')
        return replace(text, '\tconst std::unique_ptr<Private> _private;',
            '\tCapy::ReadReceiptPolicy _capyReadPolicy;\n\tconst std::unique_ptr<Private> _private;')
    if name == PREFIX + 'mtproto/mtp_instance.cpp':
        text = replace(text, '#include "mtproto/mtp_instance.h"',
            '#include "mtproto/mtp_instance.h"\n#include <QTimer>')
        text = replace(text, '\tvoid processCallback(const Response &response);',
            '\tvoid capyReadSuppressed(mtpRequestId requestId);\n\tvoid processCallback(const Response &response);')
        old = '''		bool needsLayer,
		mtpRequestId afterRequestId) {
	const auto session = getSession(shiftedDcId);'''
        text = replace(text, old, '''		bool needsLayer,
		mtpRequestId afterRequestId) {
	// Inspect the top-level TL method before layer/invokeAfter wrapping. This
	// central boundary covers Sender and direct/serialized application calls.
	const auto body = SerializedRequest::kMessageBodyPosition;
	const auto constructor = needsLayer && request->size() > body ? (*request)[body] : 0;
	const auto isRead = [&] {
		switch (constructor) {
		case mtpc_messages_readHistory:
		case mtpc_channels_readHistory:
		case mtpc_messages_readMessageContents:
		case mtpc_channels_readMessageContents:
		case mtpc_messages_readDiscussion:
		case mtpc_messages_readSavedHistory:
		case mtpc_messages_readMentions:
		case mtpc_messages_readReactions:
		case mtpc_messages_readPollVotes:
		case mtpc_stories_readStories: return true;
		default: return false;
		}
	}();
	if (_instance->capySuppressRead(requestId, constructor, isRead)) {
		request->requestId = requestId;
		storeRequest(requestId, request, std::move(callbacks));
		// Sender registers the id after send() returns. Failure must be queued.
		// No DC registration, socket enqueue, server success or pts fabrication.
		QTimer::singleShot(0, _instance, [=] { capyReadSuppressed(requestId); });
		return;
	}
	const auto session = getSession(shiftedDcId);''')
        return replace(text, 'void Instance::Private::processCallback(const Response &response) {', '''void Instance::Private::capyReadSuppressed(mtpRequestId requestId) {
	ResponseHandler handler;
	{
		QMutexLocker locker(&_parserMapLock);
		const auto i = _parserMap.find(requestId);
		if (i != _parserMap.end()) {
			handler = std::move(i->second);
			_parserMap.erase(i);
		}
	}
	unregisterRequest(requestId);
	if (handler.fail) {
		// A terminal LOCAL error. Negative errors would be silently retried by
		// Sender's default policy. Deliberately bypass network error recovery.
		const auto error = Error(MTP_rpc_error(MTP_int(400),
			MTP_string("CAPY_READ_RECEIPT_SUPPRESSED")));
		handler.fail(error, Response{ .requestId = requestId });
	}
}

void Instance::Private::processCallback(const Response &response) {''')
    if name == PREFIX + 'main/main_session_settings.h':
        text = replace(text, '\t[[nodiscard]] QByteArray serialize() const;', '''	void setCapySilentRead(bool value) { _capySilentRead = value; }
	[[nodiscard]] bool capySilentRead() const { return _capySilentRead; }
	[[nodiscard]] QByteArray serialize() const;''')
        return replace(text, '\tstd::vector<Data::ReactionId> _extraFavoriteReactions;',
            '\tstd::vector<Data::ReactionId> _extraFavoriteReactions;\n\tbool _capySilentRead = false;')
    if name == PREFIX + 'main/main_session_settings.cpp':
        text = replace(text, '\tauto result = QByteArray();',
            '\tsize += 3 * sizeof(qint32); // Capy extension tag, version, silent-read\n\n\tauto result = QByteArray();')
        text = replace(text, '''			stream << quint64(id.custom()) << id.emoji();
		}
	}

	Ensures(result.size() == size);''', '''			stream << quint64(id.custom()) << id.emoji();
		}
		stream << qint32(0x43524731) << qint32(1) << qint32(_capySilentRead ? 1 : 0);
	}

	Ensures(result.size() == size);''')
        text = replace(text, '\tstd::vector<Data::ReactionId> extraFavoriteReactions;',
            '\tstd::vector<Data::ReactionId> extraFavoriteReactions;\n\tbool capySilentRead = false;')
        old = '''	_phoneNumberHidden = (phoneNumberHidden == 1);
	_extraFavoriteReactions = std::move(extraFavoriteReactions);'''
        # Upstream validates/commits its fields before reading our optional tail.
        # Unknown/truncated metadata defaults off and cannot corrupt account data.
        return replace(text, old, old + '''
	if (!stream.atEnd()) {
		qint32 capyTag = 0, capyVersion = 0, capyValue = 0;
		stream >> capyTag >> capyVersion >> capyValue;
		capySilentRead = (stream.status() == QDataStream::Ok
			&& capyTag == 0x43524731 && capyVersion == 1 && capyValue == 1);
	}
	_capySilentRead = capySilentRead;''')
    if name == PREFIX + 'main/main_session.cpp':
        return replace(text, '\tExpects(_settings != nullptr);',
            '\tExpects(_settings != nullptr);\n\tmtp().setCapySilentRead(_settings->capySilentRead());')
    if name == PREFIX + 'main/main_account.cpp':
        return replace(text, 'void Account::destroySession(DestroyReason reason) {\n',
            'void Account::destroySession(DestroyReason reason) {\n\tif (_mtp) _mtp->resetCapyReadMode();\n')
    if name == PREFIX + 'window/window_peer_menu.cpp':
        text = replace(text, '#include "window/window_peer_menu.h"',
            '#include "window/window_peer_menu.h"\n#include "capybara/capy_read_mode_ui.h"')
        return replace(text, '\tCapy::AddNoteAction(controller, request, callback);',
            '\tCapy::AddNoteAction(controller, request, callback);\n\tCapy::AddReadModeAction(controller, request, callback);')
    if name == PREFIX + 'history/view/history_view_top_bar_widget.cpp':
        text = replace(text, '#include "capybara/capy_notes_ui.h"',
            '#include "capybara/capy_notes_ui.h"\n#include "capybara/capy_read_mode_ui.h"')
        text = replace(text, '\tCapy::AddNoteAction(_controller, _activeChat, addAction);',
            '\tCapy::AddNoteAction(_controller, _activeChat, addAction);\n\tCapy::AddReadModeAction(_controller, _activeChat, addAction);')
        text = replace(text, 'u"CapybaraGram · Notes / Templates"_q', 'u"CapybaraGram · Notes / Templates / Silent reading"_q')
        return replace(text, 'u"CapybaraGram · Заметки / Шаблоны"_q', 'u"CapybaraGram · Заметки / Шаблоны / Нечиталка"_q')
    if name == PREFIX + 'data/data_histories.cpp':
        text = replace(text, '#include "data/data_histories.h"',
            '#include "data/data_histories.h"\n#include "mtproto/mtp_instance.h"')
        text = replace(text, 'void Histories::readInbox(not_null<History*> history) {\n',
            'void Histories::readInbox(not_null<History*> history) {\n\tif (session().mtp().capySilentRead()) return;\n')
        text = replace(text, '''		bool force) {
	Expects(IsServerMsgId(tillId) || (!tillId && !force));''', '''		bool force) {
	if (session().mtp().capySilentRead()) return;
	Expects(IsServerMsgId(tillId) || (!tillId && !force));''')
        return replace(text, 'void Histories::sendReadRequest(not_null<History*> history, State &state) {\n', '''void Histories::sendReadRequest(not_null<History*> history, State &state) {
	if (session().mtp().capySilentRead()) {
		state.willReadTill = 0;
		state.willReadWhen = 0;
		return;
	}
''')
    if name in (PREFIX + 'data/data_replies_list.cpp', PREFIX + 'data/data_saved_sublist.cpp'):
        replies = name.endswith('data_replies_list.cpp')
        kind = 'RepliesList' if replies else 'SavedSublist'
        session = '_history->session()' if replies else '_parent->session()'
        include = 'data/data_replies_list.h' if replies else 'data/data_saved_sublist.h'
        text = replace(text, '#include "' + include + '"',
            '#include "' + include + '"\n#include "mtproto/mtp_instance.h"')
        old = '''		HistoryItem *tillIdItem) {
	if (!IsServerMsgId(tillId)) {'''
        text = replace(text, old, '''		HistoryItem *tillIdItem) {
	if (''' + session + '''.mtp().capySilentRead()) return;
	if (!IsServerMsgId(tillId)) {''')
        return replace(text, 'void ' + kind + '::sendReadTillRequest() {\n', 'void ' + kind + '''::sendReadTillRequest() {
	if (''' + session + '''.mtp().capySilentRead()) {
		_readRequestTimer.cancel();
		''' + session + '''.api().request(base::take(_readRequestId)).cancel();
		return;
	}
''')
    raise ValueError('Unexpected Windows read-mode target')


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def plan(source, check=False):
    source = Path(source).resolve(strict=True)
    manifest = json.loads((HERE / 'windows-read-mode-hashes.json').read_text(encoding='utf-8'))
    if manifest['source_sha'] != SOURCE_SHA or set(manifest['pre']) != set(FILES) or set(manifest['post']) != set(FILES) or set(manifest['added']) != set(ADDED):
        raise ValueError('Windows read-mode allowlist differs')
    result = {}
    for name in FILES:
        path = source / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):
            raise ValueError('Unsafe read-mode source path')
        data = path.read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['post' if check else 'pre'][name]:
            raise ValueError('Windows read-mode input differs: ' + name)
        output = data if check else transform(name, data.decode('utf-8')).encode('utf-8')
        if digest(output) != manifest['post'][name]:
            raise ValueError('Windows read-mode output differs: ' + name)
        result[name] = output
    for name, path in ADDED.items():
        data = path.read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['added'][name]:
            raise ValueError('Added read-mode source changed: ' + name)
        target = source / name
        if target.is_symlink() or not target.resolve().is_relative_to(source):
            raise ValueError('Unsafe added source path')
        if check:
            if not target.is_file() or digest(target.read_bytes()) != digest(data):
                raise ValueError('Added read-mode source differs: ' + name)
        elif target.exists():
            raise ValueError('Read-mode source already exists: ' + name)
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
        raise ValueError('Wrong Windows source revision')
    changes = plan(args.source, args.check)
    if not args.check:
        for name, data in changes.items():
            target = args.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    print('PASS: native Windows read-mode integration', 'verified' if args.check else 'prepared')
