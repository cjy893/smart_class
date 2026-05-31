#include "config.h"
#include <cstring>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <iostream>

// Minimal INI-style config parser. No external dependencies.
// Reads key=value pairs from a simple text file. Lines starting with # are comments.
// Falls back to hardcoded defaults if file doesn't exist or key is missing.

static std::string trim(const std::string& s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    size_t end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

static void parse_config_file(const std::string& path, std::map<std::string, std::string>& kv) {
    std::ifstream file(path);
    if (!file.is_open()) return;

    std::string line;
    while (std::getline(file, line)) {
        line = trim(line);
        if (line.empty() || line[0] == '#') continue;

        size_t eq = line.find('=');
        if (eq == std::string::npos) continue;

        std::string key = trim(line.substr(0, eq));
        std::string val = trim(line.substr(eq + 1));
        if (!key.empty()) kv[key] = val;
    }
}

static int get_int(const std::map<std::string, std::string>& kv,
                   const std::string& key, int default_val) {
    auto it = kv.find(key);
    if (it == kv.end()) return default_val;
    return std::atoi(it->second.c_str());
}

static float get_float(const std::map<std::string, std::string>& kv,
                       const std::string& key, float default_val) {
    auto it = kv.find(key);
    if (it == kv.end()) return default_val;
    return static_cast<float>(std::atof(it->second.c_str()));
}

static std::string get_str(const std::map<std::string, std::string>& kv,
                           const std::string& key, const std::string& default_val) {
    auto it = kv.find(key);
    if (it == kv.end()) return default_val;
    return it->second;
}

DeviceConfig load_config(const std::string& path) {
    DeviceConfig cfg;

    // Hardcoded defaults (embedded device — no yaml-cpp available).
    cfg.device_id = "classroom-301";
    cfg.mqtt.broker_host = "192.168.42.100";
    cfg.mqtt.broker_port = 1883;
    cfg.mqtt.keepalive_seconds = 10;
    cfg.person_count.interval_seconds = 2;
    cfg.web_server.port = 8080;
    cfg.camera.device = "/dev/video0";
    cfg.camera.width = 640;
    cfg.camera.height = 480;
    cfg.camera.screenshot_interval_seconds = 1;
    cfg.task.queue_depth = 1;
    cfg.task.debounce_ms = 500;
    cfg.task.long_press_ms = 2000;
    cfg.inference.model_path = "/mnt/cvimodel/yolov8n_det_coco80_640_640_INT8_cv181x.cvimodel";
    cfg.inference.threshold = 0.5f;
    cfg.inference.nms_threshold = 0.5f;
    cfg.heartbeat.interval_seconds = 5;
    cfg.offline.cache_path = "/tmp/offline_cache.jsonl";

    // Override from config file if present.
    std::map<std::string, std::string> kv;
    parse_config_file(path, kv);
    if (kv.empty()) {
        std::cout << "[Config] No config file found, using defaults. device_id="
                  << cfg.device_id << std::endl;
        return cfg;
    }

    cfg.device_id = get_str(kv, "device_id", cfg.device_id);
    cfg.mqtt.broker_host = get_str(kv, "mqtt_broker_host", cfg.mqtt.broker_host);
    cfg.mqtt.broker_port = get_int(kv, "mqtt_broker_port", cfg.mqtt.broker_port);
    cfg.mqtt.keepalive_seconds = get_int(kv, "mqtt_keepalive_seconds", cfg.mqtt.keepalive_seconds);
    cfg.mqtt.client_id = "milkv-" + cfg.device_id;
    cfg.person_count.interval_seconds = get_int(kv, "person_count_interval_seconds",
                                                 cfg.person_count.interval_seconds);
    cfg.web_server.port = get_int(kv, "web_server_port", cfg.web_server.port);
    cfg.camera.device = get_str(kv, "camera_device", cfg.camera.device);
    cfg.camera.width = get_int(kv, "camera_width", cfg.camera.width);
    cfg.camera.height = get_int(kv, "camera_height", cfg.camera.height);
    cfg.camera.screenshot_interval_seconds = get_int(kv, "camera_screenshot_interval_seconds",
                                                      cfg.camera.screenshot_interval_seconds);
    cfg.task.queue_depth = get_int(kv, "task_queue_depth", cfg.task.queue_depth);
    cfg.task.debounce_ms = get_int(kv, "task_debounce_ms", cfg.task.debounce_ms);
    cfg.task.long_press_ms = get_int(kv, "task_long_press_ms", cfg.task.long_press_ms);
    cfg.inference.model_path = get_str(kv, "inference_model_path", cfg.inference.model_path);
    cfg.inference.threshold = get_float(kv, "inference_threshold", cfg.inference.threshold);
    cfg.inference.nms_threshold = get_float(kv, "inference_nms_threshold", cfg.inference.nms_threshold);
    cfg.heartbeat.interval_seconds = get_int(kv, "heartbeat_interval_seconds",
                                              cfg.heartbeat.interval_seconds);
    cfg.offline.cache_path = get_str(kv, "offline_cache_path", cfg.offline.cache_path);

    std::cout << "[Config] Loaded, device_id=" << cfg.device_id << std::endl;
    return cfg;
}
