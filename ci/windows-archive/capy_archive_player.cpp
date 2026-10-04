// SPDX-License-Identifier: MIT
#include "capybara/capy_archive_player.h"
#include "capybara/archive_store.h"
#include "lang/lang_keys.h"
#include "media/streaming/media_streaming_loader_local.h"
#include "media/streaming/media_streaming_player.h"
#include "media/streaming/media_streaming_reader.h"
#include "styles/style_boxes.h"
#include "styles/style_layers.h"
#include <QPainter>
#include <algorithm>

namespace Capy {
namespace {
namespace Streaming = Media::Streaming;
QString Text(const QString &en, const QString &ru) {
	return Lang::Id().startsWith(u"ru"_q) ? ru : en;
}
QString Position(crl::time value) {
	const auto seconds = std::max<crl::time>(0, value) / 1000;
	return QString::number(seconds / 60) + u":"_q
		+ QString::number(seconds % 60).rightJustified(2, QChar('0'));
}
} // namespace

class ArchivePlayer::State final {
public:
	State(not_null<ArchivePlayer*> owner, QByteArray bytes, bool video,
			Fn<void(QString)> status)
	: owner(owner), status(std::move(status)) {
		if (bytes.isEmpty() || bytes.size() > qint64(Archive::Store::MaxMediaBytes)) {
			failed = true;
			this->status(Text(u"Original playback is unavailable."_q,
				u"Оригинал недоступен для воспроизведения."_q));
			return;
		}
		// QBuffer owns its QByteArray copy. No DocumentData, MTProto loader,
		// native download cache or plaintext temporary file participates here.
		reader = std::make_shared<Streaming::Reader>(Streaming::MakeBytesLoader(bytes));
		player = std::make_unique<Streaming::Player>(reader);
		options.mode = video ? Streaming::Mode::Both : Streaming::Mode::Audio;
		options.hwAllowed = false;
		options.waitForMarkAsShown = video;
		player->updates() | rpl::on_next_error([=](Streaming::Update &&update) {
			if (closed) return;
			std::visit([=](const auto &value) {
				using T = std::decay_t<decltype(value)>;
				if constexpr (std::is_same_v<T, Streaming::Information>) {
					videoSize = value.video.size;
					duration = std::max(value.video.state.duration, value.audio.state.duration);
					if (duration < 0 || duration == Media::kDurationUnavailable) duration = 0;
					if (!videoSize.isEmpty()) {
						const auto width = owner->width();
						owner->resize(width, std::max(1, videoSize.scaled(QSize(width, 320), Qt::KeepAspectRatio).height()));
					}
				} else if constexpr (std::is_same_v<T, Streaming::UpdateAudio>
					|| std::is_same_v<T, Streaming::UpdateVideo>) {
					position = duration > 0 ? std::clamp(value.position, crl::time(0), duration) : 0;
				} else if constexpr (std::is_same_v<T, Streaming::Finished>) {
					position = duration;
				}
			}, update.data);
			report();
			owner->update();
		}, [=](Streaming::Error &&) {
			if (closed) return;
			failed = true;
			this->status(Text(u"This saved original cannot be played. It remains in the archive."_q,
				u"Не удалось проиграть оригинал. Он остаётся сохранённым в архиве."_q));
			owner->update();
		}, lifetime);
		player->play(options);
	}
	~State() {
		lifetime.destroy();
		if (player) player->stop();
	}
	void report() {
		if (!player || failed || closed) return;
		status((!player->ready() || player->buffering() ? Text(u"Loading locally"_q, u"Загрузка локально"_q)
			: player->finished() ? Text(u"Finished"_q, u"Завершено"_q)
			: player->paused() ? Text(u"Paused"_q, u"Пауза"_q)
			: Text(u"Playing locally"_q, u"Воспроизведение локально"_q))
			+ u" · "_q + Position(position) + (duration ? u" / "_q + Position(duration) : QString()));
	}
	not_null<ArchivePlayer*> owner;
	Fn<void(QString)> status;
	std::shared_ptr<Streaming::Reader> reader;
	std::unique_ptr<Streaming::Player> player;
	Streaming::PlaybackOptions options;
	QSize videoSize;
	crl::time position = 0;
	crl::time duration = 0;
	bool failed = false;
	bool closed = false;
	rpl::lifetime lifetime;
};

ArchivePlayer::ArchivePlayer(not_null<Ui::RpWidget*> parent, QByteArray bytes,
		bool video, Fn<void(QString)> status)
: RpWidget(parent) {
	resize(st::boxWideWidth - st::boxPadding.left() - st::boxPadding.right(), video ? 240 : 1);
	_state = std::make_unique<State>(this, std::move(bytes), video, std::move(status));
}
ArchivePlayer::~ArchivePlayer() = default;

void ArchivePlayer::toggle() {
	const auto &s = *_state;
	if (!s.player || s.failed || s.closed) return;
	if (!s.player->active() || s.player->finished()) {
		_state->options.position = 0;
		_state->position = 0;
		s.player->play(s.options);
	} else if (s.player->paused()) {
		s.player->resume();
	} else {
		s.player->pause();
	}
	_state->report();
}
void ArchivePlayer::seek(crl::time delta) {
	auto &s = *_state;
	if (!s.player || s.failed || s.closed || !s.player->ready() || s.duration <= 1) return;
	s.options.position = std::clamp(s.position + delta, crl::time(0), s.duration - 1);
	s.position = s.options.position;
	s.player->play(s.options);
	s.report();
}
void ArchivePlayer::stop() {
	auto &s = *_state;
	s.closed = true;
	s.lifetime.destroy();
	if (s.player) s.player->stop();
	s.player.reset();
	s.reader.reset();
	s.videoSize = {};
	update();
}
void ArchivePlayer::paintEvent(QPaintEvent *) {
	auto painter = QPainter(this);
	painter.fillRect(rect(), palette().window());
	const auto &s = *_state;
	if (!s.player || s.closed || s.failed || !s.player->ready() || s.videoSize.isEmpty()) return;
	const auto size = s.videoSize.scaled(this->size(), Qt::KeepAspectRatio);
	auto request = Streaming::FrameRequest();
	request.resize = QSize(qRound(size.width() * devicePixelRatioF()), qRound(size.height() * devicePixelRatioF()));
	request.outer = request.resize;
	const auto image = s.player->frame(request);
	if (!image.isNull()) {
		painter.drawImage(QRect(QPoint((width() - size.width()) / 2, 0), size), image);
		s.player->markFrameShown();
	}
}
} // namespace Capy
