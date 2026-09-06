// SPDX-License-Identifier: MIT
#include "vault_worker.h"
#include <stdexcept>
#include <utility>

namespace Capy::Vault {

struct Worker::Session {
	Session(int slotValue, std::uint64_t ownerValue, std::string authorizationValue,
		std::shared_ptr<Gate> gateValue)
	: slot(slotValue), owner(ownerValue), authorization(std::move(authorizationValue)), gate(std::move(gateValue)) {
	}
	const int slot;
	const std::uint64_t owner;
	const std::string authorization;
	const std::shared_ptr<Gate> gate;
	std::atomic<bool> live = true;
};

struct Worker::Gate {
	std::atomic<bool> alive = true;
	std::atomic<bool> locked = false;
	std::atomic<std::uint64_t> epoch = 0;
};

Worker::Worker(std::filesystem::path root, int slots, Post post)
: _root(std::move(root))
, _slots(slots)
, _post(std::move(post))
, _uiThread(std::this_thread::get_id())
, _gate(std::make_shared<Gate>()) {
	if (!_root.is_absolute() || slots < 1 || slots > 256 || !_post) {
		throw std::invalid_argument("Invalid CapybaraGram worker configuration");
	}
	_sessions.resize(slots);
	_storage.resize(slots);
	_thread = std::thread([this] { loop(); });
}

Worker::~Worker() {
	_gate->alive = false;
	for (const auto &session : _sessions) {
		if (session) session->live = false;
	}
	{
		const auto lock = std::lock_guard(_mutex);
		_stopping = true;
	}
	_wake.notify_one();
	_thread.join();
}

void Worker::checkThread() const {
	if (std::this_thread::get_id() != _uiThread) {
		throw std::logic_error("CapybaraGram worker called outside UI thread");
	}
}

void Worker::enqueue(std::function<void()> work) {
	{
		const auto lock = std::lock_guard(_mutex);
		_queue.push_back(std::move(work));
	}
	_wake.notify_one();
}

void Worker::loop() {
	for (;;) {
		auto work = std::function<void()>();
		{
			auto lock = std::unique_lock(_mutex);
			_wake.wait(lock, [this] { return _stopping || !_queue.empty(); });
			if (_queue.empty()) break;
			work = std::move(_queue.front());
			_queue.pop_front();
		}
		// Each user operation produces an explicit failed result. Maintenance
		// can fail (e.g. locked files); its durable Registry journal is retried.
		try { work(); } catch (const std::exception &) { }
	}
	_storage.clear();
	_registry.reset();
}

Registry &Worker::registry() {
	if (!_registry) _registry = std::make_unique<Registry>(_root, _slots);
	if (_resetPending) {
		_registry->forgetAll();
		_resetPending = false;
	}
	return *_registry;
}

Store &Worker::store(const Handle &handle) {
	auto &slot = _storage[handle->slot];
	if (slot.session != handle) throw std::logic_error("Stale vault session");
	if (!slot.store) {
		slot.store = registry().open(handle->slot, handle->owner, slot.fresh, handle->authorization);
		// A failed open must not turn fresh-login intent into restoration.
		slot.fresh = false;
	}
	return *slot.store;
}

Worker::Handle Worker::attach(int slotIndex, std::uint64_t owner, bool freshLogin,
		std::string authorization) {
	checkThread();
	if (slotIndex < 0 || slotIndex >= _slots || !owner) return {};
	try { (void)Store::Template(authorization); }
	catch (const std::exception &) { return {}; }
	if (_sessions[slotIndex]) detach(_sessions[slotIndex], false);
	const auto handle = std::make_shared<Session>(slotIndex, owner, std::move(authorization), _gate);
	_sessions[slotIndex] = handle;
	enqueue([this, handle, freshLogin] {
		auto &slot = _storage[handle->slot];
		slot.store.reset();
		slot.session = handle;
		slot.fresh = freshLogin;
		(void)store(handle);
	});
	return handle;
}

void Worker::detach(Handle handle, bool loggedOut) {
	checkThread();
	// Compare the actual handle, not only the owner: the same user can log in
	// again while an old session's logout callback remains in the UI queue.
	if (!handle || handle->gate != _gate || _sessions[handle->slot] != handle) return;
	handle->live = false;
	_sessions[handle->slot].reset();
	enqueue([this, handle, loggedOut] {
		auto &slot = _storage[handle->slot];
		if (slot.session != handle) return;
		slot.store.reset();
		slot.session.reset();
		if (loggedOut) registry().logout(handle->slot, handle->owner, handle->authorization);
	});
}

void Worker::setLocked(bool locked) {
	checkThread();
	if (_gate->locked.exchange(locked) != locked) ++_gate->epoch;
}

void Worker::forgetAll() {
	checkThread();
	++_gate->epoch;
	for (auto &session : _sessions) {
		if (session) session->live = false;
		session.reset();
	}
	enqueue([this] {
		for (auto &slot : _storage) {
			slot.store.reset();
			slot.session.reset();
		}
		_resetPending = true;
		(void)registry();
	});
}

bool Worker::Current(const std::shared_ptr<Gate> &gate,
		const Handle &handle, std::uint64_t epoch) {
	return handle && handle->gate == gate && handle->live && gate->alive && !gate->locked
		&& gate->epoch == epoch;
}

bool Worker::usable(const Handle &handle) const {
	checkThread();
	return Current(_gate, handle, _gate->epoch);
}

void Worker::request(const Handle &handle, Operation operation, Done done) {
	checkThread();
	const auto epoch = _gate->epoch.load();
	if (!Current(_gate, handle, epoch)) return;
	enqueue([this, gate = _gate, handle, epoch,
			operation = std::move(operation), done = std::move(done)]() mutable {
		if (!Current(gate, handle, epoch)) return;
		auto result = Result();
		try { result = operation(store(handle)); }
		catch (const std::exception &) { }
		if (!Current(gate, handle, epoch)) return;
		_post([gate, handle, epoch, done = std::move(done),
				result = std::move(result)]() mutable {
			// No Worker pointer: callbacks may outlive application shutdown.
			if (Current(gate, handle, epoch) && done) done(std::move(result));
		});
	});
}

void Worker::read(const Handle &handle, std::string record, Done done) {
	request(handle, [record = std::move(record)](Store &store) {
		return Result{ true, store.read(record), {} };
	}, std::move(done));
}

void Worker::write(const Handle &handle, std::string record,
		std::string text, Done done) {
	request(handle, [record = std::move(record), text = std::move(text)](Store &store) {
		store.write(record, text);
		return Result{ true, {}, {} };
	}, std::move(done));
}

void Worker::erase(const Handle &handle, std::string record, Done done) {
	request(handle, [record = std::move(record)](Store &store) {
		store.erase(record);
		return Result{ true, {}, {} };
	}, std::move(done));
}

void Worker::templates(const Handle &handle, Done done) {
	request(handle, [](Store &store) {
		return Result{ true, {}, store.templates() };
	}, std::move(done));
}

} // namespace Capy::Vault
