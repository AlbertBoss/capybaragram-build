// SPDX-License-Identifier: MIT
#include "voice_worker.h"
#include "voice_decoder.h"
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QFile>
#include <QMetaObject>
#include <QThread>
#include <algorithm>
#include <cctype>
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {
int checks = 0;
void Check(bool value) { ++checks; if (!value) throw std::runtime_error("voice runtime assertion"); }
std::vector<std::uint8_t> Bytes(const QString &file) {
    QFile input(file); Check(input.open(QIODevice::ReadOnly));
    const auto data = input.readAll();
    return { reinterpret_cast<const std::uint8_t*>(data.constData()),
        reinterpret_cast<const std::uint8_t*>(data.constData()) + data.size() };
}
template <typename Condition> void Wait(Condition condition) {
    QElapsedTimer timeout; timeout.start();
    while (!condition() && timeout.elapsed() < 120000) {
        QCoreApplication::processEvents(); QThread::msleep(5);
    }
    Check(condition());
}
} // namespace
int main(int argc, char **argv) {
    QCoreApplication application(argc, argv);
    try {
        Check(argc == 4);
        const auto arguments = application.arguments();
        const auto directory = arguments[1].toUtf8().toStdString();
        const auto opus = Bytes(arguments[2]);
        const auto aac = Bytes(arguments[3]);
        std::atomic<bool> cancel = false;
        auto first = Capy::Voice::DecodeAudio(opus, cancel);
        auto second = Capy::Voice::DecodeAudio(aac, cancel);
        Check(first.size() >= 5 * 16000 && first.size() <= 15 * 16000);
        Check(std::abs(static_cast<long long>(first.size()) - static_cast<long long>(second.size())) < 1600);
        Check(std::all_of(first.begin(), first.end(), [](float x) { return std::isfinite(x) && std::abs(x) <= 1.F; }));
        cancel = true;
        bool rejected = false;
        try { Capy::Voice::DecodeAudio(opus, cancel); } catch (...) { rejected = true; }
        Check(rejected); cancel = false;
        for (const auto invalid : { std::string("invalid audio"),
                std::string("#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10,\nhttp://127.0.0.1:9/private.wav\n") }) {
            rejected = false;
            try { Capy::Voice::DecodeAudio({invalid.begin(), invalid.end()}, cancel); }
            catch (...) { rejected = true; }
            Check(rejected);
        }
        std::fill(first.begin(), first.end(), 0.F); std::fill(second.begin(), second.end(), 0.F);
        const auto post = [&application](std::function<void()> callback) {
            QMetaObject::invokeMethod(&application, std::move(callback), Qt::QueuedConnection);
        };
        {
            Capy::Voice::Worker worker(directory + "/absent", post);
            bool done = false;
            Capy::Voice::Worker::Input input; input.bytes = opus; input.expectedBytes = opus.size();
            const auto job = worker.submit(std::move(input), [&](Capy::Voice::Worker::Result result) {
                Check(result.code == Capy::Voice::Worker::Result::Code::ModelRequired && result.text.empty()); done = true;
            });
            Check(job != nullptr); Wait([&] { return done; });
        }
        {
            Capy::Voice::Worker worker(directory, post);
            bool done = false;
            Capy::Voice::Worker::Input input; input.bytes = opus; input.expectedBytes = opus.size(); input.language = "en";
            const auto job = worker.submit(std::move(input), [&](Capy::Voice::Worker::Result result) {
                Check(QThread::currentThread() == application.thread());
                Check(result.code == Capy::Voice::Worker::Result::Code::Ok);
                std::transform(result.text.begin(), result.text.end(), result.text.begin(), [](unsigned char c) { return std::tolower(c); });
                Check(result.text.find("country") != std::string::npos && result.text.find("ask") != std::string::npos);
                std::fill(result.text.begin(), result.text.end(), '\0'); done = true;
            });
            Check(job != nullptr); Wait([&] { return done; });
            bool staleCallback = false;
            Capy::Voice::Worker::Input next; next.bytes = aac; next.expectedBytes = aac.size(); next.language = "en";
            const auto cancelled = worker.submit(std::move(next), [&](Capy::Voice::Worker::Result) { staleCallback = true; });
            Check(cancelled != nullptr);
            Wait([&] { return cancelled->stage() == Capy::Voice::Job::Stage::Recognize; });
            cancelled->cancel();
            Wait([&] { return cancelled->stage() == Capy::Voice::Job::Stage::Finished; });
            QCoreApplication::processEvents(); Check(!staleCallback);
        }
        std::cout << "CAPY_WINDOWS_VOICE_RUNTIME=PASS checks=" << checks << '\n';
        return 0;
    } catch (const std::exception&) {
        std::cerr << "CAPY_WINDOWS_VOICE_RUNTIME=FAIL\n"; return 1;
    }
}
