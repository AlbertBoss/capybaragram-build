// SPDX-License-Identifier: MIT
#include "capybara/capy_connection_ui.h"

#include "capybara/capy_connection_service.h"
#include "core/application.h"
#include "lang/lang_keys.h"
#include "main/main_account.h"
#include "main/main_session.h"
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

QString StatusText(Connection::Service &service) {
	using Phase = Connection::Service::Phase;
	switch (service.phase()) {
	case Phase::Starting:
		return Text(u"Starting the connection route…"_q,
			u"Запускаю маршрут подключения…"_q);
	case Phase::Ready:
		return Text(u"Route enabled. Check Telegram's connection status in the main window. The local route starting alone does not confirm a connection to Telegram."_q,
			u"Маршрут включён. Проверьте статус соединения Telegram в основном окне. Сам запуск локального маршрута ещё не подтверждает подключение к Telegram."_q);
	case Phase::Failed:
		return Text(u"The route could not start. Your normal connection settings remain available. You can retry."_q,
			u"Не удалось запустить маршрут. Обычные настройки подключения доступны. Можно повторить попытку."_q);
	case Phase::Disabled:
		return Text(u"Disabled. Telegram uses your normal connection settings."_q,
			u"Выключено. Telegram использует обычные настройки подключения."_q);
	}
	Unexpected("Connection phase");
}

void ShowConnection(not_null<Window::SessionController*> controller) {
	if (Core::App().passcodeLocked()) return;
	const auto session = &controller->session();
	const auto weakSession = base::make_weak(session);
	controller->uiShow()->showBox(Box([=](not_null<Ui::GenericBox*> box) {
		if (!weakSession || Core::App().passcodeLocked()) {
			box->closeBox();
			return;
		}
		const auto service = QPointer<Connection::Service>(&Core::App().capyConnectionService());
		box->setWidth(st::boxWideWidth);
		box->setTitle(rpl::single(Text(u"CapybaraGram · Connection"_q,
			u"CapybaraGram · Подключение"_q)));
		box->addRow(object_ptr<Ui::FlatLabel>(box,
			Text(u"Experimental connection for chats and files without a separate proxy server. Applies to all accounts until the app closes. Your saved proxies stay unchanged; choosing a normal proxy disables this mode. Calls and other apps use the normal network. Try with or without VPN; availability depends on your network."_q,
				u"Экспериментальное подключение для чатов и файлов без отдельного прокси-сервера. Действует для всех аккаунтов до закрытия приложения. Сохранённые прокси не меняются; выбор обычного прокси выключает этот режим. Звонки и другие приложения используют обычную сеть. Режим можно пробовать с VPN и без него; доступность зависит от сети."_q),
			st::aboutLabel), st::boxPadding);
		const auto status = box->addRow(object_ptr<Ui::FlatLabel>(box,
			StatusText(*service), st::aboutLabel), st::boxPadding);
		const auto update = [=] {
			if (service) status->setText(StatusText(*service));
		};
		service->changes() | rpl::on_next(update, box->lifetime());
		Core::App().passcodeLockChanges() | rpl::on_next([=](bool locked) {
			if (locked) box->closeBox();
		}, box->lifetime());
		session->account().sessionChanges() | rpl::on_next([=](Main::Session*) {
			box->closeBox();
		}, box->lifetime());
		Lang::Updated() | rpl::on_next([=] { box->closeBox(); }, box->lifetime());
		box->addButton(rpl::single(Text(u"Enable / retry"_q, u"Включить / повторить"_q)), [=] {
			if (service && weakSession && !Core::Quitting()
				&& !Core::App().passcodeLocked()) service->setEnabled(true);
		});
		box->addLeftButton(rpl::single(Text(u"Disable"_q, u"Выключить"_q)), [=] {
			if (service && weakSession && !Core::Quitting()
				&& !Core::App().passcodeLocked()) service->setEnabled(false);
		});
		box->addButton(tr::lng_close(), [=] { box->closeBox(); });
	}));
}

} // namespace

void AddConnectionAction(not_null<Window::SessionController*> controller,
		const Window::PeerMenuCallback &addAction) {
	if (Core::App().passcodeLocked()) return;
	const auto weak = base::make_weak(controller);
	addAction(Text(u"CapybaraGram · Connection"_q,
		u"CapybaraGram · Подключение"_q), [=] {
		if (weak) ShowConnection(weak.get());
	}, nullptr);
}

} // namespace Capy
