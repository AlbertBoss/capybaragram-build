// SPDX-License-Identifier: MIT
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>

#ifndef CAPY_CPP_ONLY
extern "C" long capy_probe_close_registry_key(void *);
#endif

int main() {
    HKEY key = nullptr;
    if (RegOpenKeyExW(HKEY_CURRENT_USER, L"Software", 0, KEY_QUERY_VALUE, &key) != ERROR_SUCCESS) {
        return 11;
    }
    // Read a deliberately absent value. No account data or registry mutation.
    const auto result = RegQueryValueExW(key,
        L"CapybaraGram__ReadOnlyImportProbe__Absent", nullptr, nullptr, nullptr, nullptr);
#ifdef CAPY_CPP_ONLY
    const auto closed = RegCloseKey(key);
#else
    const auto closed = capy_probe_close_registry_key(key);
#endif
    if (result != ERROR_FILE_NOT_FOUND || closed != ERROR_SUCCESS) {
        return 12;
    }
    std::puts("CAPY_REGISTRY_IMPORT_PROBE=PASS");
    return 0;
}
