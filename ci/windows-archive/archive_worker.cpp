// SPDX-License-Identifier: MIT
#include "archive_worker.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdexcept>
#include <utility>

namespace Capy::Archive {
namespace {
struct Release final {
	std::atomic<unsigned> &counter;
	~Release() { --counter; }
};
struct ReleaseBytes final {
	std::atomic<std::size_t> &counter;
	std::size_t bytes;
	~ReleaseBytes() { counter -= bytes; }
};
struct Wipe final {
	Snapshot &snapshot;
	~Wipe() {
		if (!snapshot.text.empty()) SecureZeroMemory(snapshot.text.data(), snapshot.text.size());
		if (!snapshot.content.empty()) SecureZeroMemory(snapshot.content.data(), snapshot.content.size());
	}
};
struct WipeResult final {
	Worker::Result &result;
	~WipeResult() {
		if (!result.media.empty()) SecureZeroMemory(result.media.data(), result.media.size());
		if (result.snapshot) {
			const auto wipe = Wipe{*result.snapshot};
		}
		for (auto &snapshot : result.snapshots) {
			const auto wipe = Wipe{snapshot};
		}
	}
};
} // namespace

struct Worker::Gate final {
	std::atomic<bool> alive = true;
	std::atomic<bool> locked = false;
	std::atomic<std::uint64_t> epoch = 0;
};

struct Worker::Session final {
	Session(int slotValue, std::uint64_t ownerValue, std::string authorizationValue,
		std::shared_ptr<Gate> gateValue)
	: slot(slotValue), owner(ownerValue), authorization(std::move(authorizationValue))
	, gate(std::move(gateValue)) {}
	const int slot;
	const std::uint64_t owner;
	const std::string authorization;
	const std::shared_ptr<Gate> gate;
	std::atomic<bool> live = true;
	std::atomic<bool> enabled = false;
	std::atomic<std::uint64_t> revision = 0;
};

Worker::Worker(std::filesystem::path root, int slots, Post post)
: _root(std::move(root)), _slots(slots), _post(std::move(post))
, _uiThread(std::this_thread::get_id()), _gate(std::make_shared<Gate>()) {
	if (!_root.is_absolute() || slots < 1 || slots > 256 || !_post) {
		throw std::invalid_argument("Invalid CapybaraGram archive worker configuration");
	}
	_sessions.resize(slots);
	_storage.resize(slots);
	_thread = std::thread([this] { loop(); });
}

Worker::~Worker() {
	_gate->alive = false;
	for (const auto &session : _sessions) if (session) session->live = false;
	{
		const auto lock = std::lock_guard(_mutex);
		_stopping = true;
	}
	_wake.notify_one();
	_thread.join();
}

void Worker::checkThread() const {
	if (std::this_thread::get_id() != _uiThread) {
		throw std::logic_error("Archive worker called outside UI thread");
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
		try { work(); } catch (const std::exception &) { }
	}
	_storage.clear();
	_registry.reset();
}

Vault::Registry &Worker::registry() {
	if (!_registry) _registry = std::make_unique<Vault::Registry>(_root, _slots);
	if (_resetPending) {
		_registry->forgetAll();
		_resetPending = false;
	}
	return *_registry;
}

Store &Worker::store(const Handle &handle) {
	auto &slot = _storage[handle->slot];
	if (slot.session != handle) throw std::logic_error("Stale archive session");
	if (slot.clearPending) {
		slot.archive.reset();
		slot.vault.reset();
		registry().logout(handle->slot, handle->owner, handle->authorization);
		slot.fresh = true;
		slot.clearPending = false;
		slot.recoveryPending = false;
	}
	if (!slot.vault) {
		slot.vault = registry().open(handle->slot, handle->owner, slot.fresh, handle->authorization);
		slot.fresh = false; // only after successful owner-bound opening
	}
	if (!slot.archive) slot.archive = std::make_unique<Store>(*slot.vault);
	if (slot.recoveryPending) {
		slot.archive->recover();
		slot.recoveryPending = false;
	}
	return *slot.archive;
}

Worker::Handle Worker::attach(int slotIndex, std::uint64_t owner, bool freshLogin,
		std::string authorization) {
	checkThread();
	if (slotIndex < 0 || slotIndex >= _slots || !owner) return {};
	try { (void)Vault::Store::Template(authorization); }
	catch (const std::exception &) { return {}; }
	if (_sessions[slotIndex]) detach(_sessions[slotIndex], false);
	const auto handle = std::make_shared<Session>(slotIndex, owner, std::move(authorization), _gate);
	_sessions[slotIndex] = handle;
	enqueue([this, handle, freshLogin] {
		auto &slot = _storage[handle->slot];
		slot.archive.reset();
		slot.vault.reset();
		slot.session = handle;
		slot.fresh = freshLogin;
		slot.clearPending = false;
		slot.recoveryPending = false;
		// Storage stays lazy until an enabled capture or explicit archive request.
	});
	return handle;
}

void Worker::detach(Handle handle, bool loggedOut) {
	checkThread();
	if (!handle || handle->gate != _gate || _sessions[handle->slot] != handle) return;
	handle->live = false;
	++handle->revision;
	_sessions[handle->slot].reset();
	enqueue([this, handle, loggedOut] {
		auto &slot = _storage[handle->slot];
		if (slot.session != handle) return;
		slot.archive.reset();
		slot.vault.reset();
		slot.session.reset();
		if (loggedOut) registry().logout(handle->slot, handle->owner, handle->authorization);
	});
}

void Worker::setLocked(bool locked) {
	checkThread();
	if (_gate->locked.exchange(locked) != locked) ++_gate->epoch;
}

void Worker::setEnabled(const Handle &handle, bool value) {
	checkThread();
	if (handle && Current(_gate, handle, handle->revision)) handle->enabled = value;
}

bool Worker::Current(const std::shared_ptr<Gate> &gate, const Handle &handle,
		std::uint64_t revision) {
	return handle && handle->gate == gate && handle->live && gate->alive
		&& handle->revision == revision;
}

bool Worker::Visible(const std::shared_ptr<Gate> &gate, const Handle &handle,
		std::uint64_t revision, std::uint64_t epoch) {
	return Current(gate, handle, revision) && !gate->locked && gate->epoch == epoch;
}

bool Worker::usable(const Handle &handle) const {
	checkThread();
	return handle && Visible(_gate, handle, handle->revision, _gate->epoch);
}

bool Worker::enabled(const Handle &handle) const {
	checkThread();
	return handle && Current(_gate, handle, handle->revision) && handle->enabled;
}

void Worker::post(const Handle &handle, std::uint64_t revision, std::uint64_t epoch,
		Result result, Done done) {
	const auto resultWipe = WipeResult{result};
	if (!done || !Visible(_gate, handle, revision, epoch)) return;
	_post([gate = _gate, handle, revision, epoch, result = std::move(result),
			done = std::move(done)]() mutable {
		// No Worker pointer: UI callbacks may outlive destruction.
		const auto wipe = WipeResult{result};
		if (Visible(gate, handle, revision, epoch)) done(std::move(result));
	});
}

bool Worker::capture(const Handle &handle, Snapshot snapshot, std::uint64_t bytes,
		Store::Reader reader, Done done) {
	checkThread();
	const auto media = bool(reader);
	const auto weight = snapshot.text.size() + snapshot.content.size() + snapshot.mime.size() + 192;
	if (!enabled(handle) || (media ? _captures >= 4 : _textCaptures >= 2000)
		|| weight > 64 * 1024 * 1024 || _queuedTextBytes > 64 * 1024 * 1024 - weight
		|| bytes > Store::MaxMediaBytes
		|| (bytes != 0) != bool(reader) || snapshot.text.size() > 60000
		|| snapshot.content.size() > 60000 || snapshot.mime.size() > 128) return false;
	const auto revision = handle->revision.load();
	const auto epoch = _gate->epoch.load();
	++(media ? _captures : _textCaptures);
	_queuedTextBytes += weight;
	try {
		enqueue([this, handle, revision, epoch, snapshot = std::move(snapshot), bytes, media, weight,
				reader = std::move(reader), done = std::move(done)]() mutable {
			const auto release = Release{media ? _captures : _textCaptures};
			const auto releaseBytes = ReleaseBytes{_queuedTextBytes, weight};
			const auto wipe = Wipe{snapshot};
			if (!Current(_gate, handle, revision)) return;
			auto result = Result();
			try {
				auto guarded = reader ? Store::Reader([gate = _gate, handle, revision,
					reader = std::move(reader)](std::span<char> out) {
					if (!Current(gate, handle, revision)) throw std::runtime_error("Revoked archive capture");
					return reader(out);
				}) : Store::Reader();
				const auto added = store(handle).add(snapshot, bytes, std::move(guarded));
				result.ok = true;
				result.id = added.id;
				result.cleanupPending = added.cleanupPending;
				_storage[handle->slot].recoveryPending = added.cleanupPending;
			} catch (const std::exception &) {
				_storage[handle->slot].recoveryPending = true;
			}
			post(handle, revision, epoch, std::move(result), std::move(done));
		});
	} catch (...) {
		--(media ? _captures : _textCaptures);
		_queuedTextBytes -= weight;
		throw;
	}
	return true;
}

bool Worker::request(const Handle &handle, Operation operation, Done done) {
	checkThread();
	if (!usable(handle) || _requests >= 8) return false;
	const auto revision = handle->revision.load();
	const auto epoch = _gate->epoch.load();
	++_requests;
	try {
		enqueue([this, handle, revision, epoch, operation = std::move(operation),
				done = std::move(done)]() mutable {
			const auto release = Release{_requests};
			if (!Visible(_gate, handle, revision, epoch)) return;
			auto result = Result();
			try { result = operation(store(handle)); }
			catch (const std::exception &) { }
			post(handle, revision, epoch, std::move(result), std::move(done));
		});
	} catch (...) {
		--_requests;
		throw;
	}
	return true;
}

bool Worker::page(const Handle &handle, std::size_t offset, Done done) {
	return request(handle, [offset](Store &store) {
		auto result = Result();
		result.ids = store.page(offset);
		result.ok = true;
		return result;
	}, std::move(done));
}

bool Worker::pageFor(const Handle &handle, Conversation conversation,
		std::size_t offset, Done done) {
	return request(handle, [conversation, offset](Store &store) {
		auto result = Result();
		result.ids = store.pageFor(conversation, offset);
		for (const auto &id : result.ids) result.snapshots.push_back(store.read(id));
		result.ok = true;
		return result;
	}, std::move(done));
}

bool Worker::read(const Handle &handle, std::string id, Done done) {
	return request(handle, [id = std::move(id)](Store &store) {
		auto result = Result();
		result.snapshot = store.read(id);
		result.ok = true;
		return result;
	}, std::move(done));
}

bool Worker::media(const Handle &handle, std::string id, Done done) {
	return request(handle, [id = std::move(id)](Store &store) {
		auto result = Result();
		result.media = store.media(id);
		result.ok = true;
		return result;
	}, std::move(done));
}

void Worker::clear(const Handle &handle, Done done) {
	checkThread();
	if (!usable(handle)) return;
	const auto revision = ++handle->revision;
	const auto epoch = _gate->epoch.load();
	enqueue([this, handle, revision, epoch, done = std::move(done)]() mutable {
		if (!Current(_gate, handle, revision)) return;
		auto result = Result();
		try {
			_storage[handle->slot].clearPending = true;
			(void)store(handle);
			result.ok = true;
		} catch (const std::exception &) { }
		post(handle, revision, epoch, std::move(result), std::move(done));
	});
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
			slot.archive.reset();
			slot.vault.reset();
			slot.session.reset();
		}
		_resetPending = true;
		(void)registry();
	});
}

} // namespace Capy::Archive
