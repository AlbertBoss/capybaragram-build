// SPDX-License-Identifier: MIT
#include "vault_store.h"

#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <dpapi.h>
#include <bcrypt.h>
#include <algorithm>
#include <array>
#include <stdexcept>
#include <utility>

namespace Capy::Vault {
namespace {

[[noreturn]] void Fail() {
	throw std::runtime_error("CapybaraGram local data operation failed");
}

class Handle final {
public:
	explicit Handle(HANDLE value) : value(value) {
		if (value == INVALID_HANDLE_VALUE) Fail();
	}
	~Handle() { CloseHandle(value); }
	Handle(const Handle &) = delete;
	Handle &operator=(const Handle &) = delete;
	HANDLE value;
};

struct Blob final {
	DATA_BLOB data = {};
	~Blob() {
		if (data.pbData) {
			SecureZeroMemory(data.pbData, data.cbData);
			LocalFree(data.pbData);
		}
	}
	Blob() = default;
	Blob(const Blob &) = delete;
	Blob &operator=(const Blob &) = delete;
};

[[nodiscard]] bool IsId(const std::string &id) {
	return id.size() == 32 && std::all_of(id.begin(), id.end(), [](char ch) {
		return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
	});
}

[[nodiscard]] bool IsRecord(const std::string &name) {
	if (name.starts_with("template-")) return IsId(name.substr(9));
	if (!name.starts_with("note-") || name.size() > 70) return false;
	const auto tail = name.substr(5);
	return std::count(tail.begin(), tail.end(), '-') == 2
		&& std::all_of(tail.begin(), tail.end(), [](char ch) {
			return (ch >= '0' && ch <= '9') || ch == '-';
		});
}

void Directory(const std::filesystem::path &path, bool create, bool exclusive = false) {
	if (create && !CreateDirectoryW(path.c_str(), nullptr)) {
		if (exclusive || GetLastError() != ERROR_ALREADY_EXISTS) Fail();
	}
	const auto attributes = GetFileAttributesW(path.c_str());
	if (attributes == INVALID_FILE_ATTRIBUTES
		|| !(attributes & FILE_ATTRIBUTE_DIRECTORY)
		|| (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) Fail();
}

[[nodiscard]] std::optional<std::string> Read(const std::filesystem::path &path) {
	const auto raw = CreateFileW(path.c_str(), GENERIC_READ,
		FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
		FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
	if (raw == INVALID_HANDLE_VALUE && GetLastError() == ERROR_FILE_NOT_FOUND) return {};
	const auto file = Handle(raw);
	auto info = BY_HANDLE_FILE_INFORMATION();
	auto size = LARGE_INTEGER();
	if (!GetFileInformationByHandle(file.value, &info)
		|| (info.dwFileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY))
		|| !GetFileSizeEx(file.value, &size) || size.QuadPart < 1
		|| size.QuadPart > 200000) Fail();
	auto result = std::string(static_cast<std::size_t>(size.QuadPart), '\0');
	auto read = DWORD();
	if (!ReadFile(file.value, result.data(), static_cast<DWORD>(result.size()), &read, nullptr)
		|| read != result.size()) Fail();
	return result;
}

void AtomicWrite(const std::filesystem::path &path, const std::string &data) {
	const auto temporary = std::filesystem::path(path.wstring() + L".tmp-"
		+ std::filesystem::path(Store::NewId()).wstring());
	struct Cleanup final {
		std::filesystem::path path;
		~Cleanup() { DeleteFileW(path.c_str()); }
	} cleanup{temporary};
	{
		const auto file = Handle(CreateFileW(temporary.c_str(), GENERIC_WRITE, 0, nullptr,
			CREATE_NEW, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_WRITE_THROUGH, nullptr));
		auto written = DWORD();
		if (!WriteFile(file.value, data.data(), static_cast<DWORD>(data.size()), &written, nullptr)
			|| written != data.size() || !FlushFileBuffers(file.value)) Fail();
	}
	if (!MoveFileExW(temporary.c_str(), path.c_str(),
		MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) Fail();
}

[[nodiscard]] std::string Transform(const std::string &input,
		const std::string &entropy, bool encrypt) {
	auto source = DATA_BLOB{static_cast<DWORD>(input.size()),
		reinterpret_cast<BYTE *>(const_cast<char *>(input.data()))};
	auto context = DATA_BLOB{static_cast<DWORD>(entropy.size()),
		reinterpret_cast<BYTE *>(const_cast<char *>(entropy.data()))};
	auto output = Blob();
	const auto ok = encrypt
		? CryptProtectData(&source, nullptr, &context, nullptr, nullptr,
			CRYPTPROTECT_UI_FORBIDDEN, &output.data)
		: CryptUnprotectData(&source, nullptr, &context, nullptr, nullptr,
			CRYPTPROTECT_UI_FORBIDDEN, &output.data);
	if (!ok || output.data.cbData > 200000) Fail();
	return output.data.cbData
		? std::string(reinterpret_cast<const char *>(output.data.pbData), output.data.cbData)
		: std::string();
}

[[nodiscard]] std::filesystem::path GenerationPath(const std::filesystem::path &root,
		const std::string &generation) {
	if (!root.is_absolute() || !IsId(generation)) Fail();
	return root / generation;
}

} // namespace

std::string Store::NewId() {
	auto bytes = std::array<unsigned char, 16>();
	if (BCryptGenRandom(nullptr, bytes.data(), static_cast<ULONG>(bytes.size()),
		BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0) Fail();
	constexpr auto digits = "0123456789abcdef";
	auto result = std::string();
	result.reserve(32);
	for (const auto value : bytes) {
		result += digits[value >> 4];
		result += digits[value & 15];
	}
	return result;
}

std::string Store::Note(int type, std::uint64_t peer, std::uint64_t topic) {
	if (type < 1 || type > 3 || !peer) Fail();
	return "note-" + std::to_string(type) + '-' + std::to_string(peer)
		+ '-' + std::to_string(topic);
}

std::string Store::Template(const std::string &id) {
	if (!IsId(id)) Fail();
	return "template-" + id;
}

Store::Store(const std::filesystem::path &root, std::uint64_t owner,
	const std::string &generation, bool create)
: _directory(GenerationPath(root, generation))
, _identity("CapybaraGram/v1/" + std::to_string(owner) + '/' + generation)
, _thread(std::this_thread::get_id()) {
	if (!owner) Fail();
	Directory(root, create);
	Directory(_directory, create, create);
	checkActive();
	if (create) {
		AtomicWrite(path("identity"), Transform("CPGV1", entropy("identity"), true));
	} else {
		const auto data = Read(path("identity"));
		if (!data || Transform(*data, entropy("identity"), false) != "CPGV1") Fail();
	}
}

void Store::checkThread() const {
	if (_thread != std::this_thread::get_id()) Fail();
}

void Store::checkActive() const {
	checkThread();
	Directory(_directory, false);
	const auto marker = _directory / "retired";
	if (GetFileAttributesW(marker.c_str()) != INVALID_FILE_ATTRIBUTES
		|| GetLastError() != ERROR_FILE_NOT_FOUND) Fail();
}

std::string Store::entropy(const std::string &record) const {
	return _identity + '/' + record;
}

std::filesystem::path Store::path(const std::string &record) const {
	return _directory / (record + ".bin");
}

std::optional<std::string> Store::read(const std::string &record) const {
	checkActive();
	if (!IsRecord(record)) Fail();
	const auto data = Read(path(record));
	if (!data) return {};
	auto plain = Transform(*data, entropy(record), false);
	if (plain.size() > MaxPayload) Fail();
	return plain;
}

void Store::write(const std::string &record, const std::string &text) const {
	checkActive();
	if (!IsRecord(record) || text.size() > MaxPayload) Fail();
	const auto protectedData = Transform(text, entropy(record), true);
	checkActive();
	AtomicWrite(path(record), protectedData);
}

void Store::erase(const std::string &record) const {
	checkActive();
	if (!IsRecord(record)) Fail();
	if (!DeleteFileW(path(record).c_str()) && GetLastError() != ERROR_FILE_NOT_FOUND) Fail();
}

std::vector<std::string> Store::templates() const {
	checkActive();
	auto result = std::vector<std::string>();
	for (const auto &entry : std::filesystem::directory_iterator(_directory)) {
		const auto name = entry.path().filename().string();
		if (name.size() == 45 && name.ends_with(".bin") && IsRecord(name.substr(0,41))
			&& name.starts_with("template-")) {
			result.push_back(name.substr(0,41));
		}
	}
	std::sort(result.begin(), result.end());
	return result;
}

void Store::retire() const {
	checkThread();
	RetireGeneration(_directory.parent_path(), _directory.filename().string());
}

void Store::RetireGeneration(const std::filesystem::path &root,
		const std::string &generation) {
	const auto directory = GenerationPath(root, generation);
	if (GetFileAttributesW(directory.c_str()) == INVALID_FILE_ATTRIBUTES) {
		const auto error = GetLastError();
		if (error == ERROR_FILE_NOT_FOUND || error == ERROR_PATH_NOT_FOUND) return;
		Fail();
	}
	Directory(directory, false);
	AtomicWrite(directory / "retired", "CPG retired generation");
	for (const auto &entry : std::filesystem::directory_iterator(directory)) {
		const auto name = entry.path().filename().string();
		if (name == "retired") continue;
		if (!DeleteFileW(entry.path().c_str()) && GetLastError() != ERROR_FILE_NOT_FOUND) Fail();
	}
}

} // namespace Capy::Vault
