// SPDX-License-Identifier: MIT
#include "capybara/capy_archive_bridge.h"
#include "capybara/archive_worker.h"
#include "capybara/verified_input.h"
#include "base/unixtime.h"
#include "core/application.h"
#include "core/file_location.h"
#include "data/data_document.h"
#include "data/data_document_media.h"
#include "data/data_media_types.h"
#include "data/data_peer.h"
#include "data/data_photo.h"
#include "data/data_photo_media.h"
#include "history/history.h"
#include "history/history_item.h"
#include "main/main_account.h"
#include "main/main_session.h"
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QMimeDatabase>
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <algorithm>
#include <cstring>

namespace Capy {
namespace {
struct Memory final {
	std::string bytes;
	std::size_t position = 0;
	~Memory() { if (!bytes.empty()) SecureZeroMemory(bytes.data(), bytes.size()); }
};

Archive::Store::Reader FromBytes(const QByteArray &bytes) {
	const auto input = std::make_shared<Memory>();
	input->bytes.assign(bytes.constData(), static_cast<std::size_t>(bytes.size()));
	return [input](std::span<char> out) {
		const auto count = std::min(out.size(), input->bytes.size() - input->position);
		if (count) std::memcpy(out.data(), input->bytes.data() + input->position, count);
		input->position += count;
		return count;
	};
}

Archive::Store::Reader FromLocation(const Core::FileLocation &location,
		std::uint64_t expected) {
	if (location.isEmpty() || location.inMediaCache() || !location.accessEnable()) return {};
	struct Access final {
		const Core::FileLocation &location;
		~Access() { location.accessDisable(); }
	} access{location};
	// This path comes from the matching native Document/Photo object, not remote
	// filenames. The received object's own declared byte count must also match.
	const auto path = std::filesystem::path(location.name().toStdWString());
	const auto input = Archive::VerifiedInput::Open(path.parent_path(), path, expected);
	return [input](std::span<char> out) { return input->read(out); };
}
} // namespace

bool CaptureArchive(not_null<HistoryItem*> item, Archive::Reason reason) {
	try {
	const auto session = &item->history()->session();
	const auto handle = session->account().capyArchiveHandle();
	const auto worker = &Core::App().capyArchiveWorker();
	if (!worker->enabled(handle) || item->id.bare <= 0) return false;
	const auto peer = item->history()->peer;
	auto snapshot = Archive::Snapshot();
	snapshot.peerType = static_cast<std::uint8_t>(peer->isUser() ? 1 : peer->isChat() ? 2 : 3);
	snapshot.peer = peer->isUser() ? peerToUser(peer->id).bare
		: peer->isChat() ? peerToChat(peer->id).bare : peerToChannel(peer->id).bare;
	snapshot.topic = static_cast<std::uint64_t>(std::max<qint64>(0, item->topicRootId().bare));
	snapshot.message = item->id.bare;
	snapshot.sentAt = item->date();
	snapshot.capturedAt = base::unixtime::now();
	snapshot.reason = reason;
	const auto original = item->originalText();
	snapshot.text = original.text.toUtf8().toStdString();
	if (snapshot.text.size() > 60000) return false;
	auto entities = QJsonArray();
	for (const auto &entity : original.entities) {
		entities.push_back(QJsonObject{
			{u"type"_q, int(entity.type())}, {u"offset"_q, entity.offset()},
			{u"length"_q, entity.length()}, {u"data"_q, entity.data()}});
	}
	auto metadata = QJsonObject{
		{u"adapter"_q, u"capy.native.archive.v1"_q}, {u"entities"_q, entities},
		{u"outgoing"_q, item->out()}};
	auto reader = Archive::Store::Reader();
	auto expected = std::uint64_t();
	const auto media = item->media();
	if (media) {
		snapshot.media = Archive::MediaState::Unavailable;
		if (const auto document = media->document()) {
			snapshot.mime = document->mimeString().toUtf8().toStdString();
			if (snapshot.mime.empty()) snapshot.mime = "application/octet-stream";
			metadata.insert(u"kind"_q, u"document"_q);
			metadata.insert(u"document"_q, QString::number(document->id));
			metadata.insert(u"filename"_q, document->filename());
			if (document->size > 0 && document->size <= Archive::Store::MaxMediaBytes) {
				expected = static_cast<std::uint64_t>(document->size);
				const auto view = document->activeMediaView();
				const auto bytes = view ? view->bytes() : QByteArray();
				if (static_cast<std::uint64_t>(bytes.size()) == expected) {
					reader = FromBytes(bytes);
				} else if (bytes.isEmpty()) {
					try { reader = FromLocation(document->location(true), expected); }
					catch (const std::exception &) { }
				}
			}
		} else if (const auto photo = media->photo()) {
			metadata.insert(u"kind"_q, u"photo"_q);
			metadata.insert(u"photo"_q, QString::number(photo->id));
			const auto size = Data::PhotoSize::Large;
			const auto bytesExpected = photo->imageByteSize(size);
			if (photo->hasExact(size) && bytesExpected > 0
				&& bytesExpected <= Archive::Store::MaxMediaBytes) {
				expected = static_cast<std::uint64_t>(bytesExpected);
				const auto view = photo->activeMediaView();
				const auto bytes = view && view->loaded() ? view->imageBytes(size) : QByteArray();
				if (static_cast<std::uint64_t>(bytes.size()) == expected) {
					snapshot.mime = QMimeDatabase().mimeTypeForData(bytes).name().toUtf8().toStdString();
					reader = FromBytes(bytes);
				} else if (bytes.isEmpty()) {
					snapshot.mime = "image/jpeg";
					try { reader = FromLocation(photo->location(true), expected); }
					catch (const std::exception &) { }
				}
			}
		} else {
			metadata.insert(u"kind"_q, u"other"_q);
		}
	}
	if (snapshot.text.empty() && !media) return false; // no empty service notification
	snapshot.content = QJsonDocument(metadata).toJson(QJsonDocument::Compact).toStdString();
	if (snapshot.content.size() > 60000 || snapshot.mime.size() > 128) return false;
	if (!reader) expected = 0;
	if (worker->capture(handle, snapshot, expected, std::move(reader))) return true;
	// An unavailable/oversized/busy original must not discard received text.
	metadata.insert(u"originalNotSaved"_q, u"admission_failed"_q);
	snapshot.content = QJsonDocument(metadata).toJson(QJsonDocument::Compact).toStdString();
	return worker->capture(handle, std::move(snapshot));
	} catch (const std::exception &) {
		// A failed local capture must never interrupt Telegram's native lifecycle.
		return false;
	}
}
} // namespace Capy
