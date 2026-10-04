// SPDX-License-Identifier: MIT
#include "archive_store.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <bcrypt.h>
#include <algorithm>
#include <limits>
#include <set>
#include <stdexcept>
#include <string_view>

namespace Capy::Archive {
namespace {
constexpr auto Index = "archive-index";
constexpr auto MaxRows = std::size_t(2000);
constexpr auto IndexReserve = std::uint64_t(70000);

[[noreturn]] void Fail() {
	throw std::runtime_error("CapybaraGram archive operation failed");
}

struct Wipe final {
	std::string &value;
	~Wipe() { if (!value.empty()) SecureZeroMemory(value.data(), value.size()); }
};

class Hash final {
public:
	Hash() {
		if (BCryptOpenAlgorithmProvider(&_algorithm, BCRYPT_SHA256_ALGORITHM,
			nullptr, 0) < 0) Fail();
		if (BCryptCreateHash(_algorithm, &_hash, nullptr, 0, nullptr, 0, 0) < 0) {
			BCryptCloseAlgorithmProvider(_algorithm, 0);
			_algorithm = nullptr;
			Fail();
		}
	}
	~Hash() {
		if (_hash) BCryptDestroyHash(_hash);
		if (_algorithm) BCryptCloseAlgorithmProvider(_algorithm, 0);
	}
	Hash(const Hash &) = delete;
	Hash &operator=(const Hash &) = delete;
	void add(std::span<const char> bytes) {
		if (bytes.size() > std::numeric_limits<ULONG>::max()
			|| BCryptHashData(_hash,
				reinterpret_cast<PUCHAR>(const_cast<char *>(bytes.data())),
				static_cast<ULONG>(bytes.size()), 0) < 0) Fail();
	}
	std::array<unsigned char, 32> finish() {
		auto result = std::array<unsigned char, 32>();
		if (BCryptFinishHash(_hash, result.data(),
			static_cast<ULONG>(result.size()), 0) < 0) Fail();
		return result;
	}
private:
	BCRYPT_ALG_HANDLE _algorithm = nullptr;
	BCRYPT_HASH_HANDLE _hash = nullptr;
};

bool Id(std::string_view value) {
	return value.size() == 32 && std::all_of(value.begin(), value.end(), [](char ch) {
		return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
	});
}

bool Zero(const std::array<unsigned char, 32> &digest) {
	return std::all_of(digest.begin(), digest.end(), [](auto byte) { return byte == 0; });
}

void Validate(const Snapshot &s) {
	const auto reason = static_cast<unsigned>(s.reason);
	const auto media = static_cast<unsigned>(s.media);
	if (s.peerType < 1 || s.peerType > 3 || !s.peer || !s.message
		|| s.sentAt < 0 || s.capturedAt < 0 || reason < 1 || reason > 3
		|| media > 2 || s.text.size() > 60000 || s.content.size() > 60000
		|| s.mime.size() > 128 || s.text.size() + s.content.size() > 120000) Fail();
	if (s.media == MediaState::Complete) {
		if (!s.mediaBytes || s.mediaBytes > Store::MaxMediaBytes
			|| s.chunks != (s.mediaBytes + Store::ChunkBytes - 1) / Store::ChunkBytes
			|| Zero(s.digest)) Fail();
	} else if (s.mediaBytes || s.chunks || !Zero(s.digest)) {
		Fail();
	}
}

void Number(std::string &out, std::uint64_t value, unsigned bytes) {
	for (auto i = 0U; i != bytes; ++i) {
		out.push_back(static_cast<char>(value & 255));
		value >>= 8;
	}
}

void Text(std::string &out, const std::string &text) {
	Number(out, text.size(), 4);
	out += text;
}

class Input final {
public:
	explicit Input(std::string_view value) : _value(value) {}
	std::uint64_t number(unsigned bytes) {
		if (bytes > 8 || _value.size() < bytes) Fail();
		auto result = std::uint64_t();
		for (auto i = 0U; i != bytes; ++i) {
			result |= std::uint64_t(static_cast<unsigned char>(_value[i])) << (8 * i);
		}
		_value.remove_prefix(bytes);
		return result;
	}
	std::string text(std::size_t max) {
		const auto size = number(4);
		if (size > max || size > _value.size()) Fail();
		auto result = std::string(_value.substr(0, static_cast<std::size_t>(size)));
		_value.remove_prefix(static_cast<std::size_t>(size));
		return result;
	}
	void digest(std::array<unsigned char, 32> &out) {
		for (auto &byte : out) byte = static_cast<unsigned char>(number(1));
	}
	void end() const { if (!_value.empty()) Fail(); }
private:
	std::string_view _value;
};

std::string Encode(const Snapshot &s) {
	Validate(s);
	auto result = std::string("CPGAE1");
	Number(result, s.peerType, 1);
	Number(result, s.peer, 8);
	Number(result, s.topic, 8);
	Number(result, static_cast<std::uint64_t>(s.message), 8);
	Number(result, static_cast<std::uint64_t>(s.sentAt), 8);
	Number(result, static_cast<std::uint64_t>(s.capturedAt), 8);
	Number(result, static_cast<unsigned>(s.reason), 1);
	Number(result, static_cast<unsigned>(s.media), 1);
	Number(result, s.mediaBytes, 8);
	Number(result, s.chunks, 4);
	for (const auto byte : s.digest) result.push_back(static_cast<char>(byte));
	Text(result, s.text);
	Text(result, s.content);
	Text(result, s.mime);
	if (result.size() > Vault::Store::MaxPayload) Fail();
	return result;
}

Snapshot Decode(std::string_view raw) {
	if (!raw.starts_with("CPGAE1")) Fail();
	auto input = Input(raw.substr(6));
	auto result = Snapshot();
	result.peerType = static_cast<std::uint8_t>(input.number(1));
	result.peer = input.number(8);
	result.topic = input.number(8);
	result.message = static_cast<std::int64_t>(input.number(8));
	result.sentAt = static_cast<std::int64_t>(input.number(8));
	result.capturedAt = static_cast<std::int64_t>(input.number(8));
	result.reason = static_cast<Reason>(input.number(1));
	result.media = static_cast<MediaState>(input.number(1));
	result.mediaBytes = input.number(8);
	result.chunks = static_cast<std::uint32_t>(input.number(4));
	input.digest(result.digest);
	result.text = input.text(60000);
	result.content = input.text(60000);
	result.mime = input.text(128);
	input.end();
	Validate(result);
	return result;
}

std::string Catalog(const std::vector<std::string> &ids) {
	if (ids.size() > MaxRows) Fail();
	auto result = std::string("CPGAI1\n");
	for (const auto &id : ids) {
		if (!Id(id)) Fail();
		result += id + '\n';
	}
	return result;
}

std::vector<std::string> Parse(std::string_view raw) {
	if (!raw.starts_with("CPGAI1\n")) Fail();
	raw.remove_prefix(7);
	if (raw.size() % 33 || raw.size() / 33 > MaxRows) Fail();
	auto result = std::vector<std::string>();
	auto seen = std::set<std::string>();
	while (!raw.empty()) {
		auto id = std::string(raw.substr(0, 32));
		if (!Id(id) || raw[32] != '\n' || !seen.insert(id).second) Fail();
		result.push_back(std::move(id));
		raw.remove_prefix(33);
	}
	return result;
}
} // namespace

Store::Store(Vault::Store &vault, Limits limits)
: _vault(vault), _limits(limits) {
	if (!_limits.rows || _limits.rows > MaxRows
		|| _limits.protectedBytes <= IndexReserve
		|| _limits.protectedBytes > 128ULL * 1024 * 1024) Fail();
	recover();
}

void Store::check() const {
	// Includes the vault's retirement and serialized-thread checks.
	(void)_vault.protectedBytes(Index);
	if (_cleanupPending) Fail();
}

Snapshot Store::stored(const std::string &id) const {
	auto raw = _vault.read(Vault::Store::Archive(id));
	if (!raw) Fail();
	const auto wipe = Wipe{*raw};
	return Decode(*raw);
}

std::uint64_t Store::entryBytes(const std::string &id, const Snapshot &s) const {
	auto result = _vault.protectedBytes(Vault::Store::Archive(id));
	for (auto part = 0U; part != s.chunks; ++part) {
		result += _vault.protectedBytes(Vault::Store::ArchiveChunk(id, part));
	}
	return result;
}

void Store::recover() {
	const auto records = _vault.archiveRecords();
	auto catalog = _vault.read(Index);
	if (!catalog) {
		if (!records.empty()) Fail(); // do not discard unindexed evidence
		_vault.write(Index, Catalog({})); // before any staged entry may be written
		catalog = _vault.read(Index);
	}
	if (!catalog) Fail();
	auto ids = Parse(*catalog);
	auto wanted = std::set<std::string>{Index};
	// Verify all catalog references before deleting any orphan.
	for (const auto &id : ids) {
		const auto s = stored(id);
		wanted.insert(Vault::Store::Archive(id));
		for (auto part = 0U; part != s.chunks; ++part) {
			const auto key = Vault::Store::ArchiveChunk(id, part);
			(void)_vault.protectedBytes(key);
			wanted.insert(key);
		}
	}
	_cleanupPending = true;
	for (const auto &key : records) {
		if (!wanted.contains(key)) _vault.erase(key);
	}
	_vault.cleanupArchiveTemporary();
	_ids = std::move(ids);
	_cleanupPending = false;
	if (_ids.size() > _limits.rows || protectedBytes() > _limits.protectedBytes) Fail();
}

Added Store::add(Snapshot snapshot, std::uint64_t mediaBytes, Reader reader) {
	check();
	if (mediaBytes > MaxMediaBytes || (mediaBytes != 0) != bool(reader)
		|| snapshot.media == MediaState::Complete || snapshot.mediaBytes
		|| snapshot.chunks || !Zero(snapshot.digest)) Fail();
	Validate(snapshot);
	const auto id = Vault::Store::NewId();
	auto staged = std::vector<std::string>();
	auto committed = false;
	try {
		if (reader) {
			auto buffer = std::string(ChunkBytes, '\0');
			const auto wipe = Wipe{buffer};
			auto remaining = mediaBytes;
			auto hash = Hash();
			while (remaining) {
				const auto count = static_cast<std::size_t>(std::min<std::uint64_t>(remaining, ChunkBytes));
				auto filled = std::size_t();
				while (filled != count) {
					const auto got = reader(std::span<char>(buffer.data() + filled, count - filled));
					if (!got || got > count - filled) Fail();
					filled += got;
				}
				hash.add(std::span<const char>(buffer.data(), count));
				const auto key = Vault::Store::ArchiveChunk(id, snapshot.chunks++);
				staged.push_back(key); // include a possible interrupted atomic write
				auto chunk = buffer.substr(0, count);
				const auto chunkWipe = Wipe{chunk};
				_vault.write(key, chunk);
				remaining -= count;
			}
			auto extra = std::array<char, 1>();
			if (reader(extra)) Fail(); // never silently truncate a larger source
			snapshot.media = MediaState::Complete;
			snapshot.mediaBytes = mediaBytes;
			snapshot.digest = hash.finish();
		}
		auto payload = Encode(snapshot);
		const auto wipe = Wipe{payload};
		const auto key = Vault::Store::Archive(id);
		staged.push_back(key);
		_vault.write(key, payload);
		auto chosen = _ids;
		chosen.push_back(id);
		auto bytes = IndexReserve + entryBytes(id, snapshot);
		for (const auto &previous : _ids) bytes += entryBytes(previous, stored(previous));
		auto prune = std::size_t();
		while ((bytes > _limits.protectedBytes || chosen.size() - prune > _limits.rows)
			&& prune < _ids.size()) {
			bytes -= entryBytes(chosen[prune], stored(chosen[prune]));
			++prune;
		}
		if (bytes > _limits.protectedBytes) Fail();
		chosen.erase(chosen.begin(), chosen.begin() + static_cast<std::ptrdiff_t>(prune));
		_vault.write(Index, Catalog(chosen)); // atomic commit, old catalog unchanged on failure
		committed = true;
		_ids = std::move(chosen);
		try { recover(); }
		catch (const std::exception &) { _cleanupPending = true; }
		return {id, _cleanupPending};
	} catch (...) {
		if (!committed) {
			for (const auto &key : staged) {
				try { _vault.erase(key); }
				catch (const std::exception &) { _cleanupPending = true; }
			}
		}
		throw;
	}
}

std::vector<std::string> Store::page(std::size_t offset, std::size_t count) const {
	check();
	if (!count || count > 20) Fail();
	auto result = std::vector<std::string>();
	if (offset >= _ids.size()) return result;
	const auto end = std::min(_ids.size(), offset + count);
	for (auto i = offset; i != end; ++i) result.push_back(_ids[_ids.size() - 1 - i]);
	return result;
}

std::vector<std::string> Store::pageFor(Conversation conversation,
		std::size_t offset, std::size_t count) const {
	check();
	if (conversation.peerType < 1 || conversation.peerType > 3 || !conversation.peer
		|| !count || count > 20) Fail();
	auto result = std::vector<std::string>();
	auto skipped = std::size_t();
	for (auto i = _ids.rbegin(); i != _ids.rend(); ++i) {
		const auto snapshot = stored(*i);
		if (snapshot.peerType != conversation.peerType || snapshot.peer != conversation.peer
			|| (conversation.topic && snapshot.topic != *conversation.topic)) continue;
		if (skipped < offset) { ++skipped; continue; }
		result.push_back(*i);
		if (result.size() == count) break;
	}
	return result;
}

Snapshot Store::read(const std::string &id) const {
	check();
	if (std::find(_ids.begin(), _ids.end(), id) == _ids.end()) Fail();
	return stored(id);
}

std::string Store::media(const std::string &id) const {
	const auto s = read(id);
	if (s.media != MediaState::Complete) Fail();
	auto result = std::string();
	result.reserve(static_cast<std::size_t>(s.mediaBytes));
	try {
		auto hash = Hash();
		for (auto part = 0U; part != s.chunks; ++part) {
			auto chunk = _vault.read(Vault::Store::ArchiveChunk(id, part));
			if (!chunk) Fail();
			const auto wipe = Wipe{*chunk};
			const auto expected = static_cast<std::size_t>(std::min<std::uint64_t>(
				ChunkBytes, s.mediaBytes - result.size()));
			if (chunk->size() != expected) Fail();
			hash.add(*chunk);
			result += *chunk;
		}
		if (result.size() != s.mediaBytes || hash.finish() != s.digest) Fail();
		return result;
	} catch (...) {
		if (!result.empty()) SecureZeroMemory(result.data(), result.size());
		throw;
	}
}

std::size_t Store::size() const {
	check();
	return _ids.size();
}

std::uint64_t Store::protectedBytes() const {
	check();
	auto result = _vault.protectedBytes(Index);
	for (const auto &id : _ids) result += entryBytes(id, stored(id));
	return result;
}

} // namespace Capy::Archive
