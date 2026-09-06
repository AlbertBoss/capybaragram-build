// SPDX-License-Identifier: MIT
#include "capy_authorization.h"
#include <QFile>
#include <QTemporaryDir>
#include <iostream>
#include <stdexcept>

namespace {
int Checks = 0;
void Check(bool value) {
	if (!value) throw std::runtime_error("Authorization serialization assertion failed");
	++Checks;
}
QByteArray Encode(std::string_view identity) {
	auto bytes = QByteArray();
	QDataStream stream(&bytes, QIODevice::WriteOnly);
	stream.setVersion(QDataStream::Qt_5_1);
	Capy::Authorization::Write(stream, identity);
	Check(stream.status() == QDataStream::Ok);
	return bytes;
}
std::string Decode(const QByteArray &bytes) {
	QDataStream stream(bytes);
	stream.setVersion(QDataStream::Qt_5_1);
	return Capy::Authorization::Read(stream);
}
}

int main() {
	try {
		const auto identity = std::string("0123456789abcdef0123456789abcdef");
		const auto expected = QByteArray("CPG1") + QByteArray::fromStdString(identity);
		const auto encoded = Encode(identity);
		Check(encoded == expected); // independent wire-format fixture
		Check(Decode(expected) == identity);
		Check(Decode({}) == std::string(32,'0'));
		for (auto length = 1; length < expected.size(); ++length) {
			Check(Decode(expected.left(length)).empty());
		}
		for (auto position = 0; position < expected.size(); ++position) {
			auto corrupt = expected;
			corrupt[position] = '!';
			Check(Decode(corrupt).empty());
		}
		Check(Decode(expected + QByteArray(1,'\0')).empty());
		Check(Decode(expected + QByteArray(1024*1024,'x')).empty());
		Check(Decode(QByteArray("CPG1") + QByteArray(32,'F')).empty());
		Check(Decode(QByteArray("CPG1") + QByteArray(32,'\0')).empty());
		Check(Decode(Encode("")).empty());
		Check(Decode(Encode(std::string(31,'a'))).empty());
		Check(Decode(Encode(std::string(33,'a'))).empty());
		Check(Decode(Encode(std::string(32,'z'))).empty());
		{
			QDataStream broken(encoded);
			broken.setStatus(QDataStream::ReadCorruptData);
			Check(Capy::Authorization::Read(broken).empty());
		}
		// Append after existing authorization bytes and reopen from a real file.
		auto directory = QTemporaryDir();
		Check(directory.isValid());
		const auto path = directory.filePath(QStringLiteral("synthetic-mtp-payload.bin"));
		{
			QFile file(path);
			Check(file.open(QIODevice::WriteOnly));
			QDataStream writer(&file);
			writer.setVersion(QDataStream::Qt_5_1);
			writer << quint64(17) << qint32(2) << QByteArray("synthetic existing keys");
			Capy::Authorization::Write(writer, identity);
			Check(writer.status() == QDataStream::Ok && file.flush());
		}
		{
			QFile file(path);
			Check(file.open(QIODevice::ReadOnly));
			QDataStream reader(&file);
			reader.setVersion(QDataStream::Qt_5_1);
			auto owner = quint64();
			auto dc = qint32();
			auto keys = QByteArray();
			reader >> owner >> dc >> keys;
			Check(owner == 17 && dc == 2 && keys == QByteArray("synthetic existing keys"));
			Check(Capy::Authorization::Read(reader) == identity);
			Check(reader.atEnd());
		}
		std::cout << "CAPY_QT_AUTHORIZATION=PASS checks=" << Checks << '\n';
		return 0;
	} catch (const std::exception &) {
		std::cerr << "CAPY_QT_AUTHORIZATION=FAIL\n";
		return 1;
	}
}
