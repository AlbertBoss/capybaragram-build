// SPDX-License-Identifier: MIT
#include "archive_store.h"
#include "verified_input.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <algorithm>
#include <atomic>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
using Vault = Capy::Vault::Store;
using Archive = Capy::Archive::Store;
int Checks = 0;

void Check(bool value) {
	if (!value) throw std::runtime_error("Archive synthetic assertion failed");
	++Checks;
}
template <typename Callback> void Reject(Callback callback) {
	auto rejected = false;
	try { callback(); } catch (const std::exception &) { rejected = true; }
	Check(rejected);
}

std::filesystem::path Root() {
	return std::filesystem::absolute("synthetic-archive-" + Vault::NewId());
}

Capy::Archive::Snapshot Message(std::int64_t id = 100) {
	auto s = Capy::Archive::Snapshot();
	s.peerType = 1;
	s.peer = 200;
	s.message = id;
	s.sentAt = 100000;
	s.capturedAt = 100001;
	s.text = "Synthetic private UTF-8 / \xd0\xba\xd0\xb0\xd0\xbf\xd0\xb8";
	s.content = "synthetic-adapter-v1";
	return s;
}

Archive::Reader Reader(const std::string &bytes) {
	return [&bytes, offset = std::size_t()](std::span<char> out) mutable {
		const auto count = std::min({out.size(), bytes.size() - offset, std::size_t(7001)});
		std::copy_n(bytes.data() + offset, count, out.data());
		offset += count;
		return count;
	};
}

