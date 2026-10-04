// SPDX-License-Identifier: MIT
#pragma once
#include "ui/rp_widget.h"
#include <QByteArray>
#include <memory>

namespace Capy {
// Owns verified original bytes through the native memory-only streaming reader.
// All methods run on the UI thread. stop() permanently revokes this view.
class ArchivePlayer final : public Ui::RpWidget {
public:
	ArchivePlayer(not_null<Ui::RpWidget*> parent, QByteArray bytes, bool video,
		Fn<void(QString)> status);
	~ArchivePlayer();
	void toggle();
	void seek(crl::time delta);
	void stop();
private:
	class State;
	void paintEvent(QPaintEvent *) override;
	std::unique_ptr<State> _state;
};
} // namespace Capy
