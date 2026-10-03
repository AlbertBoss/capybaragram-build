// SPDX-License-Identifier: MIT
#pragma once

#include "window/window_peer_menu.h"

namespace Capy {

void AddReadModeAction(not_null<Window::SessionController*> controller,
	Dialogs::EntryState request,
	const Window::PeerMenuCallback &addAction);

} // namespace Capy