std::string Bytes(const std::filesystem::path &path) {
	auto in = std::ifstream(path, std::ios::binary);
	if (!in) throw std::runtime_error("Fixture read failed");
	return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

void Put(const std::filesystem::path &path, const std::string &bytes) {
	auto out = std::ofstream(path, std::ios::binary | std::ios::trunc);
	out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
	out.close();
	if (!out) throw std::runtime_error("Fixture write failed");
}

class Locked final {
public:
	explicit Locked(const std::filesystem::path &path, DWORD sharing = 0)
	: _handle(CreateFileW(path.c_str(), GENERIC_READ, sharing, nullptr,
		OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr)) {
		Check(_handle != INVALID_HANDLE_VALUE);
	}
	~Locked() { CloseHandle(_handle); }
	Locked(const Locked &) = delete;
	Locked &operator=(const Locked &) = delete;
private:
	HANDLE _handle;
};

void RoundTrip() {
	const auto root = Root();
	const auto generation = Vault::NewId();
	auto vault = Vault(root, 100, generation, true);
	auto archive = Archive(vault);
	Check(archive.size() == 0 && archive.page().empty());
	const auto original = std::string(Archive::ChunkBytes * 2 + 17, 'm');
	auto s = Message();
	s.reason = Capy::Archive::Reason::Expired;
	s.mime = "audio/ogg";
	s.media = Capy::Archive::MediaState::Unavailable;
	const auto added = archive.add(s, original.size(), Reader(original));
	Check(!added.cleanupPending && archive.size() == 1);
	const auto restored = archive.read(added.id);
	Check(restored.text == s.text && restored.content == s.content
		&& restored.reason == s.reason && restored.mime == s.mime
		&& restored.media == Capy::Archive::MediaState::Complete
		&& restored.chunks == 3 && restored.mediaBytes == original.size());
	Check(archive.media(added.id) == original);
	Check(archive.page() == std::vector<std::string>{added.id});
	Check(archive.page(100).empty());
	Reject([&] { (void)archive.page(0, 21); });
	Reject([&] { (void)archive.page(0, 0); });
	Reject([&] { (void)archive.read(Vault::NewId()); });
	for (const auto &key : vault.archiveRecords()) {
		const auto protectedData = Bytes(root / generation / (key + ".bin"));
		Check(protectedData.find(s.text) == std::string::npos
			&& protectedData.find(std::string(256, 'm')) == std::string::npos);
	}
	{
		auto reopenedVault = Vault(root, 100, generation, false);
		auto reopened = Archive(reopenedVault);
		Check(reopened.read(added.id).text == s.text && reopened.media(added.id) == original);
	}
	Reject([&] { auto wrongOwner = Vault(root, 101, generation, false); });
	const auto secondGeneration = Vault::NewId();
	auto other = Vault(root, 100, secondGeneration, true);
	const auto key = Vault::Archive(added.id);
	std::filesystem::copy_file(root / generation / (key + ".bin"),
		root / secondGeneration / (key + ".bin"));
	Reject([&] { (void)other.read(key); });
	const auto chunkKey = Vault::ArchiveChunk(added.id, 0);
	const auto chunkPath = root / generation / (chunkKey + ".bin");
	const auto encrypted = Bytes(chunkPath);
	auto tampered = encrypted;
	tampered[tampered.size() / 2] ^= 1;
	Put(chunkPath, tampered);
	Reject([&] { (void)archive.media(added.id); });
	Check(Bytes(chunkPath) == tampered); // failed authentication preserves evidence
	Put(chunkPath, encrypted);
	vault.write(chunkKey, std::string(Archive::ChunkBytes, 'z'));
	Reject([&] { (void)archive.media(added.id); }); // valid DPAPI, wrong whole-file digest
	Put(chunkPath, encrypted);
	Check(archive.media(added.id) == original);
	auto threadRejected = std::atomic<bool>(false);
	auto thread = std::thread([&] {
		try { (void)archive.size(); } catch (const std::exception &) { threadRejected = true; }
	});
	thread.join();
	Check(threadRejected);
	vault.retire();
	Reject([&] { (void)archive.read(added.id); });
	Reject([&] { (void)archive.add(Message()); });
}

void RejectionAndRollback() {
	const auto root = Root();
	const auto generation = Vault::NewId();
	auto vault = Vault(root, 100, generation, true);
	auto archive = Archive(vault);
	const auto existing = archive.add(Message());
	const auto before = vault.archiveRecords();
	const auto truncated = std::string(Archive::ChunkBytes + 1, 't');
	Reject([&] { (void)archive.add(Message(101), truncated.size() + 1, Reader(truncated)); });
	Check(vault.archiveRecords() == before && archive.size() == 1);
	Reject([&] { (void)archive.add(Message(101), truncated.size() - 1, Reader(truncated)); });
	Check(vault.archiveRecords() == before && archive.read(existing.id).text == Message().text);
	Reject([&] { (void)archive.add(Message(101), Archive::MaxMediaBytes + 1, Reader(truncated)); });
	Reject([&] { (void)archive.add(Message(101), 1); });
	auto invalid = Message();
	invalid.text.resize(60001, 'x');
	Reject([&] { (void)archive.add(invalid); });
	Reject([&] { (void)Vault::ArchiveChunk(existing.id, 512); });
	for (const auto key : {"archive-../escape", "archive-00000000000000000000000000000000-01",
		"archive-00000000000000000000000000000000-512", "archive-index/escape"}) {
		Reject([&] { vault.write(key, "invalid"); });
	}
	// Lock the index only after staging succeeds, to fail the actual atomic commit.
	auto lock = std::unique_ptr<Locked>();
	auto reader = Reader(truncated);
	Reject([&] {
		(void)archive.add(Message(101), truncated.size(), [&](std::span<char> out) {
			const auto count = reader(out);
			if (!count) lock = std::make_unique<Locked>(root / generation / "archive-index.bin");
			return count;
		});
	});
	lock.reset();
	Check(vault.archiveRecords() == before && archive.read(existing.id).text == Message().text);
	Check(archive.size() == 1);
	const auto unavailable = archive.add([] {
		auto value = Message(102);
		value.media = Capy::Archive::MediaState::Unavailable;
		return value;
	}());
	Check(archive.read(unavailable.id).media == Capy::Archive::MediaState::Unavailable);
	Reject([&] { (void)archive.media(unavailable.id); });
}

void RecoveryAndQuota() {
	const auto root = Root();
	const auto generation = Vault::NewId();
	auto vault = Vault(root, 100, generation, true);
	auto archive = Archive(vault, {2, 128ULL * 1024 * 1024});
	const auto first = archive.add(Message(1));
	const auto second = archive.add(Message(2));
	const auto orphan = Vault::NewId();
	vault.write(Vault::Archive(orphan), "interrupted staging");
	vault.write(Vault::ArchiveChunk(orphan, 0), "interrupted chunk");
	const auto temporary = root / generation / (Vault::Archive(orphan) + ".bin.tmp-" + Vault::NewId());
	Put(temporary, "synthetic encrypted temporary fixture");
	archive.recover();
	Check(!vault.read(Vault::Archive(orphan)) && !vault.read(Vault::ArchiveChunk(orphan, 0))
		&& !std::filesystem::exists(temporary));
	Check(archive.page() == std::vector<std::string>{second.id, first.id});
	Capy::Archive::Added third;
	{
		const auto lock = Locked(root / generation / (Vault::Archive(first.id) + ".bin"), FILE_SHARE_READ);
		third = archive.add(Message(3));
		Check(third.cleanupPending); // new catalog committed; cleanup can retry
		Reject([&] { (void)archive.page(); });
	}
	archive.recover();
	Check(archive.page() == std::vector<std::string>{third.id, second.id}
		&& !vault.read(Vault::Archive(first.id)));
	{
		const auto quotaRoot = Root();
		auto quotaVault = Vault(quotaRoot, 100, Vault::NewId(), true);
		auto quota = Archive(quotaVault, {2000, 160000});
		auto big = Message(10);
		big.text.assign(40000, 'q');
		const auto a = quota.add(big);
		big.message = 11;
		const auto b = quota.add(big);
		big.message = 12;
		const auto c = quota.add(big);
		Check(quota.size() == 2 && quota.page() == std::vector<std::string>{c.id, b.id});
		Check(quota.protectedBytes() <= 160000 && !quotaVault.read(Vault::Archive(a.id)));
	}
	// Missing or unrecognised index must not erase unindexed records.
	const auto preserved = vault.archiveRecords();
	vault.write("archive-index", "CPGAI9\n");
	Reject([&] { auto unknown = Archive(vault); });
	Check(vault.archiveRecords() == preserved && vault.read("archive-index") == "CPGAI9\n");
	vault.erase("archive-index");
	Reject([&] { auto missing = Archive(vault); });
	Check(vault.read(Vault::Archive(third.id)).has_value());
}

void MissingReferences() {
	const auto root = Root();
	const auto generation = Vault::NewId();
	auto vault = Vault(root, 100, generation, true);
	auto archive = Archive(vault);
	const auto original = std::string(Archive::ChunkBytes + 3, 'm');
	const auto entry = archive.add(Message(), original.size(), Reader(original));
	vault.erase(Vault::ArchiveChunk(entry.id, 1));
	const auto orphan = Vault::Archive(Vault::NewId());
	vault.write(orphan, "must preserve before catalog fully checked");
	Reject([&] { archive.recover(); });
	Check(vault.read(orphan).has_value());
	Reject([&] { (void)archive.media(entry.id); });
}

void HeldOriginalFile() {
	using Capy::Archive::VerifiedInput;
	const auto sourceRoot = Root();
	std::filesystem::create_directory(sourceRoot);
	const auto path = sourceRoot / "synthetic-original.ogg";
	const auto original = std::string(Archive::ChunkBytes + 19, 'f');
	Put(path, original);
	Reject([&] { (void)VerifiedInput::Open(sourceRoot, path, original.size() + 1); });
	Reject([&] { (void)VerifiedInput::Open(sourceRoot, path, 0); });
	Reject([&] { (void)VerifiedInput::Open(sourceRoot, path, Archive::MaxMediaBytes + 1); });
	Reject([&] { (void)VerifiedInput::Open(sourceRoot, sourceRoot, original.size()); });
	const auto sibling = std::filesystem::path(sourceRoot.wstring() + L"-sibling");
	std::filesystem::create_directory(sibling);
	const auto outside = sibling / "outside.ogg";
	Put(outside, original);
	Reject([&] { (void)VerifiedInput::Open(sourceRoot, outside, original.size()); });
	Reject([&] { (void)VerifiedInput::Open(sourceRoot, path.parent_path() / ".." / sourceRoot.filename()
		/ path.filename(), original.size()); });
	const auto hardlink = sourceRoot / "hardlink.ogg";
	Check(CreateHardLinkW(hardlink.c_str(), path.c_str(), nullptr) != FALSE);
	Reject([&] { (void)VerifiedInput::Open(sourceRoot, hardlink, original.size()); });
	Check(DeleteFileW(hardlink.c_str()) != FALSE);
	auto input = VerifiedInput::Open(sourceRoot, path, original.size());
	Check(input->size() == original.size());
	{
		const auto denied = CreateFileW(path.c_str(), GENERIC_WRITE,
			FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
			OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
		Check(denied == INVALID_HANDLE_VALUE);
	}
	Check(DeleteFileW(path.c_str()) != FALSE); // retained handle must still yield original bytes
	auto vault = Vault(Root(), 100, Vault::NewId(), true);
	auto archive = Archive(vault);
	const auto added = archive.add(Message(), input->size(), [input](std::span<char> out) {
		return input->read(out);
	});
	Check(!added.cleanupPending && archive.media(added.id) == original);
	input.reset();
	Check(!std::filesystem::exists(path));
	Reject([&] { (void)VerifiedInput::Open(sourceRoot, path, original.size()); });
}
} // namespace

int main() {
	try {
		RoundTrip();
		RejectionAndRollback();
		RecoveryAndQuota();
		MissingReferences();
		HeldOriginalFile();
		std::cout << "CAPY_WINDOWS_ARCHIVE=PASS checks=" << Checks << '\n';
		return 0;
	} catch (const std::exception &) {
		std::cerr << "CAPY_WINDOWS_ARCHIVE=FAIL (synthetic runtime check)\n";
		return 1;
	}
}
