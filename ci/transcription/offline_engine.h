// SPDX-License-Identifier: MIT
#pragma once
#include <atomic>
#include <cstddef>
#include <string>
#include <vector>
struct whisper_context;
namespace Capy::Voice {
// One job/context, owned by its worker. Only cancel/progress may run concurrently.
class Engine final {
public:
    static constexpr int SampleRate = 16000;
    static constexpr std::size_t MaxSamples = SampleRate * 180;
    explicit Engine(const std::string &verifiedModelUtf8Path);
    ~Engine();
    Engine(const Engine &) = delete;
    Engine &operator=(const Engine &) = delete;
    void cancel() noexcept;
    int progress() const noexcept;
    std::string transcribe(const std::vector<float> &mono16k, const std::string &language, int threads);
private:
    whisper_context *_context = nullptr;
    std::atomic<bool> _cancelled = false;
    std::atomic<int> _progress = 0;
    bool _used = false;
};
}
