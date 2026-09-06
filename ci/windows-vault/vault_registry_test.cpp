// SPDX-License-Identifier: MIT
#include "vault_registry.h"
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <fstream>
#include <functional>
#include <iostream>
#include <stdexcept>

namespace {
int Checks = 0;
void Check(bool value) {
	if (!value) throw std::runtime_error("Registry assertion failed");
	++Checks;
}
void Reject(const std::function<void()> &operation) {
	auto rejected = false;
	try { operation(); } catch (const std::exception &) { rejected = true; }
	Check(rejected);
}
std::string Generation(const std::string &binding) {
	return binding.substr(binding.rfind('\n')+1);
}
std::string Bytes(const std::filesystem::path &path) {
	auto input=std::ifstream(path,std::ios::binary);
	if (!input) throw std::runtime_error("Fixture read failed");
	return {std::istreambuf_iterator<char>(input),std::istreambuf_iterator<char>()};
}
class Lock final {
public:
	explicit Lock(const std::filesystem::path &path,DWORD sharing=0)
	: _handle(CreateFileW(path.c_str(),GENERIC_READ,sharing,nullptr,
		OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr)) {
		if (_handle==INVALID_HANDLE_VALUE) throw std::runtime_error("Fixture lock failed");
	}
	~Lock() { CloseHandle(_handle); }
	Lock(const Lock &)=delete;
	Lock &operator=(const Lock &)=delete;
private:
	HANDLE _handle;
};
}

