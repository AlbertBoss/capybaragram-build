// SPDX-License-Identifier: MIT
#pragma once
#include "native_api.h"
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <thread>

namespace Capy::Connection {

class Worker final {
public:
    struct Result final {
        enum class Code { Ready, Stopped, Failed } code = Code::Failed;
        std::uint64_t revision = 0;
        CapyConnectionEndpoint endpoint{};
        ~Result();
    };
    using Post = std::function<void(std::function<void()>)>;
    using Done = std::function<void(std::shared_ptr<const Result>)>;
    Worker(Post post, Done done);
    ~Worker();
    // At most one pending command. Rapid changes replace the pending command.
    // Native startup/shutdown never runs on the UI thread.
    std::uint64_t request(bool enabled);
    [[nodiscard]] CapyConnectionStatus status() const;
    Worker(const Worker &) = delete;
    Worker &operator=(const Worker &) = delete;
private:
    struct State {
        std::atomic<bool> alive = true;
        std::atomic<std::uint64_t> revision = 0;
        std::mutex replyMutex;
        std::shared_ptr<Result> reply;
        bool dispatchQueued = false;
    };
    struct Command { bool enabled = false; std::uint64_t revision = 0; };
    void loop();
    void deliver(std::shared_ptr<Result> result);
    const Post _post;
    const Done _done;
    const std::shared_ptr<State> _state;
    std::atomic<std::uint64_t> _handle = 0;
    std::mutex _mutex;
    std::condition_variable _wake;
    std::optional<Command> _pending;
    bool _stopping = false;
    std::thread _thread;
};

} // namespace Capy::Connection
