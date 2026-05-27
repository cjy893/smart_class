#pragma once
#include <string>
#include <atomic>
#include <memory>
#include <chrono>
#include "config.h"
#include "task_queue.h"
#include "inference_engine.h"
#include "mqtt_client.h"
#include "http_server.h"
#include "gpio_handler.h"
#include "mmf_pipeline.h"
#include "offline_cache.h"
#include "heartbeat.h"

// Main application orchestrator for the device side.
// Manages the lifecycle: init → connect → online → active/idle → degraded/offline.
enum class DeviceState {
    INIT,
    CONNECTING,
    ONLINE,
    ACTIVE,     // In a class session, person_count running
    IDLE,       // Connected but not in class time
    DEGRADED,   // Edge offline, local-only mode
    OFFLINE     // Network disconnected
};

class App {
public:
    App() = default;
    ~App();

    // Load config, init all modules. Returns false on failure.
    bool init(const std::string& config_path);

    // Run the main loop (blocks until shutdown).
    void run();

    // Signal shutdown.
    void shutdown();

private:
    DeviceConfig config_;
    std::atomic<DeviceState> state_{DeviceState::INIT};

    // Modules.
    std::unique_ptr<TaskQueue> task_queue_;
    std::unique_ptr<InferenceEngine> inference_;
    std::unique_ptr<MqttClient> mqtt_;
    std::unique_ptr<HttpServer> http_;
    std::unique_ptr<GpioHandler> gpio_;
    std::unique_ptr<MmfPipeline> mmf_;
    std::unique_ptr<OfflineCache> offline_cache_;
    std::unique_ptr<Heartbeat> heartbeat_;

    // Timers.
    std::chrono::steady_clock::time_point last_person_count_time_;
    std::chrono::steady_clock::time_point last_screenshot_time_;

    // Current state.
    std::string current_session_id_;
    std::string current_policy_ = "adaptive";
    std::string last_result_json_;
    std::vector<uint8_t> last_screenshot_jpeg_;
    int current_person_count_ = 0;
    bool force_local_mode_ = false;

    // Shutdown flag.
    std::atomic<bool> running_{false};

    // --- Initialization steps ---
    bool init_modules();
    bool connect_mqtt();
    void setup_mqtt_subscriptions();
    void setup_http_callbacks();
    void setup_gpio_callbacks();

    // --- MQTT message handlers ---
    void on_task_result(const std::string& topic, const std::string& payload);
    void on_schedule_command(const std::string& topic, const std::string& payload);

    // --- GPIO event handlers ---
    void on_gpio_event(GpioHandler::Event event);

    // --- Task management ---
    void trigger_person_count();
    void trigger_face_attendance();
    void trigger_behavior_analyze();
    void trigger_report_generate();
    void publish_task_request(TaskType type, TriggerSource source,
                              const std::string& image_base64 = "");
    std::string generate_task_id() const;

    // --- Periodic loops ---
    void person_count_loop();
    void screenshot_loop();

    // --- State management ---
    void set_state(DeviceState new_state);
    void on_online();
    void on_session_start(const std::string& session_id, const std::string& policy);
    void on_session_end();
    void on_edge_offline();
    void on_edge_online();
    void on_network_offline();
    void on_network_online();

    // --- Helper ---
    std::string iso8601_now() const;
    uint64_t unix_ms() const;

    // --- Frame capture ---
    bool capture_screenshot_jpeg(VIDEO_FRAME_INFO_S& frame);
};
