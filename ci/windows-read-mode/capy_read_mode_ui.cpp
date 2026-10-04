// SPDX-License-Identifier: MIT
#include "capybara/capy_read_mode_ui.h"

#include "apiwrap.h"
#include "capybara/vault_worker.h"
#include "core/application.h"
#include "data/data_channel.h"
#include "data/data_forum_topic.h"
#include "data/data_histories.h"
#include "data/data_peer.h"
#include "data/data_session.h"
#include "dialogs/dialogs_entry.h"
#include "dialogs/dialogs_key.h"
#include "history/history.h"
#include "history/history_item.h"
#include "lang/lang_keys.h"
#include "main/main_account.h"
#include "main/main_session.h"
#include "main/main_session_settings.h"
#include "mtproto/mtp_instance.h"
#include "ui/layers/generic_box.h"
#include "ui/layers/show.h"
#include "ui/widgets/labels.h"
#include "window/window_session_controller.h"
#include "styles/style_boxes.h"
#include "styles/style_layers.h"
#include "styles/style_widgets.h"

#include <QPointer>

namespace Capy {
namespace {

QString Text(const QString &en, const QString &ru) {
	return Lang::Id().startsWith(u"ru"_q) ? ru : en;
}

void ShowReadMode(not_null<Window::SessionController*> controller,
		not_null<Data::Thread*> thread) {
	const auto session = &controller->session();
	const auto weakSession = base::make_weak(session);
	const auto handle = session->account().capyVaultHandle();
	const auto worker = &Core::App().capyVaultWorker();
	if (!worker->usable(handle)) return;
	const auto peer = thread->peer();
	const auto rootId = thread->topicRootId();
	const auto sublistId = thread->monoforumPeerId();
	const auto history = thread->owningHistory();
	const auto topic = thread->asTopic();
	const auto last = topic ? topic->lastServerMessage() : history->lastServerMessage();
	const auto till = last ? last->id : MsgId();
	const auto name = topic ? topic->title() : peer->name();
	controller->uiShow()->showBox(Box([=](not_null<Ui::GenericBox*> box) {
		if (!weakSession || !worker->usable(handle)) { box->closeBox(); return; }
		box->setWidth(st::boxWideWidth);
		box->setTitle(rpl::single(Text(u"CapybaraGram · Silent reading"_q,
			u"CapybaraGram · Нечиталка"_q)));
		box->addRow(object_ptr<Ui::FlatLabel>(box, name, st::aboutLabel), st::boxPadding);
		const auto status = box->addRow(object_ptr<Ui::FlatLabel>(box,
			Text(u"When enabled, this account does not send automatic chat, voice, mention, reaction or story read confirmations from this client. Reading in another client still sends confirmations. This does not hide online status or typing. Explicit reading below is limited to the messages already loaded when this window opened."_q,
				u"После включения этот аккаунт не отправляет из клиента автоматические подтверждения чтения чатов, голоса, упоминаний, реакций и историй. Чтение в другом клиенте по-прежнему отправляет подтверждения. Режим не скрывает статус онлайн и набор текста. Ручное прочтение ниже относится только к сообщениям, уже загруженным при открытии этого окна."_q),
			st::aboutLabel), st::boxPadding);
		struct State { bool pending = false; bool closed = false; mtpRequestId request = 0; };
		const auto state = box->lifetime().make_state<State>();
		const auto weakBox = QPointer<Ui::GenericBox>(box.get());
		const auto available = [=] { return !state->closed && weakSession && worker->usable(handle); };
		box->boxClosing() | rpl::on_next([=] {
			state->closed = true;
			if (weakSession && state->request) weakSession.get()->mtp().cancel(state->request);
		}, box->lifetime());
		Core::App().passcodeLockChanges() | rpl::on_next([=](bool locked) {
			if (locked) box->closeBox();
		}, box->lifetime());
		session->account().sessionChanges() | rpl::on_next([=](Main::Session*) {
			box->closeBox();
		}, box->lifetime());
		Lang::Updated() | rpl::on_next([=] { box->closeBox(); }, box->lifetime());
		const auto silent = session->settings().capySilentRead();
		box->addButton(rpl::single(silent
			? Text(u"Disable silent reading"_q, u"Выключить нечиталку"_q)
			: Text(u"Enable silent reading"_q, u"Включить нечиталку"_q)), [=] {
			if (!available() || state->pending) return;
			session->settings().setCapySilentRead(!silent);
			session->mtp().setCapySilentRead(!silent);
			session->saveSettings();
			box->closeBox();
		});
		// Saved sublists need a separate peer-scoped TL request. Never mark the
		// whole owning history read on behalf of a selected sublist.
		if (till.bare > 0 && !sublistId) {
			box->addLeftButton(rpl::single(Text(u"Mark loaded messages read"_q,
				u"Прочитать загруженные"_q)), [=] {
				if (!available() || state->pending) return;
				state->pending = true;
				status->setText(Text(u"Sending read confirmation…"_q, u"Отправляю подтверждение чтения…"_q));
				const auto finish = [=](bool ok) {
					if (!weakBox || !available()) return;
					state->pending = false;
					state->request = 0;
					if (ok) session->data().histories().requestDialogEntry(history);
					status->setText(ok
						? Text(u"Telegram accepted the read confirmation. Silent reading remains as configured."_q,
							u"Telegram принял подтверждение. Настройка нечиталки сохранена."_q)
						: Text(u"The read confirmation was not accepted. You can try again."_q,
							u"Подтверждение не принято. Можно попробовать ещё раз."_q));
				};
				const auto fail = [=](const MTP::Error&, const MTP::Response&) { finish(false); return true; };
				if (rootId) {
					state->request = session->mtp().sendCapyExplicitRead(MTPmessages_ReadDiscussion(
						peer->input(), MTP_int(rootId), MTP_int(till)), MTP::ResponseHandler{
						.done = [=](const MTP::Response &response) {
							if (!available()) return true;
							auto result = MTPBool(); auto from = response.reply.constData();
							const auto ok = result.read(from, from + response.reply.size()) && result.type() == mtpc_boolTrue;
							finish(ok); return true;
						}, .fail = fail });
				} else if (const auto channel = peer->asChannel()) {
					state->request = session->mtp().sendCapyExplicitRead(MTPchannels_ReadHistory(
						channel->inputChannel(), MTP_int(till)), MTP::ResponseHandler{
						.done = [=](const MTP::Response &response) {
							if (!available()) return true;
							auto result = MTPBool(); auto from = response.reply.constData();
							finish(result.read(from, from + response.reply.size()) && result.type() == mtpc_boolTrue); return true;
						}, .fail = fail });
				} else {
					state->request = session->mtp().sendCapyExplicitRead(MTPmessages_ReadHistory(
						peer->input(), MTP_int(till)), MTP::ResponseHandler{
						.done = [=](const MTP::Response &response) {
							if (!available()) return true;
							auto result = MTPmessages_AffectedMessages(); auto from = response.reply.constData();
							const auto ok = result.read(from, from + response.reply.size());
							if (ok) session->api().applyAffectedMessages(peer, result);
							finish(ok); return true;
						}, .fail = fail });
				}
			});
		}
		box->addButton(tr::lng_close(), [=] { box->closeBox(); });
	}));
}

} // namespace

void AddReadModeAction(not_null<Window::SessionController*> controller,
		Dialogs::EntryState request, const Window::PeerMenuCallback &addAction) {
	const auto thread = request.key.thread();
	if (!thread || !Core::App().capyVaultWorker().usable(controller->session().account().capyVaultHandle())) return;
	const auto weak = base::make_weak(controller);
	const auto peer = thread->peer();
	const auto root = thread->topicRootId();
	const auto sublist = thread->monoforumPeerId();
	const auto silent = controller->session().settings().capySilentRead();
	addAction(silent
		? Text(u"CapybaraGram · Silent reading: on"_q, u"CapybaraGram · Нечиталка: включена"_q)
		: Text(u"CapybaraGram · Silent reading: off"_q, u"CapybaraGram · Нечиталка: выключена"_q), [=] {
		if (!weak) return;
		const auto history = peer->owner().historyLoaded(peer);
		const auto current = history ? history->threadFor(root, sublist) : nullptr;
		if (current) ShowReadMode(weak.get(), current);
	}, nullptr);
}

} // namespace Capy
