// SPDX-License-Identifier: MIT
#pragma once
#include <cstdint>
#include <filesystem>
#include <memory>
#include <span>

namespace Capy::Archive {

// Open the already complete ORIGINAL on admission, before cache deletion.
// It may then be moved to the serialized archive worker. Never pass a thumbnail
// or an encrypted cache file requiring Telegram's own decryptor to this API.
class VerifiedInput final {
public:
	[[nodiscard]] static std::shared_ptr<VerifiedInput> Open(
		const std::filesystem::path &trustedRoot,
		const std::filesystem::path &file, std::uint64_t expectedBytes);
	~VerifiedInput();
	VerifiedInput(const VerifiedInput &) = delete;
	VerifiedInput &operator=(const VerifiedInput &) = delete;
	[[nodiscard]] std::uint64_t size() const;
	// Serialized worker only; no UI thread file streaming.
	[[nodiscard]] std::size_t read(std::span<char> output);

private:
	struct Impl;
	explicit VerifiedInput(std::unique_ptr<Impl> impl);
	std::unique_ptr<Impl> _impl;
};

} // namespace Capy::Archive
