// SPDX-License-Identifier: MIT
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Only 127.0.0.1 is supported. Keep secret in memory; never log or persist it.
typedef struct CapyConnectionEndpoint {
    uint32_t abi_version;
    uint16_t port;
    uint16_t reserved;
    uint8_t secret[35]; // 34 hex bytes followed by NUL.
} CapyConnectionEndpoint;

typedef struct CapyConnectionStatus {
    uint32_t abi_version;
    uint32_t running;
    uint32_t active;
    uint32_t established;
    uint32_t failed_tunnels;
    uint32_t data_centre;
    uint32_t route;
} CapyConnectionStatus;

// Start/stop on a worker thread. Start returns zero on failure; no proxy is
// configured in Telegram automatically. Caller owns and wipes the endpoint.
uint64_t capy_connection_start(CapyConnectionEndpoint *output);
int32_t capy_connection_status(uint64_t handle, CapyConnectionStatus *output);
int32_t capy_connection_stop(uint64_t handle); // 1 stopped, 0 unknown, -1 error.

#ifdef __cplusplus
}
static_assert(sizeof(CapyConnectionEndpoint) == 44);
static_assert(sizeof(CapyConnectionStatus) == 28);
#endif
