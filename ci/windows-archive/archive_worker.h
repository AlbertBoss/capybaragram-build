// SPDX-License-Identifier: MIT
#pragma once
#include "archive_store.h"
#include "vault_registry.h"
#include <atomic>
#include <condition_variable>
#include <deque>
#include <mutex>

namespace Capy::Archive {

// Public methods: UI thread. Registry, vault and archive: serialized worker.
// Post must enqueue on the UI thread, not invoke synchronously.
class Worker final {
	struct Gate;
	struct Session;
public:
	using Handle = std::shared_ptr<Session>;
	using Post = std::function<void(std::function<void()>)>;
	struct Result final {
		bool ok = false;
		bool cleanupPending = false;
		std::string id;
		std::vector<std::string> ids;
		std::optional<Snapshot> snapshot;
		std::vector<Snapshot> snapshots;
		std::string media;
	};
	using Done = std::function<void(Result)>;
	Worker(std::filesystem::path root, int slots, Post post);
	~Worker();
	Worker(const Worker &) = delete;
	Worker &operator=(const Worker &) = delete;
	[[nodiscard]] Handle attach(int slot, std::uint64_t owner, bool freshLogin,
		std::string authorization = Vault::Registry::LegacyAuthorization);
	void detach(Handle handle, bool loggedOut);
	void forgetAll();
	void setLocked(bool locked);
	void setEnabled(const Handle &handle, bool enabled);
	[[nodiscard]] bool usable(const Handle &handle) const;
	[[nodiscard]] bool enabled(const Handle &handle) const;
	// Max four queued/active captures. Reader must OWN resources (e.g. shared
	// VerifiedInput), not refer to a viewer that can disappear before execution.
	// Encrypted captures already admitted may finish while locked or disabled.
	[[nodiscard]] bool capture(const Handle &handle, Snapshot snapshot,
		std::uint64_t bytes = 0, Store::Reader reader = {}, Done done = {});
	[[nodiscard]] bool page(const Handle &handle, std::size_t offset, Done done);
	[[nodiscard]] bool pageFor(const Handle &handle, Conversation conversation,
		std::size_t offset, Done done);
	[[nodiscard]] bool read(const Handle &handle, std::string id, Done done);
	[[nodiscard]] bool media(const Handle &handle, std::string id, Done done);
	// Revoke old operations immediately, retire only this archive generation.
	void clear(const Handle &handle, Done done);
private:
	struct Slot final {
		Handle session;
		std::unique_ptr<Vault::Store> vault;
		std::unique_ptr<Store> archive; // destroyed before borrowed vault
		bool fresh = false;
		bool clearPending = false;
		bool recoveryPending = false;
	};
	using Operation = std::function<Result(Store &)>;
	void checkThread() const;
	void enqueue(std::function<void()> work);
	void loop();
	Vault::Registry &registry();
	Store &store(const Handle &handle);
	[[nodiscard]] bool request(const Handle &handle, Operation operation, Done done);
	void post(const Handle &handle, std::uint64_t revision, std::uint64_t epoch,
		Result result, Done done);
	[[nodiscard]] static bool Current(const std::shared_ptr<Gate> &gate,
		const Handle &handle, std::uint64_t revision);
	[[nodiscard]] static bool Visible(const std::shared_ptr<Gate> &gate,
		const Handle &handle, std::uint64_t revision, std::uint64_t epoch);
	const std::filesystem::path _root;
	const int _slots;
	const Post _post;
	const std::thread::id _uiThread;
	const std::shared_ptr<Gate> _gate;
	std::vector<Handle> _sessions; // UI only
	std::vector<Slot> _storage; // worker only
	std::unique_ptr<Vault::Registry> _registry; // worker only
	bool _resetPending = false;
	std::atomic<unsigned> _captures = 0;
	std::atomic<unsigned> _requests = 0;
	std::mutex _mutex;
	std::condition_variable _wake;
	std::deque<std::function<void()>> _queue;
	bool _stopping = false;
	std::thread _thread;
};

} // namespace Capy::Archive
