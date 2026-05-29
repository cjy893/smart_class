#pragma once
#include <string>
#include <functional>
#include <atomic>
#include <thread>
#include <chrono>

class MqttClient;

// Sends heartbeat JSON every 5s via MQTT (QoS 0).
class Heartbeat {
public:
    using LoadCallback = std::function<void(float& cpu, float& npu, int& memory_mb)>;

    Heartbeat() = default;
    ~Heartbeat();

    void init(MqttClient* mqtt, const std::string& device_id, int interval_seconds);

    void set_session_id(const std::string& session_id);
    void set_policy(const std::string& policy);
    void set_queue_depth(int depth);
    void add_bandwidth_bytes(uint64_t bytes);
    void on_load_query(LoadCallback callback);

    void start();
    void stop();

private:
    MqttClient* mqtt_ = nullptr;
    std::string device_id_;
    int interval_seconds_ = 5;
    std::string current_session_id_;
    std::string current_policy_ = "adaptive";
    std::atomic<int> queue_depth_{0};
    std::atomic<uint64_t> bandwidth_bytes_{0};

    std::atomic<bool> running_{false};
    std::thread timer_thread_;
    LoadCallback load_callback_;

    void timer_loop();
    std::string build_heartbeat_json();
};
