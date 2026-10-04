# SPDX-License-Identifier: MIT
"""Apply a memory-only Telegram route after the pinned archive preparation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
CI = HERE.parent
SOURCE_SHA = '80158983dba09d3bf5d96701f21473d6c34bf5f5'
PREFIX = 'Telegram/SourceFiles/'
FILES = ['Telegram/CMakeLists.txt'] + [PREFIX + p for p in (
    'core/application.h', 'core/application.cpp', 'mtproto/session.cpp',
    'core/proxy_rotation_manager.cpp', 'window/window_peer_menu.cpp')]
ADDED = {PREFIX + 'capybara/' + p: HERE / p for p in (
    'capy_connection_service.h', 'capy_connection_service.cpp',
    'capy_connection_ui.h', 'capy_connection_ui.cpp')}
ADDED.update({PREFIX + 'capybara/' + p: CI / 'windows-connection' / p
              for p in ('connection_worker.h', 'connection_worker.cpp')})
ADDED[PREFIX + 'capybara/native_api.h'] = CI / 'connection/native_api.h'


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Connection anchor differs: ' + before[:90])
    return text.replace(before, after)


def transform(name, text):
    if name == 'Telegram/CMakeLists.txt':
        text = replace(text, '        ${src_loc}/capybara/capy_archive_ui.cpp\n',
            ''.join('        ${src_loc}/capybara/' + p + '\n' for p in (
                'capy_connection_service.h', 'capy_connection_service.cpp',
                'capy_connection_ui.h', 'capy_connection_ui.cpp'))
            + '        ${src_loc}/capybara/capy_archive_ui.cpp\n')
        return replace(text,
            '    target_link_libraries(Telegram PRIVATE crypt32 bcrypt capy_windows_voice)',
            '''    # Rust and the client use the same static release CRT. Debug CRT is
    # intentionally rejected until a separate matching Rust build is verified.
    if(NOT MSVC OR NOT CMAKE_CONFIGURATION_TYPES STREQUAL "Release")
        message(FATAL_ERROR "Capy connection requires the verified MSVC Release profile")
    endif()
    set(CAPY_CONNECTION_LIBRARY "$ENV{CAPY_WINDOWS_CONNECTION_LIBRARY}")
    set(CAPY_CONNECTION_LIBRARY_SHA "$ENV{CAPY_WINDOWS_CONNECTION_LIBRARY_SHA}")
    if(NOT EXISTS "${CAPY_CONNECTION_LIBRARY}" OR NOT CAPY_CONNECTION_LIBRARY_SHA)
        message(FATAL_ERROR "Verified connection library is missing")
    endif()
    file(SHA256 "${CAPY_CONNECTION_LIBRARY}" CAPY_CONNECTION_ACTUAL_SHA)
    if(NOT CAPY_CONNECTION_ACTUAL_SHA STREQUAL CAPY_CONNECTION_LIBRARY_SHA)
        message(FATAL_ERROR "Connection library digest differs")
    endif()
    add_library(capy_connection_rust STATIC IMPORTED)
    set_target_properties(capy_connection_rust PROPERTIES
        IMPORTED_LOCATION "${CAPY_CONNECTION_LIBRARY}")
    add_library(capy_windows_connection STATIC ${src_loc}/capybara/connection_worker.cpp)
    init_target(capy_windows_connection)
    target_include_directories(capy_windows_connection PUBLIC ${src_loc}/capybara)
    set_source_files_properties(${src_loc}/capybara/connection_worker.cpp
        PROPERTIES SKIP_PRECOMPILE_HEADERS ON)
    target_link_libraries(capy_windows_connection PUBLIC capy_connection_rust
        ws2_32 crypt32 secur32 ncrypt bcrypt userenv advapi32 ntdll)
    target_link_libraries(Telegram PRIVATE crypt32 bcrypt capy_windows_voice capy_windows_connection)''')
    if name == PREFIX + 'core/application.h':
        text = replace(text, '#include "base/timer.h"',
            '#include "base/timer.h"\n#include <mutex>\n#include <optional>')
        text = replace(text, 'namespace Capy::Archive { class Worker; }',
            'namespace Capy::Connection { class Service; }\nnamespace Capy::Archive { class Worker; }')
        text = replace(text, '\tvoid proxyRotationSettingsChanged();',
            '\t[[nodiscard]] Capy::Connection::Service &capyConnectionService();\n'
            '\t[[nodiscard]] std::optional<MTP::ProxyData> capyConnectionProxy() const;\n'
            '\tvoid setCapyConnectionProxy(std::optional<MTP::ProxyData> proxy);\n'
            '\tvoid proxyRotationSettingsChanged();')
        return replace(text, '\trpl::event_stream<ProxyChange> _proxyChanges;',
            '\tmutable std::mutex _capyConnectionProxyMutex;\n'
            '\tstd::optional<MTP::ProxyData> _capyConnectionProxy;\n'
            '\tstd::unique_ptr<Capy::Connection::Service> _capyConnectionService;\n'
            '\trpl::event_stream<ProxyChange> _proxyChanges;')
    if name == PREFIX + 'core/application.cpp':
        text = replace(text, '#include "capybara/archive_worker.h"',
            '#include "capybara/archive_worker.h"\n#include "capybara/capy_connection_service.h"')
        text = replace(text, 'Application::~Application() {\n',
            'Application::~Application() {\n\t_capyConnectionService.reset(); // revoke callbacks before windows/domain\n')
        text = replace(text, '''	const auto was = current();
	my.setSelected(proxy);''', '''	const auto was = capyConnectionProxy().value_or(current());
	if (_capyConnectionService) _capyConnectionService->manualProxySelected();
	{
		const auto lock = std::lock_guard(_capyConnectionProxyMutex);
		_capyConnectionProxy.reset();
	}
	my.setSelected(proxy);''')
        text = replace(text, 'void Application::proxyRotationSettingsChanged() {', '''Capy::Connection::Service &Application::capyConnectionService() {
	if (!_capyConnectionService) {
		_capyConnectionService = std::make_unique<Capy::Connection::Service>();
	}
	return *_capyConnectionService;
}

std::optional<MTP::ProxyData> Application::capyConnectionProxy() const {
	const auto lock = std::lock_guard(_capyConnectionProxyMutex);
	return _capyConnectionProxy;
}

void Application::setCapyConnectionProxy(std::optional<MTP::ProxyData> proxy) {
	const auto &normal = settings().proxy();
	const auto saved = normal.isEnabled() ? normal.selected() : MTP::ProxyData();
	auto was = MTP::ProxyData();
	auto now = MTP::ProxyData();
	{
		const auto lock = std::lock_guard(_capyConnectionProxyMutex);
		was = _capyConnectionProxy.value_or(saved);
		_capyConnectionProxy = std::move(proxy);
		now = _capyConnectionProxy.value_or(saved);
	}
	if (was == now) return;
	refreshGlobalProxy();
	_proxyChanges.fire({ was, now }); // native accounts restart, auth keys preserved
	settings().proxy().connectionTypeChangesNotify();
	proxyRotationSettingsChanged();
}

void Application::proxyRotationSettingsChanged() {''')
        text = replace(text, 'void Application::badMtprotoConfigurationError() {\n',
            'void Application::badMtprotoConfigurationError() {\n'
            '\tif (capyConnectionProxy() && _capyConnectionService) {\n'
            '\t\t_capyConnectionService->setEnabled(false);\n'
            '\t\tUi::show(Ui::MakeInformBox(Lang::Hard::ProxyConfigError()));\n'
            '\t\treturn; // never disable the saved normal proxy for a runtime-route error\n\t}\n')
        return replace(text, '''	const auto proxy = proxySettings.isEnabled()
		? proxySettings.selected()
		: MTP::ProxyData();''', '''	const auto proxy = capyConnectionProxy().value_or(proxySettings.isEnabled()
		? proxySettings.selected()
		: MTP::ProxyData());''')
    if name == PREFIX + 'mtproto/session.cpp':
        text = replace(text, '''	const auto &proxy = settings.selected();
	const auto isEnabled = settings.isEnabled();''', '''	const auto runtime = Core::App().capyConnectionProxy();
	const auto proxy = runtime.value_or(settings.selected());
	const auto isEnabled = runtime.has_value() || settings.isEnabled();''')
        return replace(text, '\tconst auto useIPv6 = settings.tryIPv6();',
            '\tconst auto useIPv6 = !runtime.has_value() && settings.tryIPv6();')
    if name == PREFIX + 'core/proxy_rotation_manager.cpp':
        return replace(text, '''bool ProxyRotationManager::shouldObserve() const {
	const auto &settings''', '''bool ProxyRotationManager::shouldObserve() const {
	if (App().capyConnectionProxy()) return false;
	const auto &settings''')
    if name == PREFIX + 'window/window_peer_menu.cpp':
        text = replace(text, '#include "capybara/capy_archive_ui.h"',
            '#include "capybara/capy_archive_ui.h"\n#include "capybara/capy_connection_ui.h"')
        return replace(text, '\tCapy::AddArchiveAction(controller, request, callback);',
            '\tCapy::AddArchiveAction(controller, request, callback);\n'
            '\tCapy::AddConnectionAction(controller, callback);')
    raise ValueError('Unexpected connection host')


def plan(source, check=False):
    source = Path(source).resolve(strict=True)
    manifest = json.loads((HERE / 'native-hashes.json').read_text(encoding='utf-8'))
    if (manifest['source_sha'] != SOURCE_SHA or set(manifest['pre']) != set(FILES)
            or set(manifest['post']) != set(FILES) or set(manifest['added']) != set(ADDED)):
        raise ValueError('Native connection inventory differs')
    result = {}
    for name in FILES:
        path = source / name
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(source):
            raise ValueError('Native connection host escapes checkout')
        data = path.read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['post' if check else 'pre'][name]:
            raise ValueError('Native connection input changed: ' + name)
        output = data if check else transform(name, data.decode('utf-8')).encode('utf-8')
        if digest(output) != manifest['post'][name]:
            raise ValueError('Native connection output changed: ' + name)
        if not check:
            result[name] = output
    for name, payload in ADDED.items():
        if payload.is_symlink() or not payload.resolve(strict=True).is_relative_to(CI):
            raise ValueError('Native connection payload escapes CI package')
        data = payload.read_bytes().replace(b'\r\n', b'\n')
        if digest(data) != manifest['added'][name]:
            raise ValueError('Native connection payload changed: ' + name)
        target = source / name
        if target.is_symlink() or not target.resolve().is_relative_to(source):
            raise ValueError('Native connection destination escapes checkout')
        if check:
            if not target.is_file() or digest(target.read_bytes()) != digest(data):
                raise ValueError('Installed native connection payload changed: ' + name)
        elif target.exists():
            raise ValueError('Native connection payload already exists')
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
        raise ValueError('Wrong native Telegram revision')
    changes = plan(args.source, args.check)  # Check every host/payload before writing.
    if not args.check:
        for name, data in changes.items():
            target = args.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    print('CAPY_WINDOWS_CONNECTION_SOURCE=' + ('CHECKED' if args.check else 'PREPARED'))
