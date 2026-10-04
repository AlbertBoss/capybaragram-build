// SPDX-License-Identifier: MIT
#pragma once
#include "dialogs/dialogs_key.h"
#include "window/window_peer_menu.h"
namespace Capy {
void AddArchiveAction(not_null<Window::SessionController*> controller,
	Dialogs::EntryState request, const Window::PeerMenuCallback &addAction);
} // namespace Capy
