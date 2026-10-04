// SPDX-License-Identifier: MIT
#include "voice_worker.h"
#include "voice_decoder.h"
#include "offline_engine.h"
#include <QCryptographicHash>
#include <QDir>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QFile>
#include <QFileInfo>
#include <QtNetwork/QNetworkAccessManager>
#include <QtNetwork/QNetworkReply>
#include <QtNetwork/QNetworkRequest>
#include <QSaveFile>
#include <QTimer>
#include <QUrl>
#include <algorithm>
#include <stdexcept>

namespace Capy::Voice {
namespace {
constexpr auto ModelBytes = 77691713LL;
constexpr auto ModelHash = "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21";
constexpr auto ModelUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny.bin";
constexpr auto MaxSource = 32 * 1024 * 1024;
void Require(bool value) { if (!value) throw std::runtime_error("local voice operation failed"); }
bool VerifiedModel(const QString &path, const std::atomic<bool> &cancel) {
    const QFileInfo info(path);
    if (!info.isFile() || info.isSymLink() || info.size() != ModelBytes) return false;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly) || file.size() != ModelBytes) return false;
    QCryptographicHash hash(QCryptographicHash::Sha256);
    qint64 count = 0;
    while (!file.atEnd()) {
        if (cancel.load()) return false;
        auto bytes = file.read(1024 * 1024);
        if (bytes.isEmpty()) return false;
        count += bytes.size(); if (count > ModelBytes) return false;
        hash.addData(bytes);
    }
    return count == ModelBytes && hash.result().toHex() == ModelHash;
}
void DownloadModel(const QString &path, const std::atomic<bool> &cancel,
        std::atomic<int> &progress) {
    Require(!QFileInfo(path).isSymLink());
    QUrl url(QString::fromLatin1(ModelUrl));
    QNetworkAccessManager network;
    QElapsedTimer total; total.start();
    for (int redirect = 0; redirect <= 6; ++redirect) {
        Require(!cancel.load() && url.isValid() && url.scheme() == QStringLiteral("https")
            && url.userInfo().isEmpty() && !url.host().isEmpty()
            && (url.port(-1) == -1 || url.port() == 443));
        QSaveFile target(path);
        target.setDirectWriteFallback(false);
        Require(target.open(QIODevice::WriteOnly));
        Require(target.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner));
        QNetworkRequest request(url);
        request.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::ManualRedirectPolicy);
        request.setAttribute(QNetworkRequest::CookieLoadControlAttribute, QNetworkRequest::Manual);
        request.setAttribute(QNetworkRequest::CookieSaveControlAttribute, QNetworkRequest::Manual);
        request.setAttribute(QNetworkRequest::AuthenticationReuseAttribute, QNetworkRequest::Manual);
        request.setTransferTimeout(30000);
        request.setRawHeader("Accept-Encoding", "identity");
        const auto reply = network.get(request);
        reply->setReadBufferSize(1024 * 1024);
        QEventLoop loop; QTimer cancelTimer;
        cancelTimer.setInterval(50);
        bool failed = false;
        qint64 count = 0;
        QCryptographicHash hash(QCryptographicHash::Sha256);
        const auto drain = [&] {
            const auto status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
            if (status >= 300 && status < 400) { reply->readAll(); return; }
            while (reply->bytesAvailable()) {
                auto bytes = reply->read(65536);
                count += bytes.size();
                if (count > ModelBytes || target.write(bytes) != bytes.size()) {
                    failed = true; reply->abort(); return;
                }
                hash.addData(bytes);
                progress.store(static_cast<int>(count * 100 / ModelBytes));
            }
        };
        QObject::connect(reply, &QNetworkReply::readyRead, &loop, drain);
        QObject::connect(reply, &QNetworkReply::finished, &loop, &QEventLoop::quit);
        QObject::connect(&cancelTimer, &QTimer::timeout, &loop, [&] {
            if (cancel.load() || total.elapsed() > 5 * 60 * 1000) {
                failed = true; reply->abort(); loop.quit();
            }
        });
        cancelTimer.start();
        if (!reply->isFinished()) loop.exec();
        drain();
        const auto status = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        const auto next = reply->attribute(QNetworkRequest::RedirectionTargetAttribute).toUrl();
        const auto ok = !failed && !cancel.load() && reply->error() == QNetworkReply::NoError;
        delete reply;
        Require(ok);
        if (status >= 300 && status < 400 && !next.isEmpty()) {
            target.cancelWriting(); url = url.resolved(next); continue;
        }
        Require(status == 200 && count == ModelBytes && hash.result().toHex() == ModelHash);
        Require(target.commit()); return;
    }
    Require(false);
}
struct SensitiveSamples {
    std::vector<float> values;
    ~SensitiveSamples() { std::fill(values.begin(), values.end(), 0.F); }
};
} // namespace

