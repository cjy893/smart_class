#include "task_queue.h"

TaskQueue::TaskQueue(int depth) : depth_(depth) {}

bool TaskQueue::push(const TaskRequest& task) {
    std::lock_guard<std::mutex> lock(mutex_);
    if ((int)queue_.size() >= depth_) {
        return false;
    }
    queue_.push(task);
    cv_.notify_one();
    return true;
}

bool TaskQueue::pop(TaskRequest& task) {
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait(lock, [this] { return !queue_.empty() || stopped_; });
    if (stopped_ && queue_.empty()) {
        return false;
    }
    task = queue_.front();
    queue_.pop();
    return true;
}

bool TaskQueue::empty() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.empty();
}

size_t TaskQueue::size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return queue_.size();
}

void TaskQueue::stop() {
    stopped_ = true;
    cv_.notify_all();
}
