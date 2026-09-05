// SPDX-License-Identifier: MIT
#pragma once

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace Capy::Vault {

// Call from one serialized worker. UI account/lock epochs belong to the host.
// DPAPI protects against other Windows users, not code running as this user.
class Store final {
public:
	static constexpr auto MaxPayload = std::size_t(131040);
	[[nodiscard]] static std::string NewId();
	[[nodiscard]] static std::string Note(int type, std::uint64_t peer,
		std::uint64_t topic = 0);
	[[nodiscard]] static std::string Template(const std::string &id);
	// For the registry's durable cleanup queue, including after process restart.
	static void RetireGeneration(const std::filesystem::path &root,
		const std::string &generation);

	Store(const std::filesystem::path &root, std::uint64_t owner,
		const std::string &generation, bool create);
	Store(const Store &) = delete;
	Store &operator=(const Store &) = delete;

	[[nodiscard]] std::optional<std::string> read(const std::string &record) const;
	void write(const std::string &record, const std::string &text) const;
	void erase(const std::string &record) const;
	[[nodiscard]] std::vector<std::string> templates() const;
	// Durable retirement marker stays in place even if cleanup is interrupted.
	// Caller must persist a new generation for subsequent login, including same owner.
	void retire() const;

private:
	void checkThread() const;
	void checkActive() const;
	[[nodiscard]] std::string entropy(const std::string &record) const;
	[[nodiscard]] std::filesystem::path path(const std::string &record) const;
	const std::filesystem::path _directory;
	const std::string _identity;
	const std::thread::id _thread;
};

} // namespace Capy::Vault
