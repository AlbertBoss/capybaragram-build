// SPDX-License-Identifier: MIT
#pragma once

#include "capybara/connection_worker.h"
#include "rpl/event_stream.h"
#include <QObject>

namespace Capy::Connection {

// Main-thread owner. Transport startup/shutdown stays in Worker; no settings
// serialization or account credentials enter this controller.
class Service final : public QObject {
public:
	enum class Phase { Disabled, Starting, Ready, Failed };
	Service();
	~Service() override;
	void setEnabled(bool enabled);
	// Application calls this before changing the user's normal proxy settings.
	// It revokes a pending result without emitting a second proxy-change event.
	void manualProxySelected();
	[[nodiscard]] bool enabled() const;
	[[nodiscard]] Phase phase() const;
	[[nodiscard]] CapyConnectionStatus status() const;
	[[nodiscard]] rpl::producer<> changes() const;
	Service(const Service &) = delete;
	Service &operator=(const Service &) = delete;
private:
	void completed(std::shared_ptr<const Worker::Result> result);
	std::unique_ptr<Worker> _worker;
	std::uint64_t _revision = 0;
	bool _enabled = false;
	Phase _phase = Phase::Disabled;
	rpl::event_stream<> _changes;
};

} // namespace Capy::Connection
