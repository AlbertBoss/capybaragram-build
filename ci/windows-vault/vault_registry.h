// SPDX-License-Identifier: MIT
#pragma once

#include "vault_store.h"
#include <memory>

namespace Capy::Vault {

// Persistent account -> generation mapping. Confined to the same worker as Store.
// UI lock/account epochs are additionally required at the Telegram host boundary.
class Registry final {
public:
	Registry(const std::filesystem::path &root, int slots);
	[[nodiscard]] std::unique_ptr<Store> open(int slot, std::uint64_t owner,
		bool freshLogin = false);
	void logout(int slot, std::uint64_t expectedOwner);
	// Forgotten app passcode: no authenticated owner/session is available.
	// Persists a reset barrier before retiring any generation.
	void forgetAll();
	// Retries pending cleanup; returns false if at least one entry still needs retry.
	[[nodiscard]] bool retryCleanup();

private:
	struct Binding {
		std::uint64_t owner;
		std::string generation;
	};
	[[nodiscard]] static std::string Encode(const Binding &binding);
	[[nodiscard]] static Binding Decode(const std::string &value);
	[[nodiscard]] std::string slotKey(int slot) const;
	[[nodiscard]] std::optional<Binding> binding(int slot);
	void retire(const Binding &binding);
	void clean(const std::string &record);
	[[nodiscard]] bool referenced(const std::string &generation);
	void finishReset();
	const std::filesystem::path _root;
	const int _slots;
	Store _index;
};

} // namespace Capy::Vault
