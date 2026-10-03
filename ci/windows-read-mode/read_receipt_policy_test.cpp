// SPDX-License-Identifier: MIT
#include "read_receipt_policy.h"
#include <array>
#include <iostream>
#include <stdexcept>

int main() {
	int checks = 0;
	const auto check = [&](bool value) {
		++checks;
		if (!value) throw std::runtime_error("Read receipt isolation regression");
	};
	std::array<Capy::ReadReceiptPolicy, 10> accounts;
	for (auto &account : accounts) {
		check(!account.suppress(1, 100, true));
		account.setSilent(true);
		check(account.suppress(2, 100, true));
		check(!account.suppress(3, 999, false)); // login/send/download never blocked
	}
	accounts[0].allow(10, 100);
	check(accounts[1].suppress(10, 100, true));
	check(accounts[0].suppress(11, 100, true)); // concurrent automatic request
	check(!accounts[0].suppress(10, 100, true));
	check(accounts[0].suppress(10, 100, true)); // permit cannot replay
	accounts[0].allow(12, 100);
	check(accounts[0].suppress(12, 101, true)); // same id, different method
	check(accounts[0].suppress(12, 100, true)); // invalid use consumed that id
	accounts[0].allow(13, 100);
	accounts[0].setSilent(false);
	accounts[0].setSilent(true);
	check(accounts[0].suppress(13, 100, true));
	accounts[0].allow(14, 100);
	accounts[0].reset(); // logout, reused slot, or replaced authorization
	check(!accounts[0].silent());
	accounts[0].setSilent(true);
	check(accounts[0].suppress(14, 100, true));
	std::cout << "CAPY_READ_POLICY=PASS checks=" << checks << '\n';
}
