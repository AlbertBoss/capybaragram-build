// SPDX-License-Identifier: MIT
#pragma once

#include <QDataStream>
#include <algorithm>
#include <string>
#include <string_view>

namespace Capy::Authorization {

inline bool Valid(std::string_view identity) {
	return identity.size() == 32 && std::all_of(identity.begin(), identity.end(), [](char ch) {
		return (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f');
	});
}

inline void Write(QDataStream &stream, std::string_view identity) {
	stream << quint32(0x43504731); // CPG1; inside the encrypted MTP blob
	// Preserve an invalid marker across restart instead of falling back to legacy.
	const auto encoded = Valid(identity) ? std::string(identity) : std::string(32, '-');
	stream.writeRawData(encoded.data(), 32);
}

inline std::string Read(QDataStream &stream) {
	if (stream.status() != QDataStream::Ok) return {};
	if (stream.atEnd()) return std::string(32, '0'); // pre-Capy authorization
	auto tag = quint32();
	stream >> tag;
	auto identity = std::string(32, '\0');
	if (tag != 0x43504731 || stream.readRawData(identity.data(), 32) != 32
		|| stream.status() != QDataStream::Ok || !stream.atEnd() || !Valid(identity)) return {};
	return identity;
}

} // namespace Capy::Authorization
