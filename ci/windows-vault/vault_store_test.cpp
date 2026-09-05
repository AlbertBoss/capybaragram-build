// SPDX-License-Identifier: MIT
#include "vault_store.h"
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <atomic>
#include <fstream>
#include <functional>
#include <iostream>
#include <set>
#include <stdexcept>

namespace {
int Checks = 0;
void Check(bool value) {
	if (!value) throw std::runtime_error("Vault runtime assertion failed");
	++Checks;
}
void Reject(const std::function<void()> &operation) {
	auto rejected = false;
	try { operation(); } catch (const std::exception &) { rejected = true; }
	Check(rejected);
}
std::string Bytes(const std::filesystem::path &path) {
	auto input = std::ifstream(path, std::ios::binary);
	if (!input) throw std::runtime_error("Test fixture read failed");
	return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}
void Put(const std::filesystem::path &path, const std::string &data) {
	auto output = std::ofstream(path, std::ios::binary | std::ios::trunc);
	output.write(data.data(), static_cast<std::streamsize>(data.size()));
	output.close();
	if (!output) throw std::runtime_error("Test fixture write failed");
}
}

int main() {
	using Capy::Vault::Store;
	try {
		const auto root = std::filesystem::absolute("synthetic-vault-runtime");
		Check(!std::filesystem::exists(root));
		const auto a = Store::NewId();
		const auto b = Store::NewId();
		auto store = Store(root, 100, a, true);
		const auto note = Store::Note(1, 99);
		const auto topic = Store::Note(3, 99, 8);
		const auto id = Store::NewId();
		const auto answer = Store::Template(id);
		const auto secret = std::string("Synthetic private text / ") + "\xd0\xba\xd0\xb0\xd0\xbf\xd0\xb8";
		Check(!store.read(note));
		store.write(note, secret);
		Check(store.read(note) == secret);
		Check(Bytes(root/a/(note+".bin")).find(secret) == std::string::npos);
		Check(!store.read(topic));
		store.write(topic, "topic-only");
		Check(store.read(topic) == "topic-only" && store.read(note) == secret);
		store.write(answer, "draft-only template");
		Check(store.templates() == std::vector<std::string>{answer});
		{
			auto reopened = Store(root, 100, a, false);
			Check(reopened.read(note) == secret);
			Check(reopened.read(answer) == "draft-only template");
		}
		Reject([&] { auto wrongOwner = Store(root, 200, a, false); });
		Reject([&] { auto duplicate = Store(root, 100, a, true); });
		Reject([&] { auto missing = Store(root, 100, Store::NewId(), false); });
		Reject([&] { auto invalid = Store(root, 0, Store::NewId(), true); });
		Reject([&] { auto traversal = Store(root, 100, "../escape", true); });
		Reject([&] { store.write("../escape", "bad"); });
		Reject([&] { (void)Store::Note(0, 1); });
		Reject([&] { (void)Store::Note(1, 0); });
		Reject([&] { (void)Store::Template("bad"); });
		const auto original = Bytes(root/a/(note+".bin"));
		Reject([&] { store.write(note, std::string(Store::MaxPayload+1,'x')); });
		Check(Bytes(root/a/(note+".bin")) == original && store.read(note) == secret);
		store.write(note, secret);
		Check(Bytes(root/a/(note+".bin")) != original); // randomized protection
		{
			const auto file = root/a/(note+".bin");
			const auto handle = CreateFileW(file.c_str(), GENERIC_READ, 0, nullptr,
				OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
			Check(handle != INVALID_HANDLE_VALUE);
			struct Close final { HANDLE value; ~Close() { CloseHandle(value); } } close{handle};
			Reject([&] { store.write(note, "must not replace locked file"); });
		}
		Check(store.read(note) == secret);
		auto other = Store(root, 100, b, true);
		Check(!other.read(note));
		std::filesystem::copy_file(root/a/(note+".bin"),root/b/(note+".bin"));
		Reject([&] { (void)other.read(note); });
		const auto swapped = Store::Template(Store::NewId());
		std::filesystem::copy_file(root/a/(note+".bin"),root/a/(swapped+".bin"));
		Reject([&] { (void)store.read(swapped); });
		store.erase(swapped);
		auto corrupt = Bytes(root/a/(note+".bin"));
		corrupt[corrupt.size()/2] ^= 1;
		Put(root/a/(note+".bin"), corrupt);
		Reject([&] { (void)store.read(note); });
		Check(Bytes(root/a/(note+".bin")) == corrupt); // failed read preserves evidence
		Put(root/a/(note+".bin"), original);
		Check(store.read(note) == secret);
		auto wrongThreadRejected = std::atomic<bool>(false);
		auto thread = std::thread([&] {
			try { (void)store.read(note); }
			catch (const std::exception &) { wrongThreadRejected = true; }
		});
		thread.join();
		Check(wrongThreadRejected);
		store.erase(answer);
		store.erase(answer);
		Check(store.templates().empty());
		store.write(note, "");
		Check(store.read(note).has_value() && store.read(note)->empty());
		store.write(note, std::string(Store::MaxPayload, 'x'));
		Check(store.read(note)->size() == Store::MaxPayload);
		store.retire();
		Check(std::filesystem::exists(root/a/"retired"));
		Check(!std::filesystem::exists(root/a/(note+".bin")));
		Reject([&] { (void)store.read(note); });
		Reject([&] { store.write(note, "retired"); });
		Reject([&] { auto retired = Store(root, 100, a, false); });
		store.retire(); // idempotent cleanup
		auto relogin = Store(root, 100, Store::NewId(), true);
		Check(!relogin.read(note));
		auto ids = std::set<std::string>();
		for (auto i=0; i!=200; ++i) Check(ids.emplace(Store::NewId()).second);
		std::cout << "CAPY_WINDOWS_VAULT=PASS checks=" << Checks << '\n';
		return 0;
	} catch (const std::exception &) {
		std::cerr << "CAPY_WINDOWS_VAULT=FAIL (synthetic runtime check)\n";
		return 1;
	}
}
