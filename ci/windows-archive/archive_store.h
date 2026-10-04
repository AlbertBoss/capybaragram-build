// SPDX-License-Identifier: MIT
#pragma once

#include "vault_store.h"
#include <array>
#include <functional>
#include <span>

namespace Capy::Archive {

enum class Reason : std::uint8_t { Deleted = 1, Edited = 2, Expired = 3 };
enum class MediaState : std::uint8_t { None = 0, Unavailable = 1, Complete = 2 };

struct Snapshot final {
	std::uint8_t peerType = 0; // 1=user, 2=chat, 3=channel
	std::uint64_t peer = 0;
	std::uint64_t topic = 0;
	std::int64_t message = 0;
	std::int64_t sentAt = 0;
	std::int64_t capturedAt = 0;
	Reason reason = Reason::Deleted;
	std::string text; // bounded UTF-8 supplied by the native adapter
	std::string content; // versioned adapter metadata; not a claim of raw Telegram TL
	std::string mime;
	MediaState media = MediaState::None;
	std::uint64_t mediaBytes = 0;
	std::uint32_t chunks = 0;
	std::array<unsigned char, 32> digest = {};
};

struct Limits final {
	std::size_t rows = 2000;
	std::uint64_t protectedBytes = 128ULL * 1024 * 1024;
};

struct Added final {
	std::string id;
	bool cleanupPending = false;
};

// One serialized worker; borrowed vault must have its own archive-only registry.
// Chunks and snapshots are individually DPAPI protected. The encrypted catalog
// is published last. No plaintext temporary file is used by this implementation.
class Store final {
public:
	static constexpr auto ChunkBytes = std::size_t(64 * 1024);
	static constexpr auto MaxMediaBytes = std::uint64_t(32 * 1024 * 1024);
	using Reader = std::function<std::size_t(std::span<char>)>;
	explicit Store(Vault::Store &vault, Limits limits = {});
	[[nodiscard]] Added add(Snapshot snapshot, std::uint64_t mediaBytes = 0,
		Reader reader = {});
	[[nodiscard]] std::vector<std::string> page(std::size_t offset = 0,
		std::size_t count = 20) const;
	[[nodiscard]] Snapshot read(const std::string &id) const;
	// Authenticates every chunk and verifies whole-file SHA-256 before returning.
	[[nodiscard]] std::string media(const std::string &id) const;
	[[nodiscard]] std::size_t size() const;
	[[nodiscard]] std::uint64_t protectedBytes() const;
	// Run after restart or a deferred cleanup. Never repairs an invalid catalog.
	void recover();

private:
	[[nodiscard]] Snapshot stored(const std::string &id) const;
	[[nodiscard]] std::uint64_t entryBytes(const std::string &id,
		const Snapshot &snapshot) const;
	void check() const;
	Vault::Store &_vault;
	const Limits _limits;
	std::vector<std::string> _ids; // oldest first
	bool _cleanupPending = false;
};

} // namespace Capy::Archive
