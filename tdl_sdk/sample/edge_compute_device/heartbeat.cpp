#include "heartbeat.h"
#include "mqtt_client.h"
#include <sstream>
#include <ctime>

// Minimal JSON builder without a full library dependency.
static std::string json_escape(const std::string& s) {
    std::string out;
    for (char c : s) {
        if (c == '"') out += "\\\"";
        else if (c == '\\') out += "\\\\";
        else out += c;
    }
    return out;
}

Heartbeat::~Heartbeat() { stop(); }

void Heartbeat::init(MqttClient* mqtt, const std::string& device_id, int interval_seconds) {
    mqtt_ = mqtt;
    device_id_ = device_id;
    interval_seconds_ = interval_seconds;
}

void Heartbeat::set_session_id(const std::string& session_id) {
    current_session_id_ = session_id;
}

void Heartbeat::set_policy(const std::string& policy) {
    current_policy_ = policy;
}

void Heartbeat::set_queue_depth(int depth) {
    queue_depth_ = depth;
}

void Heartbeat::add_bandwidth_bytes(uint64_t bytes) {
    bandwidth_bytes_ += bytes;
}

void Heartbeat::on_load_query(LoadCallback callback) {
    load_callback_ = std::move(callback);
}

void Heartbeat::start() {
    running_ = true;
    timer_thread_ = std::thread(&Heartbeat::timer_loop, this);
}

void Heartbeat::stop() {
    running_ = false;
    if (timer_thread_.joinable()) {
        timer_thread_.join();
    }
}

void Heartbeat::timer_loop() {
    while (running_) {
        std::this_thread::sleep_for(std::chrono::seconds(interval_seconds_));
        if (!running_) break;

        if (mqtt_ && mqtt_->is_connected()) {
            std::string topic = "edge/heartbeat/" + device_id_;
            std::string payload = build_heartbeat_json();
            mqtt_->publish(topic, payload, 0);  // QoS 0
        }
    }
}

std::string Heartbeat::build_heartbeat_json() {
    float cpu = 0, npu = 0;
    int memory_mb = 0;
    if (load_callback_) {
        load_callback_(cpu, npu, memory_mb);
    }

    auto now = std::chrono::system_clock::now();
    auto time_t_now = std::chrono::system_clock::to_time_t(now);
    char time_buf[32];
    strftime(time_buf, sizeof(time_buf), "%Y-%m-%dT%H:%M:%S", gmtime(&time_t_now));

    std::ostringstream oss;
    oss << "{"
        << "\"device_id\":\"" << json_escape(device_id_) << "\","
        << "\"timestamp\":\"" << time_buf << "\","
        << "\"status\":\"online\","
        << "\"load\":{"
        << "\"cpu_percent\":" << cpu << ","
        << "\"npu_percent\":" << npu << ","
        << "\"memory_mb\":" << memory_mb
        << "},"
        << "\"task_queue_depth\":" << queue_depth_ << ","
        << "\"bandwidth_bytes_sent\":" << bandwidth_bytes_ << ","
        << "\"current_session_id\":\"" << json_escape(current_session_id_) << "\","
        << "\"current_policy\":\"" << json_escape(current_policy_) << "\""
        << "}";
    return oss.str();
}
