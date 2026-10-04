// SPDX-License-Identifier: MIT
#pragma once
#include <atomic>
#include <cstdint>
#include <vector>

namespace Capy::Voice {
// Local immutable bytes only: custom AVIO refuses nested file/network opens.
std::vector<float> DecodeAudio(const std::vector<std::uint8_t> &source,
    const std::atomic<bool> &cancel);
} // namespace Capy::Voice
