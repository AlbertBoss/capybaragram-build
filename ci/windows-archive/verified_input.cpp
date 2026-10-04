// SPDX-License-Identifier: MIT
#include "verified_input.h"
#include "archive_store.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <algorithm>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>

namespace Capy::Archive {
namespace {
[[noreturn]] void Fail() {
	throw std::runtime_error("CapybaraGram original media admission failed");
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

std::wstring FinalPath(HANDLE file) {
	constexpr auto flags = FILE_NAME_NORMALIZED | VOLUME_NAME_DOS;
	const auto count = GetFinalPathNameByHandleW(file, nullptr, 0, flags);
	if (!count || count > 32768) Fail();
	auto result = std::wstring(count, L'\0');
	const auto written = GetFinalPathNameByHandleW(file, result.data(), count, flags);
	if (!written || written >= count) Fail();
	result.resize(written);
	return result;
}

bool Same(std::wstring_view a, std::wstring_view b) {
	if (a.size() != b.size() || a.size() > 32768) return false;
	return CompareStringOrdinal(a.data(), static_cast<int>(a.size()),
		b.data(), static_cast<int>(b.size()), TRUE) == CSTR_EQUAL;
}

void PlainPath(const std::filesystem::path &path) {
	if (!path.is_absolute() || path.lexically_normal() != path) Fail();
	const auto value = path.wstring();
	if (value.size() > 32768 || value.find(L'\0') != std::wstring::npos) Fail();
	// No device path, ADS, wildcard, UNC or DOS ambiguous trailing component.
	if (value.size() < 3 || value[1] != L':' || value.find(L':', 2) != std::wstring::npos
		|| value.starts_with(L"\\\\") || value.find_first_of(L"*?\"") != std::wstring::npos) Fail();
	for (const auto &part : path.relative_path()) {
		const auto name = part.wstring();
		if (name.empty() || name.back() == L'.' || name.back() == L' ') Fail();
	}
}

void NoReparseAncestors(std::filesystem::path path) {
	while (!path.empty()) {
		const auto attributes = GetFileAttributesW(path.c_str());
		if (attributes == INVALID_FILE_ATTRIBUTES
			|| (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) Fail();
		const auto parent = path.parent_path();
		if (parent == path) break;
		path = parent;
	}
}
} // namespace

struct VerifiedInput::Impl final {
	explicit Impl(HANDLE file) : file(file) {}
	Handle file;
	std::uint64_t bytes = 0;
	std::uint64_t consumed = 0;
};

VerifiedInput::VerifiedInput(std::unique_ptr<Impl> impl) : _impl(std::move(impl)) {}
VerifiedInput::~VerifiedInput() = default;

std::shared_ptr<VerifiedInput> VerifiedInput::Open(const std::filesystem::path &trustedRoot,
		const std::filesystem::path &file, std::uint64_t expectedBytes) {
	if (!expectedBytes || expectedBytes > Store::MaxMediaBytes) Fail();
	PlainPath(trustedRoot);
	PlainPath(file);
	NoReparseAncestors(trustedRoot);
	NoReparseAncestors(file);
	const auto root = Handle(CreateFileW(trustedRoot.c_str(), 0,
		FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
		FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
	auto rootInfo = BY_HANDLE_FILE_INFORMATION();
	if (!GetFileInformationByHandle(root.value, &rootInfo)
		|| !(rootInfo.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
		|| (rootInfo.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) Fail();
	// Deny new writes, but allow Telegram to unlink its cache while this handle lives.
	auto impl = std::make_unique<Impl>(CreateFileW(file.c_str(), GENERIC_READ,
		FILE_SHARE_READ | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
		FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN, nullptr));
	auto info = BY_HANDLE_FILE_INFORMATION();
	auto size = LARGE_INTEGER();
	if (GetFileType(impl->file.value) != FILE_TYPE_DISK
		|| !GetFileInformationByHandle(impl->file.value, &info)
		|| (info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT))
		|| info.nNumberOfLinks != 1 || !GetFileSizeEx(impl->file.value, &size)
		|| size.QuadPart <= 0 || static_cast<std::uint64_t>(size.QuadPart) != expectedBytes) Fail();
	auto rootName = FinalPath(root.value);
	if (rootName.back() != L'\\') rootName += L'\\';
	const auto fileName = FinalPath(impl->file.value);
	if (fileName.size() <= rootName.size()
		|| !Same(std::wstring_view(fileName).substr(0, rootName.size()), rootName)) Fail();
	NoReparseAncestors(trustedRoot);
	NoReparseAncestors(file); // detect admission-time changes before exposing a reader
	impl->bytes = expectedBytes;
	return std::shared_ptr<VerifiedInput>(new VerifiedInput(std::move(impl)));
}

std::uint64_t VerifiedInput::size() const { return _impl->bytes; }

std::size_t VerifiedInput::read(std::span<char> output) {
	if (output.empty() || _impl->consumed == _impl->bytes) return 0;
	const auto count = static_cast<DWORD>(std::min<std::uint64_t>({
		static_cast<std::uint64_t>(output.size()), _impl->bytes - _impl->consumed,
		static_cast<std::uint64_t>(std::numeric_limits<DWORD>::max())}));
	auto received = DWORD();
	if (!ReadFile(_impl->file.value, output.data(), count, &received, nullptr)
		|| !received || received > count) Fail();
	_impl->consumed += received;
	return received;
}

} // namespace Capy::Archive
