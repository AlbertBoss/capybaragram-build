// SPDX-License-Identifier: MIT
#include "voice_decoder.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <memory>
#include <stdexcept>
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/channel_layout.h>
#include <libavutil/error.h>
#include <libswresample/swresample.h>
}

namespace Capy::Voice {
namespace {
constexpr auto MaxBytes = 32 * 1024 * 1024;
constexpr auto MaxSamples = 16000 * 180;
struct Input {
    const std::vector<std::uint8_t> &bytes;
    const std::atomic<bool> &cancel;
    std::size_t position = 0;
    std::chrono::steady_clock::time_point deadline =
        std::chrono::steady_clock::now() + std::chrono::seconds(120);
    bool stopped() const {
        return cancel.load() || std::chrono::steady_clock::now() > deadline;
    }
};
int Read(void *opaque, std::uint8_t *target, int size) {
    auto &input = *static_cast<Input*>(opaque);
    if (input.stopped()) return AVERROR_EXIT;
    if (size <= 0) return AVERROR(EINVAL);
    const auto count = std::min<std::size_t>(size, input.bytes.size() - input.position);
    if (!count) return AVERROR_EOF;
    std::memcpy(target, input.bytes.data() + input.position, count);
    input.position += count;
    return static_cast<int>(count);
}
std::int64_t Seek(void *opaque, std::int64_t offset, int mode) {
    auto &input = *static_cast<Input*>(opaque);
    if (input.stopped()) return AVERROR_EXIT;
    if (mode == AVSEEK_SIZE) return static_cast<std::int64_t>(input.bytes.size());
    mode &= ~AVSEEK_FORCE;
    const auto base = mode == SEEK_SET ? 0LL : mode == SEEK_CUR
        ? static_cast<std::int64_t>(input.position) : mode == SEEK_END
        ? static_cast<std::int64_t>(input.bytes.size()) : -1LL;
    if (base < 0 || offset < -base
        || offset > static_cast<std::int64_t>(input.bytes.size()) - base) return AVERROR(EINVAL);
    input.position = static_cast<std::size_t>(base + offset);
    return static_cast<std::int64_t>(input.position);
}
int Interrupt(void *opaque) { return static_cast<Input*>(opaque)->stopped() ? 1 : 0; }
int RefuseOpen(AVFormatContext*, AVIOContext**, const char*, int, AVDictionary**) {
    return AVERROR(EPERM);
}
struct Resources {
    AVIOContext *io = nullptr;
    AVFormatContext *format = nullptr;
    AVCodecContext *codec = nullptr;
    SwrContext *resample = nullptr;
    AVPacket *packet = nullptr;
    AVFrame *frame = nullptr;
    ~Resources() {
        av_frame_free(&frame); av_packet_free(&packet); swr_free(&resample);
        avcodec_free_context(&codec);
        if (format) avformat_close_input(&format);
        if (io) { av_freep(&io->buffer); avio_context_free(&io); }
    }
};
void Require(bool value) { if (!value) throw std::runtime_error("local audio decode failed"); }
struct Samples {
    std::vector<float> value;
    ~Samples() { std::fill(value.begin(), value.end(), 0.F); }
};
} // namespace

std::vector<float> DecodeAudio(const std::vector<std::uint8_t> &source,
        const std::atomic<bool> &cancel) {
    Require(!source.empty() && source.size() <= MaxBytes && !cancel.load());
    Input input{ source, cancel };
    Resources r;
    auto *buffer = static_cast<std::uint8_t*>(av_malloc(32768));
    Require(buffer != nullptr);
    r.io = avio_alloc_context(buffer, 32768, 0, &input, Read, nullptr, Seek);
    if (!r.io) { av_free(buffer); Require(false); }
    r.format = avformat_alloc_context(); Require(r.format != nullptr);
    r.format->pb = r.io;
    r.format->flags |= AVFMT_FLAG_CUSTOM_IO;
    r.format->io_open = RefuseOpen;
    r.format->interrupt_callback = { Interrupt, &input };
    r.format->probesize = 2 * 1024 * 1024;
    r.format->max_analyze_duration = 5 * AV_TIME_BASE;
    Require(avformat_open_input(&r.format, nullptr, nullptr, nullptr) >= 0);
    Require(avformat_find_stream_info(r.format, nullptr) >= 0 && !input.stopped());
    const AVCodec *decoder = nullptr;
    const auto stream = av_find_best_stream(r.format, AVMEDIA_TYPE_AUDIO, -1, -1, &decoder, 0);
    Require(stream >= 0 && decoder != nullptr);
    const auto params = r.format->streams[stream]->codecpar;
    Require(params->sample_rate >= 8000 && params->sample_rate <= 48000
        && params->ch_layout.nb_channels >= 1 && params->ch_layout.nb_channels <= 2);
    r.codec = avcodec_alloc_context3(decoder); Require(r.codec != nullptr);
    Require(avcodec_parameters_to_context(r.codec, params) >= 0);
    r.codec->thread_count = 1;
    Require(avcodec_open2(r.codec, decoder, nullptr) >= 0);
    const AVChannelLayout mono = AV_CHANNEL_LAYOUT_MONO;
    Require(swr_alloc_set_opts2(&r.resample, &mono, AV_SAMPLE_FMT_FLT, 16000,
        &r.codec->ch_layout, r.codec->sample_fmt, r.codec->sample_rate, 0, nullptr) >= 0);
    Require(r.resample && swr_init(r.resample) >= 0);
    r.packet = av_packet_alloc(); r.frame = av_frame_alloc();
    Require(r.packet && r.frame);
    Samples output;
    output.value.reserve(16000 * 30);
    int frames = 0;
    const auto append = [&](const std::uint8_t **planes, int count) {
        const auto available = swr_get_out_samples(r.resample, count);
        Require(available >= 0 && available <= MaxSamples
            && output.value.size() + available <= MaxSamples + 8192);
        Samples temporary; temporary.value.resize(available);
        auto *target = reinterpret_cast<std::uint8_t*>(temporary.value.data());
        const auto converted = swr_convert(r.resample, &target, available, planes, count);
        Require(converted >= 0 && output.value.size() + converted <= MaxSamples);
        for (int i = 0; i < converted; ++i) {
            const auto value = temporary.value[i];
            Require(std::isfinite(value));
            output.value.push_back(std::clamp(value, -1.F, 1.F));
        }
    };
    const auto receive = [&] {
        for (;;) {
            Require(!input.stopped() && ++frames <= 50000);
            const auto result = avcodec_receive_frame(r.codec, r.frame);
            if (result == AVERROR(EAGAIN) || result == AVERROR_EOF) return;
            Require(result >= 0 && r.frame->sample_rate == r.codec->sample_rate
                && r.frame->ch_layout.nb_channels == r.codec->ch_layout.nb_channels
                && r.frame->format == r.codec->sample_fmt && r.frame->nb_samples > 0);
            append(const_cast<const std::uint8_t**>(r.frame->extended_data), r.frame->nb_samples);
            av_frame_unref(r.frame);
        }
    };
    int packets = 0;
    for (;;) {
        Require(!input.stopped() && ++packets <= 50000);
        const auto result = av_read_frame(r.format, r.packet);
        if (result == AVERROR_EOF) break;
        Require(result >= 0);
        if (r.packet->stream_index == stream) {
            Require(avcodec_send_packet(r.codec, r.packet) >= 0);
            receive();
        }
        av_packet_unref(r.packet);
    }
    Require(avcodec_send_packet(r.codec, nullptr) >= 0);
    receive(); append(nullptr, 0);
    Require(!output.value.empty() && !input.stopped());
    return std::move(output.value);
}
} // namespace Capy::Voice
