// SPDX-License-Identifier: MIT
// Test scaffold only. pinned_policy.inc preserves the upstream GPL notice and
// embeds the exact RestrictToCustomIO function from the pinned Desktop source.
#include <QByteArray>
#include <QFile>
extern "C" {
#include <libavformat/avformat.h>
#include <libavcodec/avcodec.h>
#include <libavutil/opt.h>
}
#include "pinned_policy.inc"
#include <algorithm>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>

namespace {
int Checks = 0;
int NestedOpened = 0;
using Open = int(*)(AVFormatContext*, AVIOContext**, const char*, int, AVDictionary**);
Open OriginalOpen = nullptr;
void Check(bool value) {
	if (!value) throw std::runtime_error("Preview policy assertion failed");
	++Checks;
}
int ObserveOpen(AVFormatContext *format, AVIOContext **io, const char *url,
		int flags, AVDictionary **options) {
	const auto result = OriginalOpen(format, io, url, flags, options);
	if (result >= 0) ++NestedOpened;
	return result;
}
struct Bytes final {
	QByteArray data;
	qint64 position = 0;
	static int Read(void *opaque, uint8_t *out, int size) {
		auto &input = *static_cast<Bytes*>(opaque);
		if (size < 0 || input.position < 0 || input.position > input.data.size()) return AVERROR(EINVAL);
		const auto count = std::min<qint64>(size, input.data.size() - input.position);
		if (!count) return AVERROR_EOF;
		std::memcpy(out, input.data.constData() + input.position, static_cast<size_t>(count));
		input.position += count;
		return static_cast<int>(count);
	}
	static int64_t Seek(void *opaque, int64_t offset, int whence) {
		auto &input = *static_cast<Bytes*>(opaque);
		whence &= ~AVSEEK_FORCE;
		if (whence == AVSEEK_SIZE) return input.data.size();
		const auto base = whence == SEEK_SET ? qint64(0)
			: whence == SEEK_CUR ? input.position : whence == SEEK_END ? input.data.size() : qint64(-1);
		if (base < 0 || (offset > 0 && base > std::numeric_limits<qint64>::max() - offset)
			|| (offset < 0 && base < std::numeric_limits<qint64>::min() - offset)) return AVERROR(EINVAL);
		const auto next = base + offset;
		if (next < 0 || next > input.data.size()) return AVERROR(EINVAL);
		return input.position = next;
	}
};
struct Input final {
	Bytes bytes;
	AVIOContext *io = nullptr;
	AVFormatContext *format = nullptr;
	Input(QByteArray data, bool protect) : bytes{std::move(data)} {
		const auto buffer = static_cast<uint8_t*>(av_malloc(32768));
		Check(buffer != nullptr);
		io = avio_alloc_context(buffer, 32768, 0, &bytes, Bytes::Read, nullptr, Bytes::Seek);
		Check(io != nullptr);
		format = avformat_alloc_context();
		Check(format != nullptr);
		format->pb = io;
		format->flags |= AVFMT_FLAG_CUSTOM_IO;
		OriginalOpen = format->io_open;
		format->io_open = ObserveOpen;
		NestedOpened = 0;
		if (protect) {
			FFmpeg::RestrictToCustomIO(format);
			uint8_t *value = nullptr;
			Check(av_opt_get(format, "protocol_whitelist", 0, &value) == 0);
			Check(value && !*value);
			av_free(value);
		} else {
			// The control must exercise supported protocols, not pass because the
			// test FFmpeg was built without file/HTTP capabilities.
			Check(av_opt_set(format, "protocol_whitelist", "file,http,tcp", 0) == 0);
		}
	}
	bool open(const AVInputFormat *demuxer = nullptr) {
		AVDictionary *options = nullptr;
		av_dict_set(&options, "rw_timeout", "3000000", 0);
		// An HLS master needs a non-empty base URL even when its bytes come
		// exclusively from custom IO; this is a format hint, not a file load.
		const auto hint = demuxer ? "memory.m3u8" : nullptr;
		const auto result = avformat_open_input(&format, hint, demuxer, &options);
		av_dict_free(&options);
		if (result < 0) std::cerr << "OPEN_FAILED code=" << result << '\n';
		return result >= 0;
	}
	~Input() {
		if (format) avformat_close_input(&format);
		if (io) { av_freep(&io->buffer); avio_context_free(&io); }
	}
};
QByteArray Load(const char *path) {
	auto file = QFile(QString::fromUtf8(path));
	Check(file.open(QIODevice::ReadOnly));
	Check(file.size() > 0 && file.size() <= 1024 * 1024);
	return file.readAll();
}
bool Frame(AVFormatContext *format, AVMediaType type) {
	const auto index = av_find_best_stream(format, type, -1, -1, nullptr, 0);
	if (index < 0) return false;
	const auto codec = avcodec_find_decoder(format->streams[index]->codecpar->codec_id);
	if (!codec) return false;
	auto context = avcodec_alloc_context3(codec);
	Check(context != nullptr);
	auto packet = av_packet_alloc();
	auto frame = av_frame_alloc();
	Check(packet && frame);
	auto found = false;
	if (avcodec_parameters_to_context(context, format->streams[index]->codecpar) >= 0
		&& avcodec_open2(context, codec, nullptr) >= 0) {
		for (auto n = 0; n != 100 && av_read_frame(format, packet) >= 0; ++n) {
			if (packet->stream_index == index && avcodec_send_packet(context, packet) >= 0
				&& avcodec_receive_frame(context, frame) >= 0) found = true;
			av_packet_unref(packet);
			if (found) break;
		}
	}
	av_frame_free(&frame);
	av_packet_free(&packet);
	avcodec_free_context(&context);
	return found;
}
void Valid(const QByteArray &bytes, AVMediaType type) {
	auto input = Input(bytes, true);
	Check(input.open());
	Check(avformat_find_stream_info(input.format, nullptr) >= 0);
	Check(Frame(input.format, type));
	Check(NestedOpened == 0);
}
} // namespace
int main(int argc, char **argv) {
	try {
		Check(argc == 5);
		const auto video = Load(argv[1]);
		const auto voice = Load(argv[2]);
		Valid(video, AVMEDIA_TYPE_VIDEO);
		Valid(video, AVMEDIA_TYPE_AUDIO);
		Valid(voice, AVMEDIA_TYPE_AUDIO);
		for (const auto path : {argv[3], argv[4]}) {
			const auto playlist = Load(path);
			{
				auto blocked = Input(playlist, true);
				const auto opened = blocked.open(av_find_input_format("hls"));
				if (opened) avformat_find_stream_info(blocked.format, nullptr);
				Check(NestedOpened == 0);
			}
			{
				auto control = Input(playlist, false);
				const auto opened = control.open(av_find_input_format("hls"));
				if (opened) avformat_find_stream_info(control.format, nullptr);
				Check(NestedOpened > 0);
			}
		}
		std::cout << "CAPY_ARCHIVE_PLAYER_POLICY=PASS checks=" << Checks
			<< " avformat=" << avformat_version() << '\n';
		return 0;
	} catch (const std::exception &) {
		std::cerr << "CAPY_ARCHIVE_PLAYER_POLICY=FAIL checks=" << Checks << '\n';
		return 1;
	}
}
