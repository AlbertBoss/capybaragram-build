// SPDX-License-Identifier: MIT
#include "archive_worker.h"
#include <algorithm>
#include <chrono>
#include <iostream>
#include <stdexcept>

namespace {
using Worker = Capy::Archive::Worker;
using Vault = Capy::Vault::Store;
int Checks = 0;
const char *Stage = "start";
void Check(bool value) {
	if (!value) throw std::runtime_error("Archive worker assertion failed");
	++Checks;
}

class Mailbox final {
public:
	void post(std::function<void()> callback) {
		const auto lock = std::lock_guard(_mutex);
		_queue.push_back(std::move(callback));
		_wake.notify_one();
	}
	std::function<void()> take() {
		auto lock = std::unique_lock(_mutex);
		if (!_wake.wait_for(lock, std::chrono::seconds(15), [&] { return !_queue.empty(); })) {
			throw std::runtime_error("Archive worker reply timeout");
		}
		auto result = std::move(_queue.front());
		_queue.pop_front();
		return result;
	}
private:
	std::mutex _mutex;
	std::condition_variable _wake;
	std::deque<std::function<void()>> _queue;
};

class Block final {
public:
	void enter() {
		auto lock = std::unique_lock(_mutex);
		_entered = true;
		_wake.notify_all();
		if (!_wake.wait_for(lock, std::chrono::seconds(15), [&] { return _released; })) {
			throw std::runtime_error("Synthetic reader unblock timeout");
		}
	}
	void wait() {
		auto lock = std::unique_lock(_mutex);
		if (!_wake.wait_for(lock, std::chrono::seconds(15), [&] { return _entered; })) {
			throw std::runtime_error("Synthetic reader start timeout");
		}
	}
	void release() {
		const auto lock = std::lock_guard(_mutex);
		_released = true;
		_wake.notify_all();
	}
private:
	std::mutex _mutex;
	std::condition_variable _wake;
	bool _entered = false;
	bool _released = false;
};

struct Source final {
	std::shared_ptr<Block> block;
	std::shared_ptr<std::atomic<int>> destroyed;
	bool consumed = false;
	~Source() { if (destroyed) ++*destroyed; }
};

Capy::Archive::Store::Reader Reader(std::shared_ptr<Source> source) {
	return [source = std::move(source)](std::span<char> out) {
		if (source->consumed) return std::size_t();
		if (source->block) source->block->enter();
		if (out.empty()) return std::size_t();
		out[0] = 'x';
		source->consumed = true;
		return std::size_t(1);
	};
}

Capy::Archive::Snapshot Message(std::int64_t message = 1) {
	auto result = Capy::Archive::Snapshot();
	result.peerType = 1;
	result.peer = 200;
	result.message = message;
	result.text = "synthetic archive text";
	return result;
}

Worker::Result Page(Worker &worker, const Worker::Handle &handle, Mailbox &mailbox) {
	auto result = Worker::Result();
	Check(worker.page(handle, 0, [&](auto value) { result = std::move(value); }));
	mailbox.take()();
	Check(result.ok);
	return result;
}

std::string Capture(Worker &worker, const Worker::Handle &handle, Mailbox &mailbox,
		Capy::Archive::Snapshot message = Message()) {
	auto result = Worker::Result();
	Check(worker.capture(handle, std::move(message), 0, {},
		[&](auto value) { result = std::move(value); }));
	mailbox.take()();
	Check(result.ok && !result.cleanupPending && !result.id.empty());
	return result.id;
}

void Lifecycle() {
	Stage = "ten-account lifecycle";
	const auto root = std::filesystem::absolute("synthetic-archive-worker-" + Vault::NewId());
	auto mailbox = Mailbox();
	const auto post = [&](std::function<void()> callback) { mailbox.post(std::move(callback)); };
	auto authorizations = std::vector<std::string>();
	for (auto i = 0; i != 10; ++i) authorizations.push_back(Vault::NewId());
	auto lastId = std::string();
	{
		auto worker = Worker(root, 10, post);
		auto handles = std::vector<Worker::Handle>();
		auto ids = std::vector<std::string>();
		for (auto slot = 0; slot != 10; ++slot) {
			auto handle = worker.attach(slot, static_cast<std::uint64_t>(100 + slot), true, authorizations[slot]);
			Check(worker.usable(handle) && !worker.enabled(handle));
			Check(!worker.capture(handle, Message()));
			worker.setEnabled(handle, true);
			Check(worker.enabled(handle));
			auto message = Message(slot + 1);
			message.text = "slot" + std::to_string(slot);
			ids.push_back(Capture(worker, handle, mailbox, message));
			handles.push_back(handle);
		}
		for (auto slot = 0; slot != 10; ++slot) {
			Check(Page(worker, handles[slot], mailbox).ids == std::vector<std::string>{ids[slot]});
			Check(worker.read(handles[slot], ids[slot], [&, slot](auto result) {
				Check(result.ok && result.snapshot && result.snapshot->text == "slot" + std::to_string(slot));
			}));
			mailbox.take()();
		}
		Check(worker.read(handles[0], ids[1], [&](auto result) { Check(!result.ok); }));
		mailbox.take()();
		Check(worker.pageFor(handles[0], {1, 200, {}}, 0, [&](auto result) {
			Check(result.ok && result.ids == std::vector<std::string>{ids[0]}
				&& result.snapshots.size() == 1 && result.snapshots[0].text == "slot0");
		}));
		mailbox.take()();
		Check(worker.pageFor(handles[0], {2, 200, {}}, 0, [&](auto result) {
			Check(result.ok && result.ids.empty() && result.snapshots.empty());
		}));
		mailbox.take()();
		Check(worker.media(handles[0], ids[0], [&](auto result) { Check(!result.ok); }));
		mailbox.take()();
		auto staleCalled = false;
		Check(worker.page(handles[0], 0, [&](auto) { staleCalled = true; }));
		auto stale = mailbox.take();
		worker.setLocked(true);
		Check(!worker.usable(handles[0]));
		Check(!worker.page(handles[0], 0, {}));
		Check(worker.capture(handles[0], Message(11), 0, {}, [&](auto) { staleCalled = true; }));
		worker.setLocked(false);
		stale();
		Check(!staleCalled && Page(worker, handles[0], mailbox).ids.size() == 2);
		worker.setEnabled(handles[0], false);
		Check(!worker.capture(handles[0], Message(12)));
		Check(Page(worker, handles[0], mailbox).ids.size() == 2);
		worker.setEnabled(handles[0], true);
		// Results posted before clear must not disclose the retired generation.
		Check(worker.read(handles[0], ids[0], [&](auto) { staleCalled = true; }));
		stale = mailbox.take();
		worker.clear(handles[0], [&](auto result) { Check(result.ok); });
		stale();
		mailbox.take()();
		Check(!staleCalled && Page(worker, handles[0], mailbox).ids.empty());
		Check(Page(worker, handles[1], mailbox).ids == std::vector<std::string>{ids[1]});
		const auto old = handles[0];
		worker.detach(old, true);
		handles[0] = worker.attach(0, 100, true, Vault::NewId());
		worker.detach(old, true); // stale logout cannot retire new login
		worker.setEnabled(handles[0], true);
		Check(!worker.usable(old) && Page(worker, handles[0], mailbox).ids.empty());
		(void)Capture(worker, handles[0], mailbox);
		Check(!worker.attach(0, 100, false, "invalid"));
		Check(worker.usable(handles[0]));
		lastId = ids[9];
	}
	Stage = "restart, authorization rotation and shutdown";
	auto afterShutdown = std::function<void()>();
	auto staleCalled = false;
	{
		auto worker = Worker(root, 10, post);
		auto handle = worker.attach(9, 109, false, authorizations[9]);
		Check(Page(worker, handle, mailbox).ids == std::vector<std::string>{lastId});
		Check(!worker.enabled(handle)); // opt-in supplied by host settings, not stale process memory
		handle = worker.attach(9, 109, false, Vault::NewId());
		Check(Page(worker, handle, mailbox).ids.empty());
		worker.setEnabled(handle, true);
		(void)Capture(worker, handle, mailbox);
		worker.forgetAll();
		Check(!worker.usable(handle));
		handle = worker.attach(9, 109, true, authorizations[9]);
		Check(Page(worker, handle, mailbox).ids.empty());
		Check(worker.page(handle, 0, [&](auto) { staleCalled = true; }));
		afterShutdown = mailbox.take();
	}
	afterShutdown();
	Check(!staleCalled);
}

void BoundedAndRevoked() {
	Stage = "bounded captures, exact resource release";
	const auto root = std::filesystem::absolute("synthetic-archive-bounds-" + Vault::NewId());
	auto mailbox = Mailbox();
	auto worker = Worker(root, 2, [&](auto callback) { mailbox.post(std::move(callback)); });
	auto handle = worker.attach(0, 300, true, Vault::NewId());
	worker.setEnabled(handle, true);
	auto block = std::make_shared<Block>();
	auto destroyed = std::make_shared<std::atomic<int>>(0);
	auto source = std::make_shared<Source>();
	source->block = block;
	source->destroyed = destroyed;
	Check(worker.capture(handle, Message(1), 1, Reader(source)));
	source.reset();
	block->wait();
	for (auto i = 2; i != 5; ++i) {
		source = std::make_shared<Source>();
		source->destroyed = destroyed;
		Check(worker.capture(handle, Message(i), 1, Reader(source)));
		source.reset();
	}
	source = std::make_shared<Source>();
	source->destroyed = destroyed;
	Check(!worker.capture(handle, Message(5), 1, Reader(source)));
	source.reset();
	Check(*destroyed == 1);
	worker.setEnabled(handle, false); // already admitted captures may finish
	worker.setLocked(true);
	worker.setLocked(false);
	block->release();
	const auto page = Page(worker, handle, mailbox);
	Check(page.ids.size() == 4 && *destroyed == 5);
	Check(worker.media(handle, page.ids[0], [&](auto result) {
		Check(result.ok && result.media == "x");
	}));
	mailbox.take()();
	Stage = "bounded foreground requests";
	worker.setEnabled(handle, true);
	block = std::make_shared<Block>();
	source = std::make_shared<Source>();
	source->block = block;
	Check(worker.capture(handle, Message(6), 1, Reader(source)));
	source.reset();
	block->wait();
	auto replies = 0;
	for (auto i = 0; i != 8; ++i) {
		Check(worker.page(handle, 0, [&](auto result) { Check(result.ok); ++replies; }));
	}
	Check(!worker.page(handle, 0, {}));
	block->release();
	for (auto i = 0; i != 8; ++i) mailbox.take()();
	Check(replies == 8);
	Stage = "logout during a held original read and same-slot reuse";
	block = std::make_shared<Block>();
	destroyed = std::make_shared<std::atomic<int>>(0);
	source = std::make_shared<Source>();
	source->block = block;
	source->destroyed = destroyed;
	auto staleCalled = false;
	const auto old = handle;
	Check(worker.capture(old, Message(7), 1, Reader(source), [&](auto) { staleCalled = true; }));
	source.reset();
	block->wait();
	source = std::make_shared<Source>();
	source->destroyed = destroyed;
	Check(worker.capture(old, Message(8), 1, Reader(source), [&](auto) { staleCalled = true; }));
	source.reset();
	worker.detach(old, true);
	handle = worker.attach(0, 301, true, Vault::NewId());
	worker.setEnabled(handle, true);
	block->release();
	Check(Page(worker, handle, mailbox).ids.empty() && !staleCalled && *destroyed == 2);
	Check(!worker.capture(old, Message(9)));
	(void)Capture(worker, handle, mailbox);
	Stage = "clear while original read is active";
	block = std::make_shared<Block>();
	source = std::make_shared<Source>();
	source->block = block;
	Check(worker.capture(handle, Message(10), 1, Reader(source), [&](auto) { staleCalled = true; }));
	source.reset();
	block->wait();
	worker.clear(handle, [&](auto result) { Check(result.ok); });
	block->release();
	mailbox.take()();
	Check(Page(worker, handle, mailbox).ids.empty() && !staleCalled);
	(void)Capture(worker, handle, mailbox, Message(11));
	Check(Page(worker, handle, mailbox).ids.size() == 1);
	auto wrongThread = false;
	auto thread = std::thread([&] {
		try { (void)worker.usable(handle); }
		catch (const std::logic_error &) { wrongThread = true; }
	});
	thread.join();
	Check(wrongThread);
}
void BurstBehindMedia() {
	Stage = "64-message text burst behind a held media source";
	const auto root = std::filesystem::absolute("synthetic-archive-burst-" + Vault::NewId());
	auto mailbox = Mailbox();
	auto worker = Worker(root, 2, [&](auto callback) { mailbox.post(std::move(callback)); });
	const auto handle = worker.attach(0, 400, true, Vault::NewId());
	worker.setEnabled(handle, true);
	const auto block = std::make_shared<Block>();
	auto source = std::make_shared<Source>();
	source->block = block;
	Check(worker.capture(handle, Message(1), 1, Reader(source)));
	source.reset();
	block->wait();
	for (auto id = 2; id != 66; ++id) {
		auto snapshot = Message(id);
		snapshot.text = "synthetic burst " + std::to_string(id);
		Check(worker.capture(handle, std::move(snapshot)));
	}
	block->release();
	auto count = std::size_t();
	for (auto offset = std::size_t(); offset < 65; offset += 20) {
		Check(worker.pageFor(handle, {1, 200, {}}, offset, [&](auto result) {
			Check(result.ok && result.ids.size() == result.snapshots.size());
			count += result.ids.size();
			for (const auto &snapshot : result.snapshots) {
				Check(snapshot.message >= 1 && snapshot.message <= 65);
			}
		}));
		mailbox.take()();
	}
	Check(count == 65);
}
} // namespace

int main() {
	try {
		const auto start = std::chrono::steady_clock::now();
		Lifecycle();
		BoundedAndRevoked();
		BurstBehindMedia();
		const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
			std::chrono::steady_clock::now() - start).count();
		std::cout << "CAPY_WINDOWS_ARCHIVE_WORKER=PASS checks=" << Checks
			<< " elapsed_ms=" << elapsed << '\n';
		return 0;
	} catch (const std::exception &) {
		std::cerr << "CAPY_WINDOWS_ARCHIVE_WORKER=FAIL stage=" << Stage << " checks=" << Checks << '\n';
		return 1;
	}
}
