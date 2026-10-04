// SPDX-License-Identifier: MIT
#pragma once
#include <QDataStream>
namespace Capy::ArchiveSettings {
inline constexpr qint32 Tag = 0x43414731;
inline constexpr qint32 Version = 1;
inline constexpr auto SerializedSize = 3 * int(sizeof(qint32));
inline void Write(QDataStream &stream, bool enabled) {
	stream << Tag << Version << qint32(enabled ? 1 : 0);
}
inline bool Read(QDataStream &stream) {
	if (stream.atEnd()) return false;
	auto tag = qint32();
	auto version = qint32();
	auto value = qint32();
	stream >> tag >> version >> value;
	return stream.status() == QDataStream::Ok && tag == Tag && version == Version && value == 1;
}
} // namespace Capy::ArchiveSettings
