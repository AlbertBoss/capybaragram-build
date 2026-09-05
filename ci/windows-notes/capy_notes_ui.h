// SPDX-License-Identifier: MIT
#pragma once

#include "dialogs/dialogs_key.h"
#include "window/window_peer_menu.h"

namespace Capy {

void AddNoteAction(not_null<Window::SessionController*> controller,
	Dialogs::EntryState request, const Window::PeerMenuCallback &addAction);

void AddTemplatesAction(not_null<Window::SessionController*> controller,
	Dialogs::EntryState request, Fn<bool(QString)> insertDraft,
	const Window::PeerMenuCallback &addAction);

} // namespace Capy
