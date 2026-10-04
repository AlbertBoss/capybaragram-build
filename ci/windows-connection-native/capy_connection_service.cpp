// SPDX-License-Identifier: MIT
#include "capybara/capy_connection_service.h"

#include "core/application.h"
#include "mtproto/mtproto_proxy_data.h"

namespace Capy::Connection {

Service::Service() {
	_worker = std::make_unique<Worker>(
		[](std::function<void()> callback) { crl::on_main(std::move(callback)); },
		[this](std::shared_ptr<const Worker::Result> result) {
			completed(std::move(result));
		});
}

Service::~Service() {
	// Worker revokes queued GUI callbacks before joining its control thread.
	_worker.reset();
}

void Service::setEnabled(bool enabled) {
	_enabled = enabled;
	_phase = enabled ? Phase::Starting : Phase::Disabled;
	// Restore the normal route immediately, before asynchronous stop/start.
	Core::App().setCapyConnectionProxy(std::nullopt);
	_revision = _worker->request(enabled);
	if (!_revision) {
		_enabled = false;
		_phase = Phase::Failed;
	}
	_changes.fire({});
}

void Service::manualProxySelected() {
	_enabled = false;
	_phase = Phase::Disabled;
	_revision = _worker->request(false);
	_changes.fire({});
}

bool Service::enabled() const {
	return _enabled;
}

Service::Phase Service::phase() const {
	return _phase;
}

CapyConnectionStatus Service::status() const {
	return _worker->status();
}

rpl::producer<> Service::changes() const {
	return _changes.events();
}

void Service::completed(std::shared_ptr<const Worker::Result> result) {
	if (!result || result->revision != _revision) return;
	if (result->code == Worker::Result::Code::Ready && _enabled) {
		const auto &endpoint = result->endpoint;
		auto proxy = MTP::ProxyData();
		proxy.type = MTP::ProxyData::Type::Mtproto;
		proxy.host = u"127.0.0.1"_q;
		proxy.port = endpoint.port;
		proxy.password = QString::fromLatin1(
			reinterpret_cast<const char*>(endpoint.secret), 34);
		if (endpoint.abi_version == 1
			&& endpoint.secret[34] == 0
			&& proxy.valid()) {
			Core::App().setCapyConnectionProxy(std::move(proxy));
			_phase = Phase::Ready;
		} else {
			_enabled = false;
			_revision = _worker->request(false);
			_phase = Phase::Failed;
			Core::App().setCapyConnectionProxy(std::nullopt);
		}
	} else if (result->code == Worker::Result::Code::Failed) {
		_enabled = false;
		_phase = Phase::Failed;
		Core::App().setCapyConnectionProxy(std::nullopt);
	} else if (!_enabled && _phase != Phase::Failed) {
		_phase = Phase::Disabled;
	}
	_changes.fire({});
}

} // namespace Capy::Connection