int main() {
	using Capy::Vault::Store;
	using Capy::Vault::Registry;
	try {
		const auto root=std::filesystem::absolute("synthetic-vault-registry");
		Check(!std::filesystem::exists(root));
		const auto note=Store::Note(1,90);
		const auto zero=Store::Note(1,1);
		const auto indexId=std::string("00000000000000000000000000000000");
		auto registry=Registry(root,10);
		auto original=registry.open(0,100);
		original->write(note,"restart survives");
		{
			auto restart=Registry(root,10);
			Check(restart.open(0,100)->read(note)=="restart survives");
		}
		auto index=Store(root/"index",1,indexId,false);
		const auto before=*index.read(zero);
		auto relogin=registry.open(0,100,true);
		Check(!relogin->read(note));
		Check(*index.read(zero)!=before);
		Reject([&] { (void)original->read(note); });
		relogin->write(note,"new login");
		registry.logout(0,100);
		Reject([&] { (void)relogin->read(note); });
		Check(!index.read(zero));
		registry.logout(0,100); // no binding: idempotent
		Check(!registry.open(0,100)->read(note));
		auto previous=registry.open(0,100);
		previous->write(note,"owner100");
		auto next=registry.open(0,200);
		Check(!next->read(note));
		Reject([&] { (void)previous->read(note); });
		next->write(note,"owner200");
		Reject([&] { registry.logout(0,100); });
		Check(next->read(note)=="owner200");
		for (auto slot=1;slot!=10;++slot) {
			auto account=registry.open(slot,static_cast<std::uint64_t>(1000+slot));
			Check(!account->read(note));
			account->write(note,"slot"+std::to_string(slot));
		}
		{
			auto restart=Registry(root,10);
			for (auto slot=1;slot!=10;++slot) {
				Check(restart.open(slot,static_cast<std::uint64_t>(1000+slot))->read(note)
					=="slot"+std::to_string(slot));
			}
		}
		Reject([&] { (void)registry.open(-1,100); });
		Reject([&] { (void)registry.open(10,100); });
		Reject([&] { (void)registry.open(0,0); });
		const auto record=*index.read(zero);
		const auto generation=Generation(record);
		{
			const auto lock=Lock(root/"index"/indexId/(zero+".bin"),FILE_SHARE_READ);
			Reject([&] { registry.logout(0,200); });
			Check(index.read(Store::Template(generation))->starts_with("R"));
			Reject([&] { (void)registry.open(0,200); });
			Check(registry.open(1,1001)->read(note)=="slot1");
		}
		{
			auto restart=Registry(root,10);
			Check(!restart.open(0,200)->read(note));
			Reject([&] { (void)next->read(note); });
			Check(!index.read(Store::Template(generation)));
		}
		auto locked=registry.open(0,200);
		locked->write(note,"cleanup lock");
		const auto lockedGeneration=Generation(*index.read(zero));
		{
			const auto lock=Lock(root/"data"/lockedGeneration/(note+".bin"));
			Reject([&] { registry.logout(0,200); });
			Check(!index.read(zero));
			Check(index.read(Store::Template(lockedGeneration))->starts_with("R"));
			Reject([&] { (void)locked->read(note); });
			auto newOwner=registry.open(0,300);
			Check(!newOwner->read(note));
			newOwner->write(note,"owner300 kept");
		}
		Check(registry.retryCleanup());
		Check(registry.open(0,300)->read(note)=="owner300 kept");
		Check(!index.read(Store::Template(lockedGeneration)));
		// Creation committed, but journal deletion was interrupted: preserve data.
		const auto committed=*index.read(zero);
		const auto committedJournal=Store::Template(Generation(committed));
		index.write(committedJournal,'C'+committed);
		{
			auto restart=Registry(root,10);
			Check(restart.open(0,300)->read(note)=="owner300 kept");
			Check(!index.read(committedJournal));
		}
		// Creation never committed: recover the orphan without disturbing live data.
		const auto orphanId=Store::NewId();
		auto orphan=Store(root/"data",400,orphanId,true);
		orphan.write(note,"never committed");
		index.write(Store::Template(orphanId),"CCPGB1\n400\n"+orphanId);
		{
			auto restart=Registry(root,10);
			Reject([&] { (void)orphan.read(note); });
			Check(!index.read(Store::Template(orphanId)));
			Check(restart.open(0,300)->read(note)=="owner300 kept");
		}
		// Logout intent persisted, but active binding was not removed yet.
		auto preLogout=registry.open(0,300);
		index.write(committedJournal,'R'+committed);
		{
			auto restart=Registry(root,10);
			Check(!restart.open(0,300)->read(note));
			Reject([&] { (void)preLogout->read(note); });
		}
		// Malformed metadata cannot cause a silent reset or leak across accounts.
		const auto slot8=Store::Note(1,9);
		const auto preserved=*index.read(slot8);
		index.write(slot8,"invalid binding");
		const auto damaged=Bytes(root/"index"/indexId/(slot8+".bin"));
		Reject([&] { (void)registry.open(8,1008); });
		Check(Bytes(root/"index"/indexId/(slot8+".bin"))==damaged);
		index.write(slot8,preserved);
		Check(registry.open(8,1008)->read(note)=="slot8");
		// Missing index over existing data must fail; never bootstrap over it.
		std::filesystem::rename(root/"index",root/"index-held");
		Reject([&] { auto missing=Registry(root,10); });
		Check(!std::filesystem::exists(root/"index"));
		std::filesystem::rename(root/"index-held",root/"index");
		Check(registry.open(9,1009)->read(note)=="slot9");
		// Forgotten-passcode reset persists before cleanup and survives reopening.
		const auto resetKey = Store::Note(2,1);
		const auto resetGeneration = Generation(*index.read(Store::Note(1,10)));
		{
			const auto lock = Lock(root/"data"/resetGeneration/(note+".bin"));
			Reject([&] { registry.forgetAll(); });
			Check(index.read(resetKey) == "CPG-RESET-1");
			Reject([&] { auto resetRestart = Registry(root,10); });
			Reject([&] { (void)registry.open(0,100); });
		}
		{
			auto resetRestart = Registry(root,10);
			Check(!index.read(resetKey));
			for (auto slot = 0; slot != 10; ++slot) {
				Check(!resetRestart.open(slot,static_cast<std::uint64_t>(1000+slot))->read(note));
			}
		}
		// Simulate a stop after new Telegram authorization persisted but before
		// queued vault logout/attach ran: restore sees the new nonce, fresh=false.
		const auto oldAuth = Store::NewId();
		const auto newAuth = Store::NewId();
		auto oldLogin = registry.open(0,800,false,oldAuth);
		oldLogin->write(note,"must not survive a new authorization");
		const auto oldBinding = *index.read(zero);
		{
			auto restart = Registry(root,10);
			auto restoredNewLogin = restart.open(0,800,false,newAuth);
			Check(!restoredNewLogin->read(note));
			Check(*index.read(zero) != oldBinding);
			Reject([&] { (void)oldLogin->read(note); });
			restoredNewLogin->write(note,"same authorization survives");
			Reject([&] { restart.logout(0,800,oldAuth); });
			Check(restoredNewLogin->read(note) == "same authorization survives");
		}
		{
			auto restart = Registry(root,10);
			Check(restart.open(0,800,false,newAuth)->read(note) == "same authorization survives");
			const auto authBinding = *index.read(zero);
			Reject([&] { (void)restart.open(0,800,false,""); });
			Reject([&] { (void)restart.open(0,800,false,std::string(32,'Z')); });
			Check(*index.read(zero) == authBinding);
			// Readable binding, but its atomic replacement is locked: fail closed.
			{
				const auto lock = Lock(root/"index"/indexId/(zero+".bin"),FILE_SHARE_READ);
				Reject([&] { (void)restart.open(0,800,false,oldAuth); });
				Reject([&] { (void)restart.open(0,800,false,newAuth); });
			}
			Check(!restart.open(0,800,false,oldAuth)->read(note));
		}
		// A real legacy CPGB1 binding remains readable with the reserved identity.
		const auto legacyGeneration = Store::NewId();
		auto legacyStore = Store(root/"data",900,legacyGeneration,true);
		legacyStore.write(note,"legacy survives upgrade");
		registry.logout(0,800,oldAuth);
		index.write(zero,"CPGB1\n900\n"+legacyGeneration);
		{
			auto restart = Registry(root,10);
			Check(restart.open(0,900)->read(note) == "legacy survives upgrade");
			Check(!restart.open(0,900,false,newAuth)->read(note));
			Reject([&] { (void)legacyStore.read(note); });
			const auto valid = *index.read(zero);
			index.write(zero,"CPGB2\n900\nshort\n"+legacyGeneration);
			const auto malformed = *index.read(zero);
			Reject([&] { (void)restart.open(0,900,false,newAuth); });
			Check(index.read(zero) == malformed);
			index.write(zero,valid);
			Check(!restart.open(0,900,false,newAuth)->read(note));
		}
		std::cout << "CAPY_WINDOWS_REGISTRY=PASS checks=" << Checks << '\n';
		return 0;
	} catch (const std::exception &) {
		std::cerr << "CAPY_WINDOWS_REGISTRY=FAIL (synthetic account lifecycle)\n";
		return 1;
	}
}
