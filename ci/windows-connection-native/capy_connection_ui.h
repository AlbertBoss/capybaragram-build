// SPDX-License-Identifier: MIT
#pragma once
#include "window/window_peer_menu.h"
#include <memory>

class QWidget;
namespace Ui { class Show; }

namespace Capy {
[[nodiscard]] QString ConnectionButtonText();
void ShowIntroConnection(std::shared_ptr<Ui::Show> show,
	not_null<QWidget*> owner);
void AddConnectionAction(not_null<Window::SessionController*> controller,
	const Window::PeerMenuCallback &addAction);
} // namespace Capy
