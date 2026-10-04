// SPDX-License-Identifier: MIT
#include "connection_worker.h"
#include <algorithm>
#include <limits>
#include <iterator>
#include <stdexcept>
#include <utility>

namespace Capy::Connection {

Worker::Result::~Result() {
    std::fill(std::begin(endpoint.secret), std::end(endpoint.secret), std::uint8_t(0));
}

Worker::Worker(Post post, Done done)
: _post(std::move(post)), _done(std::move(done)), _state(std::make_shared<State>()) {
    if (!_post || !_done) throw std::invalid_argument("Connection dispatcher missing");
    _thread = std::thread([this] { loop(); });
}

Worker::~Worker() {
    _state->alive.store(false);
    {
        const auto lock = std::lock_guard(_state->replyMutex);
        _state->reply.reset();
    }
    {
        const auto lock = std::lock_guard(_mutex);
        _stopping = true;
        _pending.reset();
    }
    _wake.notify_one();
    if (_thread.joinable()) _thread.join();
}

std::uint64_t Worker::request(bool enabled) {
    const auto lock = std::lock_guard(_mutex);
    if (_stopping || _state->revision.load() == std::numeric_limits<std::uint64_t>::max()) return 0;
    const auto revision = _state->revision.fetch_add(1) + 1;
    _pending = Command{ enabled, revision };
    _wake.notify_one();
    return revision;
}

CapyConnectionStatus Worker::status() const {
    auto result = CapyConnectionStatus{};
    capy_connection_status(_handle.load(), &result);
    return result;
}

void Worker::deliver(std::shared_ptr<Result> result) {
    const auto state = _state;
    const auto done = _done;
    {
        const auto lock = std::lock_guard(state->replyMutex);
        if (!state->alive.load() || state->revision.load() != result->revision) return;
        state->reply = std::move(result);
        if (state->dispatchQueued) return;
        state->dispatchQueued = true;
    }
    _post([state, done] {
        auto reply = std::shared_ptr<Result>();
        {
            const auto lock = std::lock_guard(state->replyMutex);
            reply = std::move(state->reply);
            state->dispatchQueued = false;
        }
        if (reply && state->alive.load() && state->revision.load() == reply->revision) done(reply);
    });
}

void Worker::loop() {
    while (true) {
        auto command = Command{};
        {
            auto lock = std::unique_lock(_mutex);
            _wake.wait(lock, [this] { return _stopping || _pending.has_value(); });
            if (_stopping) break;
            command = *_pending;
            _pending.reset();
        }
        const auto previous = _handle.exchange(0);
        if (previous) capy_connection_stop(previous);
        auto result = std::make_shared<Result>();
        result->revision = command.revision;
        if (command.enabled) {
            const auto handle = capy_connection_start(&result->endpoint);
            _handle.store(handle);
            result->code = handle ? Result::Code::Ready : Result::Code::Failed;
        } else {
            result->code = Result::Code::Stopped;
        }
        deliver(std::move(result));
    }
    const auto previous = _handle.exchange(0);
    if (previous) capy_connection_stop(previous);
}

} // namespace Capy::Connection
