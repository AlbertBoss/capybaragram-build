// SPDX-License-Identifier: MIT
#include "capy_archive_settings.h"
#include <QIODevice>
#include <iostream>
#include <stdexcept>

namespace {
int Checks = 0;
void Check(bool value) {
	if (!value) throw std::runtime_error("Archive setting assertion failed");
	++Checks;
}
QByteArray Encode(qint32 tag, qint32 version, qint32 enabled) {
	auto bytes = QByteArray();
	auto stream = QDataStream(&bytes, QIODevice::WriteOnly);
	stream << tag << version << enabled;
	return bytes;
}
bool Decode(const QByteArray &bytes) {
	auto stream = QDataStream(bytes);
	return Capy::ArchiveSettings::Read(stream);
}
} // namespace
int main() {
	try {
		using namespace Capy::ArchiveSettings;
		Check(!Decode({}));
		for (const auto enabled : {false, true}) {
			auto bytes = QByteArray();
			auto stream = QDataStream(&bytes, QIODevice::WriteOnly);
			Write(stream, enabled);
			Check(bytes.size() == SerializedSize && Decode(bytes) == enabled);
			for (auto n = 1; n != SerializedSize; ++n) Check(!Decode(bytes.first(n)));
		}
		Check(!Decode(Encode(Tag + 1, Version, 1)));
		Check(!Decode(Encode(Tag, Version + 1, 1)));
		Check(!Decode(Encode(Tag, Version, -1)));
		Check(!Decode(Encode(Tag, Version, 2)));
		std::cout << "CAPY_QT_ARCHIVE_SETTINGS=PASS checks=" << Checks << '\n';
		return 0;
	} catch (const std::exception &) {
		std::cerr << "CAPY_QT_ARCHIVE_SETTINGS=FAIL\n";
		return 1;
	}
}
