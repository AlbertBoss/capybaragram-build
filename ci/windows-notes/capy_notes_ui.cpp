// SPDX-License-Identifier: MIT
#include "capybara/capy_notes_ui.h"

#include "capybara/vault_worker.h"
#include "chat_helpers/compose/compose_show.h"
#include "core/application.h"
#include "data/data_forum_topic.h"
#include "data/data_peer.h"
#include "lang/lang_keys.h"
#include "main/main_account.h"
#include "main/main_session.h"
#include "ui/layers/generic_box.h"
#include "ui/layers/show.h"
#include "ui/widgets/buttons.h"
#include "ui/widgets/fields/input_field.h"
#include "ui/widgets/labels.h"
#include "window/window_session_controller.h"
#include "styles/style_boxes.h"
#include "styles/style_layers.h"
#include "styles/style_menu_icons.h"
#include "styles/style_widgets.h"

#include <QPointer>
#include <algorithm>
#include <stdexcept>

namespace Capy {
namespace {

QString Text(const QString &english, const QString &russian) {
	return Lang::Id().startsWith(u"ru"_q) ? russian : english;
}

QString Failure() {
	return Text(u"Could not complete this operation. Your existing data was preserved."_q,
		u"Не удалось выполнить действие. Существующие данные сохранены."_q);
}

void ShowNote(not_null<Main::Session*> session, std::shared_ptr<Ui::Show> show,
		Vault::Worker::Handle handle, std::string record, QString recipient,
		bool isTemplate = false, Fn<void()> saved = nullptr) {
	const auto worker = &Core::App().capyVaultWorker();
	if (!worker->usable(handle)) return;
	const auto weakSession = base::make_weak(session);
	show->showBox(Box([=](not_null<Ui::GenericBox*> box) {
		if (!weakSession || !worker->usable(handle)) {
			box->closeBox();
			return;
		}
		box->setWidth(st::boxWideWidth);
		box->setMaxHeight(st::boxWideWidth);
		box->setTitle(rpl::single(isTemplate
			? Text(u"Response template"_q, u"Шаблон ответа"_q)
			: Text(u"Chat note"_q, u"Заметка к чату"_q)));
		box->addRow(object_ptr<Ui::FlatLabel>(box, recipient, st::aboutLabel), st::boxPadding);
		const auto field = box->addRow(object_ptr<Ui::InputField>(
			box, st::defaultInputField, Ui::InputField::Mode::MultiLine,
			rpl::single(Text(u"Only for you on this computer"_q, u"Только для вас на этом компьютере"_q))),
			st::boxPadding);
		const auto limit = isTemplate ? 4096 : 16000;
		field->setMaxLength(limit);
		field->setMinHeight(st::boxWideWidth / 3);
		field->setDisabled(true);
		const auto status = box->addRow(object_ptr<Ui::FlatLabel>(box,
			Text(u"Loading…"_q, u"Загрузка…"_q), st::aboutLabel), st::boxPadding);
		box->addRow(object_ptr<Ui::FlatLabel>(box,
			Text(u"Stored only on this computer for this account. Saving does not send a message. Save before closing; unsaved text is discarded on lock or logout."_q,
				u"Хранится только на этом компьютере для этого аккаунта. Сохранение не отправляет сообщение. Сохраните текст перед закрытием: при блокировке или выходе несохранённый текст удаляется."_q),
			st::aboutLabel), st::boxPadding);
		struct State {
			bool loaded = false;
			bool pending = false;
			bool closed = false;
			QPointer<Ui::RoundButton> save;
			QPointer<Ui::RoundButton> retry;
		};
		const auto state = box->lifetime().make_state<State>();
		const auto weakBox = QPointer<Ui::GenericBox>(box.get());
		const auto updateControls = [=] {
			field->setDisabled(!state->loaded || state->pending || state->closed);
			if (state->save) state->save->setDisabled(!state->loaded || state->pending || state->closed);
			if (state->retry) {
				state->retry->setVisible(!state->loaded && !state->closed);
				state->retry->setDisabled(state->pending);
			}
			box->updateButtonsGeometry();
		};
		box->boxClosing(
		) | rpl::on_next([=] {
			state->closed = true;
			field->setTextWithTags({});
		}, box->lifetime());
		const auto close = [=] {
			state->closed = true;
			field->setTextWithTags({});
			box->closeBox();
		};
		Core::App().passcodeLockChanges(
		) | rpl::on_next([=](bool locked) {
			if (locked) close();
		}, box->lifetime());
		session->account().sessionChanges(
		) | rpl::on_next([=](Main::Session *) { close(); }, box->lifetime());
		Lang::Updated(
		) | rpl::on_next(close, box->lifetime());
		const auto reload = [=] {
			if (state->loaded || state->pending || state->closed || !worker->usable(handle)) return;
			state->pending = true;
			updateControls();
			status->setText(Text(u"Loading…"_q, u"Загрузка…"_q));
			worker->read(handle, record, [=](Vault::Worker::Result result) {
				if (!weakBox || state->closed) return;
				state->pending = false;
				const auto bytes = result.text ? QByteArray::fromStdString(*result.text) : QByteArray();
				const auto text = QString::fromUtf8(bytes);
				if (!result.ok || text.toUtf8() != bytes || text.size() > limit) {
					status->setText(Failure());
					updateControls();
					return;
				}
				state->loaded = true;
				field->setTextWithTags({ text, {} });
				updateControls();
				if (weakBox->isBoxShown()) field->setFocus();
				status->setText(isTemplate
					? Text(u"Template · 4,096 characters maximum"_q, u"Шаблон · до 4096 символов"_q)
					: Text(u"Local note · 16,000 characters maximum"_q, u"Локальная заметка · до 16 000 символов"_q));
			});
		};
		state->save = box->addButton(tr::lng_settings_save(), [=] {
			if (!state->loaded || state->pending || state->closed || !worker->usable(handle)) return;
			const auto text = field->getLastText().toUtf8().toStdString();
			if (isTemplate && field->getLastText().trimmed().isEmpty()) {
				status->setText(Text(u"Enter the template text first."_q, u"Сначала введите текст шаблона."_q));
				return;
			}
			state->pending = true;
			updateControls();
			status->setText(Text(u"Saving…"_q, u"Сохранение…"_q));
			const auto done = [=](Vault::Worker::Result result) {
				if (!weakBox || state->closed) return;
				state->pending = false;
				if (result.ok) {
					close();
					if (saved) saved();
				} else {
					updateControls();
					status->setText(Failure());
				}
			};
			if (text.empty()) worker->erase(handle, record, done);
			else worker->write(handle, record, text, done);
		});
		box->addButton(tr::lng_cancel(), close);
		state->retry = box->addLeftButton(rpl::single(Text(u"Retry loading"_q, u"Загрузить снова"_q)), reload);
		reload();
	}));
}

struct TemplateContext {
	base::weak_ptr<Main::Session> session;
	std::shared_ptr<Ui::Show> show;
	Vault::Worker::Handle handle;
	QString recipient;
	Fn<bool(QString)> insertDraft;
};

bool Available(const TemplateContext &context) {
	return context.session && Core::App().capyVaultWorker().usable(context.handle);
}

// All template views share the same account handle. Closing the native layer
// destroys its lifetime; queued storage replies also check that handle and box.
bool *ProtectBox(not_null<Ui::GenericBox*> box, const TemplateContext &context) {
	const auto closed = box->lifetime().make_state<bool>(false);
	box->boxClosing(
	) | rpl::on_next([=] { *closed = true; }, box->lifetime());
	Core::App().passcodeLockChanges(
	) | rpl::on_next([=](bool locked) { if (locked) box->closeBox(); }, box->lifetime());
	context.session.get()->account().sessionChanges(
	) | rpl::on_next([=](Main::Session *) { box->closeBox(); }, box->lifetime());
	Lang::Updated(
	) | rpl::on_next([=] { box->closeBox(); }, box->lifetime());
	return closed;
}

void ShowTemplates(TemplateContext context, int page = 0);

void EditTemplate(TemplateContext context, std::string record) {
	if (!Available(context)) return;
	ShowNote(context.session.get(), context.show, context.handle, std::move(record),
		Text(u"Reusable text for this account"_q, u"Готовый текст для этого аккаунта"_q), true,
		[=] { if (Available(context)) ShowTemplates(context); });
}

void PreviewTemplate(TemplateContext context, std::string record, QString text) {
	if (!Available(context)) return;
	context.show->showBox(Box([=](not_null<Ui::GenericBox*> box) {
		if (!Available(context)) { box->closeBox(); return; }
		const auto closed = ProtectBox(box, context);
		box->setWidth(st::boxWideWidth);
		box->setMaxHeight(st::boxWideWidth);
		box->setTitle(rpl::single(Text(u"Template preview"_q, u"Предпросмотр шаблона"_q)));
		box->addRow(object_ptr<Ui::FlatLabel>(box,
			Text(u"Draft for: "_q, u"Черновик для: "_q) + context.recipient, st::aboutLabel), st::boxPadding);
		box->addRow(object_ptr<Ui::FlatLabel>(box, text, st::aboutLabel), st::boxPadding);
		const auto status = box->addRow(object_ptr<Ui::FlatLabel>(box,
			Text(u"Inserts into the draft. You send it yourself."_q, u"Текст будет вставлен в черновик. Вы отправляете его самостоятельно."_q),
			st::aboutLabel), st::boxPadding);
		const auto weak = QPointer<Ui::GenericBox>(box.get());
		const auto busy = box->lifetime().make_state<bool>(false);
		box->addButton(rpl::single(Text(u"Insert into draft"_q, u"В черновик"_q)), [=] {
			if (*busy || !Available(context)) return;
			if (context.insertDraft && context.insertDraft(text)) {
				box->closeBox();
			} else {
				status->setText(Text(u"The chat or input mode changed. Reopen templates in the intended chat."_q,
					u"Чат или режим ввода изменился. Откройте шаблоны заново в нужном чате."_q));
			}
		});
		box->addButton(tr::lng_cancel(), [=] { box->closeBox(); });
		const auto edit = box->addRow(object_ptr<Ui::RoundButton>(box,
			rpl::single(Text(u"Edit template"_q, u"Редактировать шаблон"_q)), st::defaultActiveButton), st::boxPadding);
		edit->setClickedCallback([=] {
			if (*busy || !Available(context)) return;
			box->closeBox();
			EditTemplate(context, record);
		});
		const auto remove = box->addRow(object_ptr<Ui::RoundButton>(box,
			rpl::single(Text(u"Delete template"_q, u"Удалить шаблон"_q)), st::defaultActiveButton), st::boxPadding);
		remove->setClickedCallback([=] {
			if (*busy || !Available(context)) return;
			*busy = true;
			status->setText(Text(u"Deleting…"_q, u"Удаление…"_q));
			Core::App().capyVaultWorker().erase(context.handle, record, [=](Vault::Worker::Result result) {
				if (!weak || *closed) return;
				*busy = false;
				if (!result.ok) { status->setText(Failure()); return; }
				box->closeBox();
				if (Available(context)) ShowTemplates(context);
			});
		});
	}));
}

void ShowTemplates(TemplateContext context, int page) {
	if (!Available(context)) return;
	context.show->showBox(Box([=](not_null<Ui::GenericBox*> box) {
		if (!Available(context)) { box->closeBox(); return; }
		const auto closed = ProtectBox(box, context);
		box->setWidth(st::boxWideWidth);
		box->setMaxHeight(st::boxWideWidth);
		box->setTitle(rpl::single(Text(u"Response templates"_q, u"Шаблоны ответов"_q)));
		const auto status = box->addRow(object_ptr<Ui::FlatLabel>(box,
			Text(u"Loading…"_q, u"Загрузка…"_q), st::aboutLabel), st::boxPadding);
		const auto weak = QPointer<Ui::GenericBox>(box.get());
		box->addButton(rpl::single(Text(u"New template"_q, u"Создать"_q)), [=] {
			if (!Available(context)) return;
			auto record = std::string();
			try { record = Vault::Store::Template(Vault::Store::NewId()); }
			catch (const std::exception &) { status->setText(Failure()); return; }
			box->closeBox();
			EditTemplate(context, std::move(record));
		});
		box->addButton(tr::lng_cancel(), [=] { box->closeBox(); });
		box->addLeftButton(rpl::single(Text(u"Refresh"_q, u"Обновить"_q)), [=] {
			box->closeBox();
			if (Available(context)) ShowTemplates(context, page);
		});
		Core::App().capyVaultWorker().templates(context.handle, [=](Vault::Worker::Result result) {
			if (!weak || *closed) return;
			if (!result.ok) { status->setText(Failure()); return; }
			constexpr auto PageSize = 16;
			const auto count = int(result.ids.size());
			const auto actualPage = std::clamp(page, 0, std::max(0, (count - 1) / PageSize));
			const auto first = actualPage * PageSize;
			const auto last = std::min(count, first + PageSize);
			status->setText(count ? Text(u"Choose a template to preview. Page "_q, u"Выберите шаблон для предпросмотра. Страница "_q)
				+ QString::number(actualPage + 1) : Text(u"No templates yet. Create your first response."_q, u"Шаблонов пока нет. Создайте первый ответ."_q));
			for (auto i = first; i != last; ++i) {
				const auto record = result.ids[i];
				const auto label = box->lifetime().make_state<rpl::variable<QString>>(Text(u"Loading…"_q, u"Загрузка…"_q));
				const auto button = box->addRow(object_ptr<Ui::RoundButton>(box, label->value(), st::defaultActiveButton), st::boxPadding);
				button->setTextTransform(Ui::RoundButtonTextTransform::NoTransform);
				button->setFullWidth(st::boxWideWidth - st::boxPadding.left() - st::boxPadding.right());
				button->setDisabled(true);
				Core::App().capyVaultWorker().read(context.handle, record, [=](Vault::Worker::Result loaded) {
					if (!weak || *closed) return;
					const auto bytes = loaded.text ? QByteArray::fromStdString(*loaded.text) : QByteArray();
					const auto text = QString::fromUtf8(bytes);
					if (!loaded.ok || !loaded.text || text.toUtf8() != bytes || text.size() > 4096) {
						*label = Text(u"Could not load this template"_q, u"Не удалось загрузить шаблон"_q);
						return;
					}
					const auto shortText = text.simplified();
					*label = shortText.isEmpty()
						? Text(u"Empty template"_q, u"Пустой шаблон"_q)
						: shortText;
					button->setDisabled(false);
					button->setClickedCallback([=] {
						box->closeBox();
						if (Available(context)) PreviewTemplate(context, record, text);
					});
				});
			}
			const auto addPage = [=](int next, QString label) {
				const auto button = box->addRow(object_ptr<Ui::RoundButton>(box, rpl::single(std::move(label)), st::defaultActiveButton), st::boxPadding);
				button->setClickedCallback([=] {
					box->closeBox();
					if (Available(context)) ShowTemplates(context, next);
				});
			};
			if (actualPage) addPage(actualPage - 1, Text(u"Previous page"_q, u"Предыдущая страница"_q));
			if (last < count) addPage(actualPage + 1, Text(u"Next page"_q, u"Следующая страница"_q));
		});
	}));
}

} // namespace

void AddNoteAction(not_null<Window::SessionController*> controller,
		Dialogs::EntryState request, const Window::PeerMenuCallback &addAction) {
	const auto peer = request.key.peer();
	if (!peer || request.key.sublist()) return;
	const auto topic = request.key.topic();
	if (topic && topic->rootId() <= 0) return;
	const auto type = peer->isUser() ? 1 : peer->isChat() ? 2 : 3;
	const auto id = peer->isUser() ? peerToUser(peer->id).bare
		: peer->isChat() ? peerToChat(peer->id).bare : peerToChannel(peer->id).bare;
	const auto record = Vault::Store::Note(type, id, topic ? topic->rootId().bare : 0);
	const auto recipient = peer->name() + (topic ? u" / "_q + topic->title() : QString());
	const auto session = &controller->session();
	const auto weakSession = base::make_weak(session);
	const auto handle = session->account().capyVaultHandle();
	const auto show = controller->uiShow();
	addAction(Text(u"CapybaraGram · Chat note"_q, u"CapybaraGram · Заметка к чату"_q), [=] {
		if (const auto strong = weakSession.get()) ShowNote(strong, show, handle, record, recipient);
	}, &st::menuIconEdit);
}

void AddTemplatesAction(not_null<Window::SessionController*> controller,
		Dialogs::EntryState request, Fn<bool(QString)> insertDraft,
		const Window::PeerMenuCallback &addAction) {
	const auto peer = request.key.peer();
	if (!peer || !insertDraft || request.key.sublist()) return;
	const auto topic = request.key.topic();
	const auto session = &controller->session();
	const auto context = TemplateContext{
		.session = base::make_weak(session),
		.show = controller->uiShow(),
		.handle = session->account().capyVaultHandle(),
		.recipient = peer->name() + (topic ? u" / "_q + topic->title() : QString()),
		.insertDraft = std::move(insertDraft),
	};
	addAction(Text(u"CapybaraGram · Response templates"_q, u"CapybaraGram · Шаблоны ответов"_q), [=] {
		if (Available(context)) ShowTemplates(context);
	}, &st::menuIconEdit);
}

} // namespace Capy
