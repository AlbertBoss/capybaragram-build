// SPDX-License-Identifier: MIT
// Native archive UI. Client compilation and live Telegram acceptance are separate checks.
#include "capybara/capy_archive_ui.h"
#include "capybara/archive_worker.h"
#include "core/application.h"
#include "data/data_forum_topic.h"
#include "data/data_peer.h"
#include "lang/lang_keys.h"
#include "main/main_account.h"
#include "main/main_session.h"
#include "main/main_session_settings.h"
#include "ui/layers/generic_box.h"
#include "ui/layers/show.h"
#include "ui/rp_widget.h"
#include "ui/widgets/buttons.h"
#include "ui/widgets/labels.h"
#include "window/window_session_controller.h"
#include "styles/style_boxes.h"
#include "styles/style_layers.h"
#include "styles/style_widgets.h"
#include <QBuffer>
#include <QDateTime>
#include <QImageReader>
#include <QPainter>
#include <QPointer>
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

namespace Capy {
namespace {
QString Text(const QString &en, const QString &ru) {
	return Lang::Id().startsWith(u"ru"_q) ? ru : en;
}
QString Failure() {
	return Text(u"Could not load this archive. Try again; existing records are preserved."_q,
		u"Не удалось загрузить архив. Попробуйте снова; существующие записи сохранены."_q);
}

struct Context final {
	base::weak_ptr<Main::Session> session;
	std::shared_ptr<Ui::Show> show;
	Archive::Worker::Handle handle;
	Archive::Conversation conversation;
	QString recipient;
};

bool Available(const Context &context) {
	return context.session && Core::App().capyArchiveWorker().usable(context.handle);
}

bool *Protect(not_null<Ui::GenericBox*> box, const Context &context) {
	const auto closed = box->lifetime().make_state<bool>(false);
	box->boxClosing() | rpl::on_next([=] { *closed = true; }, box->lifetime());
	Core::App().passcodeLockChanges() | rpl::on_next([=](bool locked) {
		if (locked) box->closeBox();
	}, box->lifetime());
	context.session.get()->account().sessionChanges() | rpl::on_next([=](Main::Session*) {
		box->closeBox();
	}, box->lifetime());
	Lang::Updated() | rpl::on_next([=] { box->closeBox(); }, box->lifetime());
	return closed;
}

QString Reason(Archive::Reason reason) {
	switch (reason) {
	case Archive::Reason::Deleted: return Text(u"Deleted"_q, u"Удалено"_q);
	case Archive::Reason::Edited: return Text(u"Before edit"_q, u"До изменения"_q);
	case Archive::Reason::Expired: return Text(u"Disappearing media / message"_q, u"Исчезающее медиа / сообщение"_q);
	}
	return QString();
}

class Picture final : public Ui::RpWidget {
public:
	Picture(not_null<Ui::RpWidget*> parent, QImage image)
	: RpWidget(parent), _image(std::move(image)) {
		const auto width = st::boxWideWidth - st::boxPadding.left() - st::boxPadding.right();
		const auto size = _image.size().scaled(QSize(width, 320), Qt::KeepAspectRatio);
		resize(width, size.height());
	}
private:
	void paintEvent(QPaintEvent *) override {
		auto painter = QPainter(this);
		const auto size = _image.size().scaled(this->size(), Qt::KeepAspectRatio);
		painter.drawImage(QRect(QPoint((width() - size.width()) / 2, 0), size), _image);
	}
	QImage _image;
};

void Browse(Context context, std::size_t offset = 0);

void Preview(Context context, std::string id, Archive::Snapshot snapshot) {
	if (!Available(context)) return;
	context.show->showBox(Box([=](not_null<Ui::GenericBox*> box) {
		if (!Available(context)) { box->closeBox(); return; }
		const auto closed = Protect(box, context);
		const auto weak = QPointer<Ui::GenericBox>(box.get());
		box->setWidth(st::boxWideWidth);
		box->setMaxHeight(st::boxWideWidth);
		box->setTitle(rpl::single(Reason(snapshot.reason)));
		box->addRow(object_ptr<Ui::FlatLabel>(box, context.recipient, st::aboutLabel), st::boxPadding);
		const auto text = QByteArray::fromStdString(snapshot.text);
		const auto decoded = QString::fromUtf8(text);
		if (decoded.toUtf8() != text) {
			box->addRow(object_ptr<Ui::FlatLabel>(box, Failure(), st::aboutLabel), st::boxPadding);
		} else if (!decoded.isEmpty()) {
			box->addRow(object_ptr<Ui::FlatLabel>(box, decoded, st::aboutLabel), st::boxPadding);
		}
		const auto status = box->addRow(object_ptr<Ui::FlatLabel>(box,
			snapshot.media == Archive::MediaState::Complete
				? Text(u"Original saved locally: "_q, u"Оригинал сохранён локально: "_q)
					+ QString::fromStdString(snapshot.mime)
				: snapshot.media == Archive::MediaState::Unavailable
				? Text(u"This entry contains no saved media copy."_q,
					u"Копия оригинала в этой записи не сохранена."_q)
				: Text(u"Text saved locally for this account."_q, u"Текст сохранён локально для этого аккаунта."_q),
			st::aboutLabel), st::boxPadding);
		const auto previewFormat = snapshot.mime == "image/jpeg" ? QByteArray("jpeg")
			: snapshot.mime == "image/png" ? QByteArray("png")
			: snapshot.mime == "image/webp" ? QByteArray("webp") : QByteArray();
		if (snapshot.media == Archive::MediaState::Complete && !previewFormat.isEmpty()) {
			const auto pending = box->lifetime().make_state<bool>(false);
			const auto button = box->addRow(object_ptr<Ui::RoundButton>(box,
				rpl::single(Text(u"View saved image"_q, u"Посмотреть сохранённое изображение"_q)),
				st::defaultActiveButton), st::boxPadding);
			button->setClickedCallback([=] {
				if (*pending || !Available(context)) return;
				*pending = true;
				button->setDisabled(true);
				const auto accepted = Core::App().capyArchiveWorker().media(context.handle, id,
					[=](Archive::Worker::Result result) {
						if (!weak || *closed) return;
						*pending = false;
						if (!result.ok) { status->setText(Failure()); button->setDisabled(false); return; }
						auto bytes = QByteArray::fromStdString(result.media);
						if (!result.media.empty()) SecureZeroMemory(result.media.data(), result.media.size());
						auto buffer = QBuffer(&bytes);
						buffer.open(QIODevice::ReadOnly);
						auto reader = QImageReader(&buffer, previewFormat);
						reader.setAutoDetectImageFormat(false);
						const auto size = reader.size();
						if (!size.isValid() || size.width() > 8192 || size.height() > 8192
							|| qint64(size.width()) * size.height() > 16 * 1024 * 1024) {
							bytes.fill('\0');
							status->setText(Text(u"Image preview is unavailable. The original is still saved."_q,
								u"Предпросмотр недоступен. Оригинал остаётся сохранённым."_q));
							return;
						}
						reader.setScaledSize(size.scaled(QSize(1024, 1024), Qt::KeepAspectRatio));
						auto image = reader.read();
						bytes.fill('\0');
						if (image.isNull()) { status->setText(Failure()); return; }
						box->addRow(object_ptr<Picture>(box, std::move(image)), st::boxPadding);
						button->hide();
					});
				if (!accepted) { *pending = false; button->setDisabled(false); status->setText(Failure()); }
			});
		}
		box->addButton(tr::lng_close(), [=] { box->closeBox(); });
	}));
}

void Clear(Context context) {
	if (!Available(context)) return;
	context.show->showBox(Box([=](not_null<Ui::GenericBox*> box) {
		if (!Available(context)) { box->closeBox(); return; }
		const auto closed = Protect(box, context);
		const auto weak = QPointer<Ui::GenericBox>(box.get());
		box->setTitle(rpl::single(Text(u"Clear this account's local archive?"_q,
			u"Очистить локальный архив аккаунта?"_q)));
		const auto status = box->addRow(object_ptr<Ui::FlatLabel>(box,
			Text(u"All saved message versions and original media for this account on this computer will be removed."_q,
				u"Все сохранённые версии сообщений и оригиналы медиа этого аккаунта на этом компьютере будут удалены."_q),
			st::aboutLabel), st::boxPadding);
		const auto pending = box->lifetime().make_state<bool>(false);
		box->addButton(rpl::single(Text(u"Clear archive"_q, u"Очистить архив"_q)), [=] {
			if (*pending || !Available(context)) return;
			*pending = true;
			Core::App().capyArchiveWorker().clear(context.handle, [=](Archive::Worker::Result result) {
				if (!weak || *closed) return;
				*pending = false;
				if (!result.ok) { status->setText(Failure()); return; }
				box->closeBox();
				Browse(context);
			});
		});
		box->addButton(tr::lng_cancel(), [=] { box->closeBox(); });
	}));
}

void Browse(Context context, std::size_t offset) {
	if (!Available(context)) return;
	context.show->showBox(Box([=](not_null<Ui::GenericBox*> box) {
		if (!Available(context)) { box->closeBox(); return; }
		const auto closed = Protect(box, context);
		const auto weak = QPointer<Ui::GenericBox>(box.get());
		box->setWidth(st::boxWideWidth);
		box->setMaxHeight(st::boxWideWidth);
		box->setTitle(rpl::single(Text(u"CapybaraGram · Chat archive"_q,
			u"CapybaraGram · Архив чата"_q)));
		box->addRow(object_ptr<Ui::FlatLabel>(box, context.recipient, st::aboutLabel), st::boxPadding);
		const auto status = box->addRow(object_ptr<Ui::FlatLabel>(box,
			Text(u"Loading…"_q, u"Загрузка…"_q), st::aboutLabel), st::boxPadding);
		const auto session = context.session.get();
		const auto enabled = session->settings().capyArchiveEnabled();
		box->addButton(rpl::single(enabled
			? Text(u"Disable saving"_q, u"Выключить сохранение"_q)
			: Text(u"Enable saving"_q, u"Включить сохранение"_q)), [=] {
			if (!Available(context)) return;
			session->settings().setCapyArchiveEnabled(!enabled);
			Core::App().capyArchiveWorker().setEnabled(context.handle, !enabled);
			session->saveSettings();
			box->closeBox();
			Browse(context, offset);
		});
		box->addButton(tr::lng_close(), [=] { box->closeBox(); });
		box->addLeftButton(rpl::single(Text(u"Clear account archive"_q,
			u"Очистить архив аккаунта"_q)), [=] {
			box->closeBox();
			Clear(context);
		});
		const auto accepted = Core::App().capyArchiveWorker().pageFor(context.handle,
			context.conversation, offset, [=](Archive::Worker::Result result) {
				if (!weak || *closed) return;
				if (!result.ok || result.ids.size() != result.snapshots.size()) {
					status->setText(Failure()); return;
				}
				status->setText(result.ids.empty()
					? Text(u"No saved messages here. Saving applies to this account after you enable it."_q,
						u"Здесь пока нет сохранённых сообщений. Сохранение действует для аккаунта после включения."_q)
					: Text(u"Only this chat. Saved locally on this computer."_q,
						u"Только этот чат. Сохранено локально на этом компьютере."_q));
				for (auto i = std::size_t(); i != result.ids.size(); ++i) {
					const auto snapshot = result.snapshots[i];
					const auto id = result.ids[i];
					const auto text = QString::fromStdString(snapshot.text).simplified();
					const auto button = box->addRow(object_ptr<Ui::RoundButton>(box,
						rpl::single(Reason(snapshot.reason) + u" · "_q
							+ (text.isEmpty() ? QString::fromStdString(snapshot.mime) : text.left(80))),
						st::defaultActiveButton), st::boxPadding);
					button->setTextTransform(Ui::RoundButtonTextTransform::NoTransform);
					button->setClickedCallback([=] {
						if (!Available(context)) return;
						box->closeBox();
						Preview(context, id, snapshot);
					});
				}
				const auto addPage = [=](std::size_t next, QString text) {
					const auto button = box->addRow(object_ptr<Ui::RoundButton>(box,
						rpl::single(std::move(text)), st::defaultActiveButton), st::boxPadding);
					button->setClickedCallback([=] {
						box->closeBox();
						Browse(context, next);
					});
				};
				if (offset) addPage(offset - 20, Text(u"Previous page"_q, u"Предыдущая страница"_q));
				if (result.ids.size() == 20) addPage(offset + 20, Text(u"Next page"_q, u"Следующая страница"_q));
			});
		if (!accepted) status->setText(Failure());
	}));
}
} // namespace

void AddArchiveAction(not_null<Window::SessionController*> controller,
		Dialogs::EntryState request, const Window::PeerMenuCallback &addAction) {
	const auto peer = request.key.peer();
	if (!peer || request.key.sublist()) return;
	const auto session = &controller->session();
	const auto handle = session->account().capyArchiveHandle();
	if (!Core::App().capyArchiveWorker().usable(handle)) return;
	const auto topic = request.key.topic();
	if (topic && topic->rootId().bare <= 0) return;
	const auto type = peer->isUser() ? 1 : peer->isChat() ? 2 : 3;
	const auto id = peer->isUser() ? peerToUser(peer->id).bare
		: peer->isChat() ? peerToChat(peer->id).bare : peerToChannel(peer->id).bare;
	const auto context = Context{
		.session = base::make_weak(session), .show = controller->uiShow(), .handle = handle,
		.conversation = {static_cast<std::uint8_t>(type), id,
			topic ? std::optional<std::uint64_t>(topic->rootId().bare) : std::nullopt},
		.recipient = peer->name() + (topic ? u" / "_q + topic->title() : QString())};
	addAction(Text(u"CapybaraGram · Chat archive"_q, u"CapybaraGram · Архив чата"_q), [=] {
		Browse(context);
	}, nullptr);
}
} // namespace Capy
