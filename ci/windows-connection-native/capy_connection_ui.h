// SPDX-License-Identifier: MIT
#pragma once
#include "window/window_peer_menu.h"

namespace Capy {
void AddConnectionAction(not_null<Window::SessionController*> controller,
	const Window::PeerMenuCallback &addAction);
} // namespace Capy
