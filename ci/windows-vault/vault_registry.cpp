// SPDX-License-Identifier: MIT
#include "vault_registry.h"
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <charconv>
#include <stdexcept>

namespace Capy::Vault {
namespace {

constexpr auto IndexGeneration = "00000000000000000000000000000000";

[[noreturn]] void Fail() {
	throw std::runtime_error("CapybaraGram account data operation failed");
}

[[nodiscard]] std::filesystem::path Root(const std::filesystem::path &root) {
	if (!root.is_absolute()) Fail();
	if (!CreateDirectoryW(root.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) Fail();
	const auto attributes = GetFileAttributesW(root.c_str());
	if (attributes == INVALID_FILE_ATTRIBUTES || !(attributes & FILE_ATTRIBUTE_DIRECTORY)
		|| (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) Fail();
	return root;
}

[[nodiscard]] bool NewIndex(const std::filesystem::path &root) {
	if (std::filesystem::exists(root / "index" / IndexGeneration)) return false;
	// Never recreate lost metadata over an existing data collection.
	if (std::filesystem::exists(root / "data")) Fail();
	return true;
}

[[nodiscard]] int Slots(int slots) {
	if (slots < 1 || slots > 256) Fail();
	return slots;
}

} // namespace

Registry::Registry(const std::filesystem::path &root, int slots)
: _root(Root(root))
, _slots(Slots(slots))
, _index(_root / "index", 1, IndexGeneration, NewIndex(_root)) {
	finishReset();
	(void)retryCleanup();
}

std::string Registry::Encode(const Binding &binding) {
	return "CPGB1\n" + std::to_string(binding.owner) + '\n' + binding.generation;
}

Registry::Binding Registry::Decode(const std::string &value) {
	if (!value.starts_with("CPGB1\n") || value.size() > 80) Fail();
	const auto separator = value.find('\n',6);
	if (separator == std::string::npos || separator == 6) Fail();
	auto owner = std::uint64_t();
	const auto first = value.data()+6;
	const auto last = value.data()+separator;
	const auto parsed = std::from_chars(first,last,owner);
	if (parsed.ec != std::errc() || parsed.ptr != last || !owner
		|| std::to_string(owner) != value.substr(6,separator-6)) Fail();
	const auto generation = value.substr(separator+1);
	(void)Store::Template(generation); // strict 32-hex validation
	return {owner,generation};
}

std::string Registry::slotKey(int slot) const {
	if (slot < 0 || slot >= _slots) Fail();
	return Store::Note(1,static_cast<std::uint64_t>(slot)+1);
}

std::optional<Registry::Binding> Registry::binding(int slot) {
	const auto value = _index.read(slotKey(slot));
	return value ? std::optional(Decode(*value)) : std::nullopt;
}

bool Registry::referenced(const std::string &generation) {
	for (auto slot=0; slot!=_slots; ++slot) {
		const auto value = binding(slot);
		if (value && value->generation == generation) return true;
	}
	return false;
}

void Registry::clean(const std::string &record) {
	const auto pending = _index.read(record);
	if (!pending) return;
	if (pending->empty() || ((*pending)[0] != 'C' && (*pending)[0] != 'R')) Fail();
	const auto retired = Decode(pending->substr(1));
	if (record != Store::Template(retired.generation)) Fail();
	if ((*pending)[0] == 'C' && referenced(retired.generation)) {
		// A creation journal may survive its final delete. An active binding
		// is the commit record: never destroy user data because this entry survived.
		_index.erase(record);
		return;
	}
	for (auto slot=0; slot!=_slots; ++slot) {
		const auto value = binding(slot);
		if (value && value->generation == retired.generation) _index.erase(slotKey(slot));
	}
	Store::RetireGeneration(_root / "data",retired.generation);
	_index.erase(record);
}

bool Registry::retryCleanup() {
	auto complete = true;
	for (const auto &record : _index.templates()) {
		try { clean(record); }
		catch (const std::exception &) { complete = false; }
	}
	return complete;
}

void Registry::retire(const Binding &value) {
	const auto pending = Store::Template(value.generation);
	_index.write(pending, 'R' + Encode(value));
	clean(pending);
}

void Registry::logout(int slot, std::uint64_t expectedOwner) {
	if (!expectedOwner) Fail();
	const auto value = binding(slot);
	if (!value) return;
	if (value->owner != expectedOwner) Fail();
	retire(*value);
}

void Registry::forgetAll() {
	_index.write(Store::Note(2,1), "CPG-RESET-1");
	finishReset();
}

void Registry::finishReset() {
	const auto key = Store::Note(2,1);
	const auto reset = _index.read(key);
	if (!reset) return;
	if (*reset != "CPG-RESET-1") Fail();
	auto complete = true;
	for (auto slot = 0; slot != _slots; ++slot) {
		try {
			if (const auto value = binding(slot)) retire(*value);
		} catch (const std::exception &) {
			complete = false;
		}
	}
	if (!retryCleanup() || !complete) Fail();
	_index.erase(key);
}

std::unique_ptr<Store> Registry::open(int slot, std::uint64_t owner, bool freshLogin) {
	if (!owner) Fail();
	(void)slotKey(slot);
	finishReset();
	(void)retryCleanup();
	if (const auto value = binding(slot)) {
		const auto pending = _index.read(Store::Template(value->generation));
		if (pending) {
			if (pending->empty() || ((*pending)[0] != 'C' && (*pending)[0] != 'R')) Fail();
			const auto journal = Decode(pending->substr(1));
			if (journal.owner != value->owner || journal.generation != value->generation) Fail();
		}
		if (pending && pending->starts_with("R")) {
			// Cleanup failed earlier: this generation is never available again.
			retire(*value);
		} else if (value->owner != owner || freshLogin) {
			retire(*value);
		} else {
			return std::make_unique<Store>(_root/"data",owner,value->generation,false);
		}
	}
	const auto next = Binding{owner,Store::NewId()};
	const auto pending = Store::Template(next.generation);
	_index.write(pending,'C'+Encode(next));
	auto store = std::make_unique<Store>(_root/"data",owner,next.generation,true);
	_index.write(slotKey(slot),Encode(next));
	// If this delete fails the committed binding remains authoritative; startup
	// recognizes C journals and preserves active data before removing the journal.
	_index.erase(pending);
	return store;
}

} // namespace Capy::Vault