void Job::cancel() {
    _cancel.store(true);
    std::lock_guard lock(_mutex);
    if (_engine) _engine->cancel();
}
int Job::progress() const {
    if (_stage.load() == Stage::Download) return _downloadProgress.load();
    std::lock_guard lock(_mutex);
    return _engine ? _engine->progress() : 0;
}
Worker::Worker(std::string directory, Post post)
: _directory(std::move(directory)), _post(std::move(post))
, _alive(std::make_shared<std::atomic<bool>>(true)), _thread([this] { loop(); }) {
}
Worker::~Worker() {
    _alive->store(false);
    {
        std::lock_guard lock(_mutex);
        _stopping = true;
        if (_current) _current->cancel();
    }
    _wake.notify_one();
    _thread.join();
}
std::shared_ptr<Job> Worker::submit(Input input, Done done) {
    std::lock_guard lock(_mutex);
    if (_stopping || _current) {
        std::fill(input.bytes.begin(), input.bytes.end(), 0);
        return nullptr;
    }
    auto job = std::make_shared<Job>();
    _current = job;
    _pending.emplace(Task{ std::move(input), std::move(done), job });
    _wake.notify_one();
    return job;
}
void Worker::loop() {
    for (;;) {
        std::optional<Task> task;
        {
            std::unique_lock lock(_mutex);
            _wake.wait(lock, [&] { return _pending || _stopping; });
            if (_stopping && !_pending) return;
            task = std::move(_pending); _pending.reset();
        }
        auto &input = task->input;
        const auto job = task->job;
        Result result;
        try {
            Require(!job->_cancel.load() && input.expectedBytes > 0 && input.expectedBytes <= MaxSource
                && (input.language == "auto" || input.language == "ru" || input.language == "en"));
            const auto directory = QString::fromUtf8(_directory.data(), static_cast<int>(_directory.size()));
            Require(QFileInfo(directory).isAbsolute() && !QFileInfo(directory).isSymLink()
                && QDir().mkpath(directory));
            const auto model = QDir(directory).filePath(QStringLiteral("tiny.bin"));
            job->_stage.store(Job::Stage::Model);
            auto modelVerified = VerifiedModel(model, job->_cancel);
            if (!modelVerified) {
                if (!input.allowModelDownload) {
                    result.code = Result::Code::ModelRequired;
                } else {
                    job->_stage.store(Job::Stage::Download);
                    DownloadModel(model, job->_cancel, job->_downloadProgress);
                    modelVerified = VerifiedModel(model, job->_cancel);
                }
            }
            if (result.code != Result::Code::ModelRequired) {
                Require(!job->_cancel.load() && modelVerified);
                if (input.bytes.empty()) {
                    const auto name = QString::fromUtf8(input.fileUtf8.data(), static_cast<int>(input.fileUtf8.size()));
                    Require(QFileInfo(name).isFile() && !QFileInfo(name).isSymLink());
                    QFile file(name); Require(file.open(QIODevice::ReadOnly) && file.size() == input.expectedBytes);
                    input.bytes.resize(static_cast<std::size_t>(input.expectedBytes));
                    Require(file.read(reinterpret_cast<char*>(input.bytes.data()), input.expectedBytes) == input.expectedBytes
                        && file.atEnd() && file.size() == input.expectedBytes);
                }
                Require(input.bytes.size() == static_cast<std::size_t>(input.expectedBytes));
                job->_stage.store(Job::Stage::Decode);
                SensitiveSamples pcm{ DecodeAudio(input.bytes, job->_cancel) };
                std::fill(input.bytes.begin(), input.bytes.end(), 0); input.bytes.clear();
                Require(!job->_cancel.load());
                auto engine = std::make_shared<Engine>(model.toUtf8().toStdString());
                {
                    std::lock_guard lock(job->_mutex);
                    job->_engine = engine;
                    if (job->_cancel.load()) engine->cancel();
                }
                job->_stage.store(Job::Stage::Recognize);
                result.text = engine->transcribe(pcm.values, input.language, 2);
                result.code = Result::Code::Ok;
                { std::lock_guard lock(job->_mutex); job->_engine.reset(); }
            }
        } catch (...) {
            result.code = job->_cancel.load() ? Result::Code::Cancelled : Result::Code::Failed;
            { std::lock_guard lock(job->_mutex); job->_engine.reset(); }
        }
        std::fill(input.bytes.begin(), input.bytes.end(), 0); input.bytes.clear();
        job->_stage.store(Job::Stage::Finished);
        { std::lock_guard lock(_mutex); _current.reset(); }
        const auto alive = _alive;
        if (!alive->load()) {
            std::fill(result.text.begin(), result.text.end(), '\0');
            continue;
        }
        _post([alive, job, done = std::move(task->done), result = std::move(result)]() mutable {
            if (!alive->load() || job->_cancel.load()) {
                std::fill(result.text.begin(), result.text.end(), '\0'); return;
            }
            done(std::move(result));
        });
    }
}
} // namespace Capy::Voice
