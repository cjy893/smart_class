#pragma once
#include <string>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <atomic>

enum class TaskType {
    PERSON_COUNT,
    FACE_ATTENDANCE,
    BEHAVIOR_ANALYZE,
    REPORT_GENERATE
};

enum class TriggerSource {
    SYSTEM_TIMER,
    USER_BUTTON,
    DASHBOARD_MANUAL
};

struct TaskRequest {
    std::string task_id;
    TaskType task_type;
    TriggerSource trigger_source;
    std::string session_id;
    std::string device_id;
    std::string created_at;
    std::string image_base64;
    std::string params;
};

// FIFO task queue with fixed depth, thread-safe.
class TaskQueue {
public:
    explicit TaskQueue(int depth = 1);

    // Returns false if queue is full (caller should drop the task).
    bool push(const TaskRequest& task);

    // Blocks until a task is available. Returns false if queue is stopped.
    bool pop(TaskRequest& task);

    // Non-blocking check.
    bool empty() const;
    size_t size() const;

    // Wake up any blocked pop().
    void stop();

private:
    std::queue<TaskRequest> queue_;
    mutable std::mutex mutex_;
    std::condition_variable cv_;
    int depth_;
    std::atomic<bool> stopped_{false};
};
