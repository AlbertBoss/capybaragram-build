// SPDX-License-Identifier: MIT
#include "native_api.h"
#include <array>
#include <cstdio>
#include <cstdlib>

static int checks = 0;
static void check(bool value) {
    if (!value) { std::fputs("Native connection ABI assertion failed\n", stderr); std::exit(1); }
    ++checks;
}

int main() {
    check(capy_connection_start(nullptr) == 0);
    check(capy_connection_status(0, nullptr) == 0);
    std::array<uint64_t, 16> handles{};
    for (auto &handle : handles) {
        CapyConnectionEndpoint endpoint{};
        handle = capy_connection_start(&endpoint);
        check(handle != 0 && endpoint.abi_version == 1 && endpoint.port != 0);
        check(endpoint.reserved == 0 && endpoint.secret[34] == 0);
        for (unsigned char value : endpoint.secret) {
            check(value == 0 || (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f'));
        }
        CapyConnectionStatus status{};
        check(capy_connection_status(handle, &status) == 1 && status.running == 1);
        check(status.abi_version == 1 && status.established == 0);
        for (auto &value : endpoint.secret) { value = 0; }
    }
    CapyConnectionEndpoint rejected{};
    check(capy_connection_start(&rejected) == 0);
    check(rejected.abi_version == 0 && rejected.port == 0);
    const auto revoked = handles[0];
    check(capy_connection_stop(revoked) == 1);
    handles[0] = 0;
    check(capy_connection_stop(revoked) == 0);
    CapyConnectionEndpoint replacement{};
    handles[0] = capy_connection_start(&replacement);
    check(handles[0] != 0 && handles[0] != revoked);
    for (auto &value : replacement.secret) { value = 0; }
    for (const auto handle : handles) { check(capy_connection_stop(handle) == 1); }
    CapyConnectionStatus status{};
    check(capy_connection_status(revoked, &status) == 0 && status.abi_version == 0);
    std::printf("CAPY_NATIVE_CONNECTION_ABI=PASS %d assertions\n", checks);
}
