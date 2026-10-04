// SPDX-License-Identifier: MIT
#pragma once
class DocumentData;
class HistoryItem;
namespace Ui { class PopupMenu; }
namespace Window { class SessionController; }
namespace Capy {
void AddVoiceAction(not_null<Ui::PopupMenu*> menu,
    not_null<DocumentData*> document, HistoryItem *item,
    not_null<Window::SessionController*> controller);
} // namespace Capy
