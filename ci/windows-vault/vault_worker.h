// SPDX-License-Identifier: MIT
#pragma once

#include "vault_registry.h"
#include <atomic>
#include <condition_variable>
#include <deque>
#include <functional>
#include <mutex>
#include <thread>

namespace Capy::Vault {

// Public methods belong to the UI thread. Store and Registry never leave the
// private FIFO worker. Post must enqueue (not synchronously execute) on the UI.
class Worker final {

	struct Session;
	struct Gate;

public:
	using Handle = std::shared_ptr<Session>;
	using Post = std::function<void(std::function<void()>)>;
	struct Result {
		bool ok = false;
		std::optional<std::string> text;
		std::vector<std::string> ids;
	};
	using Done = std::function<void(Result)>;

	Worker(std::filesystem::path root, int slots, Post post);
	~Worker();
	Worker(const Worker &) = delete;
	Worker &operator=(const Worker &) = delete;

	[[nodiscard]] Handle attach(int slot, std::uint64_t owner, bool freshLogin);
	void detach(Handle handle, bool loggedOut);
	void forgetAll();
	void setLocked(bool locked);
	[[nodiscard]] bool usable(const Handle &handle) const;
	void read(const Handle &handle, std::string record, Done done);
	void write(const Handle &handle, std::string record, std::string text, Done done);
	void erase(const Handle &handle, std::string record, Done done);
	void templates(const Handle &handle, Done done);

private:
	using Operation = std::function<Result(Store &)>;
	struct Slot {
		Handle session;
		std::unique_ptr<Store> store;
		bool fresh = false;
	};
	void checkThread() const;
	void enqueue(std::function<void()> work);
	void loop();
	Registry &registry();
	Store &store(const Handle &handle);
	void request(const Handle &handle, Operation operation, Done done);
	[[nodiscard]] static bool Current(const std::shared_ptr<Gate> &gate,
		const Handle &handle, std::uint64_t epoch);

	const std::filesystem::path _root;
	const int _slots;
	const Post _post;
	const std::thread::id _uiThread;
	const std::shared_ptr<Gate> _gate;
	std::vector<Handle> _sessions; // UI thread only
	std::vector<Slot> _storage; // worker only
	std::unique_ptr<Registry> _registry; // worker only
	bool _resetPending = false; // worker only; retry if the reset marker write failed
	std::mutex _mutex;
	std::condition_variable _wake;
	std::deque<std::function<void()>> _queue;
	bool _stopping = false; // guarded by _mutex
	std::thread _thread; // last: every field is initialized before loop starts
};

} // namespace Capy::Vault
