// SPDX-License-Identifier: MIT
#include "connection_worker.h"
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <thread>

using Worker = Capy::Connection::Worker;
static int checks = 0;
static void check(bool value) {
    if (!value) { std::fputs("Connection worker assertion failed\n", stderr); std::exit(1); }
    ++checks;
}

struct UiQueue final {
    std::mutex mutex;
    std::deque<std::function<void()>> calls;
    std::size_t maximum = 0;
    void post(std::function<void()> call) {
        const auto lock = std::lock_guard(mutex);
        calls.push_back(std::move(call));
        maximum = std::max(maximum, calls.size());
    }
    bool hasQueued() {
        const auto lock = std::lock_guard(mutex);
        return !calls.empty();
    }
    void flush() {
        auto next = std::function<void()>();
        {
            const auto lock = std::lock_guard(mutex);
            if (calls.empty()) return;
            next = std::move(calls.front());
            calls.pop_front();
        }
        next();
    }
};

template <typename Predicate>
void waitFor(Predicate condition, UiQueue *queue = nullptr) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!condition()) {
        if (queue) queue->flush();
        if (std::chrono::steady_clock::now() >= deadline) check(false);
        std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
}

int main() {
    auto ui = UiQueue();
    auto delivered = std::shared_ptr<const Worker::Result>();
    auto count = 0;
    auto worker = std::make_unique<Worker>([&](auto call) { ui.post(std::move(call)); }, [&](auto result) {
        delivered = std::move(result);
        ++count;
    });
    const auto enabled = worker->request(true);
    check(enabled != 0);
    waitFor([&] { return delivered && delivered->revision == enabled; }, &ui);
    check(delivered->code == Worker::Result::Code::Ready);
    check(delivered->endpoint.abi_version == 1 && delivered->endpoint.port != 0);
    check(worker->status().running == 1);
    delivered.reset();

    const auto superseded = worker->request(true);
    waitFor([&] { return ui.hasQueued(); });
    const auto stopped = worker->request(false);
    check(stopped > superseded);
    waitFor([&] { return delivered && delivered->revision == stopped; }, &ui);
    check(delivered->code == Worker::Result::Code::Stopped);
    check(worker->status().running == 0);
    check(count == 2); // Superseded Ready callback must not become visible.
    delivered.reset();

    std::uint64_t latest = 0;
    for (int index = 0; index != 2000; ++index) latest = worker->request((index % 2) == 0);
    latest = worker->request(false);
    waitFor([&] { return delivered && delivered->revision == latest; }, &ui);
    check(delivered->code == Worker::Result::Code::Stopped);
    check(ui.maximum <= 1);
    check(count == 3);
    delivered.reset();

    worker->request(true);
    waitFor([&] { return ui.hasQueued(); });
    worker.reset(); // Joins the native transport and invalidates pending UI callbacks.
    ui.flush();
    check(count == 3);
    check(!delivered);
    std::printf("CAPY_CONNECTION_WORKER=PASS %d assertions; 2000 rapid requests; bounded UI queue\n", checks);
}
