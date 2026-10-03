// SPDX-License-Identifier: MIT
#include "offline_engine.h"
#include "whisper.h"
#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <stdexcept>
namespace Capy::Voice {
Engine::Engine(const std::string &path) {
    static std::once_flag logPolicy;
    std::call_once(logPolicy, [] { whisper_log_set([](ggml_log_level, const char *, void *) {}, nullptr); });
    std::ifstream file(std::filesystem::u8path(path), std::ios::binary);
    if (!file) throw std::runtime_error("Verified speech model unavailable.");
    whisper_model_loader loader{};
    loader.context = &file;
    loader.read = [](void *p, void *out, size_t count) {
        auto &input = *static_cast<std::ifstream *>(p);
        input.read(static_cast<char *>(out), static_cast<std::streamsize>(count));
        return static_cast<size_t>(input.gcount());
    };
    loader.eof = [](void *p) { return static_cast<std::ifstream *>(p)->peek() == std::char_traits<char>::eof(); };
    loader.close = [](void *) {}; // stack-owned stream, including failure paths
    auto parameters = whisper_context_default_params();
    parameters.use_gpu = false;
    _context = whisper_init_with_params(&loader, parameters);
    if (!_context) throw std::runtime_error("Speech model could not be loaded.");
}
Engine::~Engine() { if (_context) whisper_free(_context); }
void Engine::cancel() noexcept { _cancelled.store(true); }
int Engine::progress() const noexcept { return _progress.load(); }
std::string Engine::transcribe(const std::vector<float> &pcm, const std::string &language, int threads) {
    if (_used || pcm.empty() || pcm.size() > MaxSamples || threads < 1 || threads > 4
            || (language != "ru" && language != "en" && language != "auto")) {
        throw std::invalid_argument("Invalid speech job.");
    }
    for (float sample : pcm) if (!std::isfinite(sample) || sample < -1.0f || sample > 1.0f)
        throw std::invalid_argument("Invalid audio sample.");
    _used = true;
    if (_cancelled.load()) throw std::runtime_error("Speech job cancelled.");
    auto parameters = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    parameters.n_threads = threads;
    parameters.language = language.c_str();
    parameters.translate = false;
    parameters.no_context = true;
    parameters.no_timestamps = true;
    parameters.print_special = false;
    parameters.print_progress = false;
    parameters.print_realtime = false;
    parameters.print_timestamps = false;
    parameters.progress_callback = [](whisper_context *, whisper_state *, int progress, void *p) {
        static_cast<Engine *>(p)->_progress.store(std::max(0, std::min(100, progress)));
    };
    parameters.progress_callback_user_data = this;
    parameters.abort_callback = [](void *p) { return static_cast<Engine *>(p)->_cancelled.load(); };
    parameters.abort_callback_user_data = this;
    if (whisper_full(_context, parameters, pcm.data(), static_cast<int>(pcm.size())) != 0 || _cancelled.load())
        throw std::runtime_error("Speech job failed or cancelled.");
    std::string result;
    for (int i = 0, n = whisper_full_n_segments(_context); i != n; ++i) {
        auto text = whisper_full_get_segment_text(_context, i);
        if (!text) throw std::runtime_error("Speech result unavailable.");
        result += text;
        if (result.size() > 65536) throw std::runtime_error("Speech result exceeds limit.");
    }
    _progress.store(100);
    return result;
}
}
