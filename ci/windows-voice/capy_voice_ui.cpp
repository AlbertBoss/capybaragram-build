// SPDX-License-Identifier: MIT
#include "capybara/capy_voice_ui.h"
#include "capybara/voice_worker.h"
#include "capybara/vault_worker.h"
#include "core/application.h"
#include "data/data_document.h"
#include "data/data_document_media.h"
#include "data/data_media_types.h"
#include "data/data_session.h"
#include "history/history_item.h"
#include "lang/lang_keys.h"
#include "main/main_account.h"
#include "main/main_session.h"
#include "ui/layers/generic_box.h"
#include "ui/layers/show.h"
#include "ui/widgets/buttons.h"
#include "ui/widgets/checkbox.h"
#include "ui/widgets/fields/input_field.h"
#include "ui/widgets/labels.h"
#include "ui/widgets/popup_menu.h"
#include "window/window_controller.h"
#include "window/window_session_controller.h"
#include "styles/style_boxes.h"
#include "styles/style_layers.h"
#include "styles/style_widgets.h"
#include <QClipboard>
#include <QGuiApplication>
#include <QPointer>
#include <QTimer>
#include <algorithm>
#include <array>

namespace Capy {
namespace {
QString Text(const QString &en, const QString &ru) {
    return Lang::Id().startsWith(u"ru"_q) ? ru : en;
}
enum class SpeechLanguage { Auto, Russian, English };
struct State {
    bool closed = false;
    bool pending = false;
    bool downloadAllowed = false;
    std::string language = "auto";
    std::array<QPointer<Ui::Radiobutton>, 3> languages;
    std::shared_ptr<Voice::Job> job;
    QPointer<Ui::RoundButton> start;
    QPointer<Ui::RoundButton> copy;
    ~State() { if (job) job->cancel(); }
};
} // namespace

void AddVoiceAction(not_null<Ui::PopupMenu*> menu,
        not_null<DocumentData*> document, HistoryItem *item,
        not_null<Window::SessionController*> controller) {
    if (!item || (!document->isVoiceMessage() && !document->isVideoMessage())
        || document->forbidsFileSave()) return;
    const auto weakController = base::make_weak(controller.get());
    const auto weakWindow = base::make_weak(&controller->window());
    const auto weakSession = base::make_weak(&controller->session());
    const auto handle = controller->session().account().capyVaultHandle();
    const auto messageId = item->fullId();
    const auto documentId = document->id;
    const auto chatEntry = controller->activeChatEntryCurrent();
    const auto valid = [=] {
        return weakController && weakWindow && weakSession
            && weakWindow->sessionController() == weakController.get()
            && weakController->activeChatEntryCurrent() == chatEntry
            && !Core::App().passcodeLocked()
            && Core::App().capyVaultWorker().usable(handle);
    };
    menu->addAction(Text(u"CapybaraGram · Offline transcription"_q,
        u"CapybaraGram · Расшифровать на компьютере"_q), [=] {
        if (!valid()) return;
        weakController->uiShow()->showBox(Box([=](not_null<Ui::GenericBox*> box) {
            if (!valid()) { box->closeBox(); return; }
            box->setWidth(st::boxWideWidth);
            box->setMaxHeight(st::boxWideWidth);
            box->setTitle(rpl::single(Text(u"Offline transcription"_q, u"Расшифровка голоса"_q)));
            box->addRow(object_ptr<Ui::FlatLabel>(box,
                Text(u"Without Premium. Audio is processed on this computer. The first use requires a 78 MB model download. Up to 3 minutes and 32 MiB per message. Recognition may contain mistakes."_q,
                    u"Без Premium. Голос обрабатывается на этом компьютере. Для первого запуска нужна загрузка модели 78 МБ. До 3 минут и 32 МиБ на сообщение. В тексте возможны ошибки."_q),
                st::aboutLabel), st::boxPadding);
            const auto state = box->lifetime().make_state<State>();
            box->addRow(object_ptr<Ui::FlatLabel>(box,
                Text(u"Recording language"_q, u"Язык записи"_q),
                st::aboutLabel), st::boxPadding);
            const auto languageGroup = std::make_shared<Ui::RadioenumGroup<SpeechLanguage>>(SpeechLanguage::Auto);
            const auto addLanguage = [=](SpeechLanguage value, const QString &label) {
                const auto radio = box->addRow(object_ptr<Ui::Radioenum<SpeechLanguage>>(
                    box, languageGroup, value, label, st::defaultBoxCheckbox), st::boxPadding);
                state->languages[static_cast<int>(value)] = radio;
            };
            addLanguage(SpeechLanguage::Auto,
                Text(u"Detect automatically"_q, u"Определить автоматически"_q));
            addLanguage(SpeechLanguage::Russian, u"Русский"_q);
            addLanguage(SpeechLanguage::English, u"English"_q);
            languageGroup->setChangedCallback([=](SpeechLanguage value) {
                if (state->closed || state->pending || !valid()) return;
                switch (value) {
                case SpeechLanguage::Auto: state->language = "auto"; break;
                case SpeechLanguage::Russian: state->language = "ru"; break;
                case SpeechLanguage::English: state->language = "en"; break;
                }
            });
            const auto status = box->addRow(object_ptr<Ui::FlatLabel>(box,
                Text(u"Download the voice message in the chat first, then start."_q,
                    u"Сначала загрузите голосовое сообщение в чате, затем запустите расшифровку."_q), st::aboutLabel), st::boxPadding);
            const auto output = box->addRow(object_ptr<Ui::InputField>(box,
                st::defaultInputField, Ui::InputField::Mode::MultiLine,
                rpl::single(Text(u"Recognized text"_q, u"Распознанный текст"_q))), st::boxPadding);
            output->setMaxLength(64000);
            output->setMinHeight(st::boxWideWidth / 3);
            output->setDisabled(true);
            const auto weakBox = QPointer<Ui::GenericBox>(box.get());
            const auto clear = [=] {
                state->closed = true;
                if (state->job) state->job->cancel();
                output->setTextWithTags({});
            };
            const auto close = [=] { clear(); box->closeBox(); };
            box->boxClosing() | rpl::on_next(clear, box->lifetime());
            Core::App().passcodeLockChanges() | rpl::on_next([=](bool locked) {
                if (locked) close();
            }, box->lifetime());
            weakSession->account().sessionChanges() | rpl::on_next([=](Main::Session*) {
                close();
            }, box->lifetime());
            weakWindow->sessionControllerChanges() | rpl::on_next([=](Window::SessionController*) {
                close();
            }, box->lifetime());
            weakController->activeChatEntryChanges() | rpl::on_next([=](Dialogs::RowDescriptor) {
                close();
            }, box->lifetime());
            Lang::Updated() | rpl::on_next(close, box->lifetime());
            state->copy = box->addLeftButton(rpl::single(Text(u"Copy text"_q, u"Скопировать текст"_q)), [=] {
                if (!state->closed && !state->pending && valid()) {
                    QGuiApplication::clipboard()->setText(output->getLastText());
                }
            });
            state->copy->setDisabled(true);
            state->start = box->addButton(rpl::single(Text(u"Start"_q, u"Расшифровать"_q)), [=] {
                if (state->closed || state->pending || !valid()) return;
                const auto current = weakSession->data().message(messageId);
                const auto doc = current && current->media() ? current->media()->document() : nullptr;
                if (!doc || doc->id != documentId || doc->forbidsFileSave()
                    || (!doc->isVoiceMessage() && !doc->isVideoMessage())
                    || doc->size <= 0 || doc->size > 32 * 1024 * 1024
                    || doc->duration() > 180000) {
                    status->setText(Text(u"The message changed or exceeds the supported size/duration."_q,
                        u"Сообщение изменилось или превышает допустимый размер/длительность."_q)); return;
                }
                Voice::Worker::Input input;
                input.expectedBytes = doc->size;
                input.allowModelDownload = state->downloadAllowed;
                input.language = state->language;
                const auto media = doc->activeMediaView();
                const auto bytes = media ? media->bytes() : QByteArray();
                if (!bytes.isEmpty()) {
                    if (bytes.size() != doc->size) {
                        status->setText(Text(u"Wait until the complete voice message is downloaded."_q,
                            u"Дождитесь полной загрузки голосового сообщения."_q)); return;
                    }
                    input.bytes.assign(reinterpret_cast<const std::uint8_t*>(bytes.constData()),
                        reinterpret_cast<const std::uint8_t*>(bytes.constData()) + bytes.size());
                } else {
                    input.fileUtf8 = doc->filepath(true).toUtf8().toStdString();
                    if (input.fileUtf8.empty()) {
                        status->setText(Text(u"Download this voice message first."_q,
                            u"Сначала загрузите это голосовое сообщение."_q)); return;
                    }
                }
                output->setTextWithTags({}); state->copy->setDisabled(true);
                const auto job = Core::App().capyVoiceWorker().submit(std::move(input), [=](Voice::Worker::Result result) {
                    if (!weakBox || state->closed || !valid()) {
                        std::fill(result.text.begin(), result.text.end(), '\0'); return;
                    }
                    state->pending = false; state->job.reset(); state->start->setDisabled(false);
                    for (const auto &radio : state->languages) if (radio) radio->setDisabled(false);
                    if (result.code == Voice::Worker::Result::Code::ModelRequired) {
                        state->downloadAllowed = true;
                        state->start->setText(rpl::single(Text(u"Download 78 MB and start"_q,
                            u"Загрузить 78 МБ и начать"_q)));
                        status->setText(Text(u"The speech model is missing. Press the button to download it."_q,
                            u"Модель распознавания ещё не загружена. Нажмите кнопку для загрузки."_q));
                    } else if (result.code == Voice::Worker::Result::Code::Ok) {
                        output->setTextWithTags({ QString::fromUtf8(result.text.data(), static_cast<int>(result.text.size())), {} });
                        state->copy->setDisabled(result.text.empty());
                        status->setText(Text(u"Done. Text was not sent or saved automatically."_q,
                            u"Готово. Текст не отправлялся и не сохранялся автоматически."_q));
                    } else {
                        status->setText(Text(u"Could not recognize this recording. Try again."_q,
                            u"Не удалось распознать запись. Попробуйте ещё раз."_q));
                    }
                    std::fill(result.text.begin(), result.text.end(), '\0');
                    box->updateButtonsGeometry();
                });
                if (!job) {
                    status->setText(Text(u"Another recording is being processed. Close its transcription window and retry."_q,
                        u"Уже обрабатывается другая запись. Закройте её окно расшифровки и повторите."_q)); return;
                }
                state->job = job; state->pending = true; state->start->setDisabled(true);
                for (const auto &radio : state->languages) if (radio) radio->setDisabled(true);
            });
            box->addButton(tr::lng_cancel(), close);
            const auto timer = new QTimer(box.get());
            timer->setInterval(250);
            QObject::connect(timer, &QTimer::timeout, box.get(), [=] {
                if (state->closed || !valid()) { close(); return; }
                if (!state->pending || !state->job) return;
                const auto stage = state->job->stage();
                if (stage == Voice::Job::Stage::Download) {
                    status->setText(Text(u"Downloading model: "_q, u"Загрузка модели: "_q)
                        + QString::number(state->job->progress()) + u"%"_q);
                } else if (stage == Voice::Job::Stage::Recognize) {
                    status->setText(Text(u"Recognizing: "_q, u"Распознавание: "_q)
                        + QString::number(state->job->progress()) + u"%"_q);
                } else {
                    status->setText(Text(u"Preparing audio and model…"_q, u"Подготовка записи и модели…"_q));
                }
            });
            timer->start();
        }));
    });
}
} // namespace Capy
