// SPDX-License-Identifier: MIT
#include "vault_worker.h"
#include <chrono>
#include <iostream>
#include <stdexcept>

namespace {
int Checks = 0;
void Check(bool value) {
	if (!value) throw std::runtime_error("Worker assertion failed");
	++Checks;
}

class Mailbox {
public:
	void post(std::function<void()> callback) {
		const auto lock = std::lock_guard(_mutex);
		_queue.push_back(std::move(callback));
		_wake.notify_one();
	}
	std::function<void()> take() {
		auto lock = std::unique_lock(_mutex);
		if (!_wake.wait_for(lock, std::chrono::seconds(15), [&] { return !_queue.empty(); })) {
			throw std::runtime_error("Worker reply timeout");
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
}

int main() {
	using Capy::Vault::Worker;
	using Capy::Vault::Store;
	try {
		const auto root = std::filesystem::absolute("synthetic-vault-worker");
		Check(!std::filesystem::exists(root));
		auto mailbox = Mailbox();
		const auto post = [&](std::function<void()> callback) { mailbox.post(std::move(callback)); };
		const auto note = Store::Note(1,90);
		{
			auto worker = Worker(root,10,post);
			auto handles = std::vector<Worker::Handle>();
			for (auto slot = 0; slot != 10; ++slot) {
				auto handle = worker.attach(slot, static_cast<std::uint64_t>(100+slot), true);
				Check(worker.usable(handle));
				handles.push_back(handle);
				worker.write(handle, note, "slot"+std::to_string(slot), [&](auto result) { Check(result.ok); });
				mailbox.take()();
			}
			for (auto slot = 0; slot != 10; ++slot) {
				worker.read(handles[slot], note, [&, slot](auto result) {
					Check(result.ok && result.text == "slot"+std::to_string(slot));
				});
				mailbox.take()();
			}
			// A result already posted before locking must not reappear on unlock.
			auto staleCalled = false;
			worker.read(handles[0], note, [&](auto) { staleCalled = true; });
			auto stale = mailbox.take();
			worker.setLocked(true);
			Check(!worker.usable(handles[0]));
			worker.setLocked(false);
			stale();
			Check(!staleCalled);
			Check(worker.usable(handles[0]));
			// Same owner, new session: stale detach cannot retire the new generation.
			worker.read(handles[0], note, [&](auto) { staleCalled = true; });
			stale = mailbox.take();
			const auto old = handles[0];
			worker.detach(old,true);
			handles[0] = worker.attach(0,100,true);
			worker.detach(old,true);
			stale();
			Check(!staleCalled && !worker.usable(old));
			worker.read(handles[0], note, [&](auto result) { Check(result.ok && !result.text); });
			mailbox.take()();
			const auto id = Store::NewId();
			worker.write(handles[0], Store::Template(id), "draft only", [&](auto result) { Check(result.ok); });
			mailbox.take()();
			worker.templates(handles[0], [&](auto result) { Check(result.ok && result.ids == std::vector<std::string>{Store::Template(id)}); });
			mailbox.take()();
			worker.erase(handles[0], Store::Template(id), [&](auto result) { Check(result.ok); });
			mailbox.take()();
			worker.templates(handles[0], [&](auto result) { Check(result.ok && result.ids.empty()); });
			mailbox.take()();
			worker.read(handles[0], "../invalid", [&](auto result) { Check(!result.ok); });
			mailbox.take()();
			auto wrongThreadRejected = false;
			auto thread = std::thread([&] {
				try { (void)worker.usable(handles[0]); }
				catch (const std::logic_error &) { wrongThreadRejected = true; }
			});
			thread.join();
			Check(wrongThreadRejected);
			Check(!worker.attach(-1,100,true));
			Check(!worker.attach(10,100,true));
			Check(!worker.attach(0,0,true));
			// Direct replacement goes through the vector-held handle. detach must
			// copy it before clearing that vector element (no dangling alias).
			const auto displaced = handles[1];
			handles[1] = worker.attach(1,101,true);
			Check(!worker.usable(displaced));
			worker.read(handles[1],note,[&](auto result) { Check(result.ok && !result.text); });
			mailbox.take()();
		}
		// Application restart restores existing data. Posted callbacks may outlive it.
		auto calledAfterShutdown = false;
		auto afterShutdown = std::function<void()>();
		{
			auto worker = Worker(root,10,post);
			auto handle = worker.attach(9,109,false);
			worker.read(handle,note,[&](auto result) { Check(result.ok && result.text == "slot9"); });
			mailbox.take()();
			worker.read(handle,note,[&](auto) { calledAfterShutdown = true; });
			afterShutdown = mailbox.take();
			worker.forgetAll();
			Check(!worker.usable(handle));
			handle = worker.attach(9,109,true);
			worker.read(handle,note,[&](auto result) { Check(result.ok && !result.text); });
			mailbox.take()();
			worker.read(handle,note,[&](auto) { calledAfterShutdown = true; });
			auto latest = mailbox.take();
			afterShutdown = [old = std::move(afterShutdown), latest = std::move(latest)] { old(); latest(); };
		}
		afterShutdown();
		Check(!calledAfterShutdown);
		std::cout << "CAPY_WINDOWS_WORKER=PASS checks=" << Checks << '\n';
		return 0;
	} catch (const std::exception &) {
		std::cerr << "CAPY_WINDOWS_WORKER=FAIL (synthetic FIFO lifecycle)\n";
		return 1;
	}
}
