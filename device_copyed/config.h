#pragma once
#include <string>
#include <cstdint>
#include <map>

struct MqttConfig {
    std::string broker_host;
    int broker_port;
    int keepalive_seconds;
    std::string client_id;
};

struct PersonCountConfig {
    int interval_seconds;
};

struct WebServerConfig {
    int port;
};

struct CameraConfig {
    std::string device;
    int width;
    int height;
    int screenshot_interval_seconds;
};

struct TaskConfig {
    int queue_depth;
    int debounce_ms;
    int long_press_ms;
};

struct InferenceConfig {
    std::string model_path;
    float threshold;
    float nms_threshold;
};

struct HeartbeatConfig {
    int interval_seconds;
};

struct OfflineConfig {
    std::string cache_path;
};

struct DeviceConfig {
    std::string device_id;
    MqttConfig mqtt;
    PersonCountConfig person_count;
    WebServerConfig web_server;
    CameraConfig camera;
    TaskConfig task;
    InferenceConfig inference;
    HeartbeatConfig heartbeat;
    OfflineConfig offline;
};

DeviceConfig load_config(const std::string& path);
