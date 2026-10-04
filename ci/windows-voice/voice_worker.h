// SPDX-License-Identifier: MIT
#pragma once
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace Capy::Voice {
class Engine;
class Job final {
public:
    enum class Stage { Waiting, Model, Download, Decode, Recognize, Finished };
    void cancel();
    [[nodiscard]] int progress() const;
    [[nodiscard]] Stage stage() const { return _stage.load(); }
private:
    friend class Worker;
    std::atomic<bool> _cancel = false;
    std::atomic<Stage> _stage = Stage::Waiting;
    std::atomic<int> _downloadProgress = 0;
    mutable std::mutex _mutex;
    std::shared_ptr<Engine> _engine;
};
class Worker final {
public:
    using Post = std::function<void(std::function<void()>)>;
    struct Input {
        std::vector<std::uint8_t> bytes;
        std::string fileUtf8;
        std::int64_t expectedBytes = 0;
        std::string language = "auto";
        bool allowModelDownload = false;
    };
    struct Result {
        enum class Code { Ok, Cancelled, ModelRequired, Failed } code = Code::Failed;
        std::string text;
    };
    using Done = std::function<void(Result)>;
    Worker(std::string modelDirectoryUtf8, Post post);
    ~Worker();
    // Only one job is accepted at a time; no unbounded queue or detached threads.
    std::shared_ptr<Job> submit(Input input, Done done);
    Worker(const Worker&) = delete;
    Worker &operator=(const Worker&) = delete;
private:
    struct Task { Input input; Done done; std::shared_ptr<Job> job; };
    void loop();
    const std::string _directory;
    const Post _post;
    const std::shared_ptr<std::atomic<bool>> _alive;
    std::mutex _mutex;
    std::condition_variable _wake;
    std::optional<Task> _pending;
    std::shared_ptr<Job> _current;
    bool _stopping = false;
    std::thread _thread;
};
} // namespace Capy::Voice
