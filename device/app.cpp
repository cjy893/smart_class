#include "app.h"
#include <iostream>
#include <sstream>
#include <random>
#include <ctime>
#include <algorithm>
#include <iomanip>
#include <cstring>

App::~App() { shutdown(); }

// --- Initialization ---

bool App::init(const std::string& config_path) {
    config_ = load_config(config_path);
    std::cout << "[App] Config loaded, device_id=" << config_.device_id << std::endl;

    if (!init_modules()) {
        std::cerr << "[App] Module init failed" << std::endl;
        return false;
    }

    setup_http_callbacks();
    setup_gpio_callbacks();

    if (connect_mqtt()) {
        setup_mqtt_subscriptions();
        publish_online();
        set_state(DeviceState::ONLINE);
    } else {
        set_state(DeviceState::OFFLINE);
        std::cout << "[App] MQTT unavailable, starting in offline mode" << std::endl;
    }

    // Start background services (HTTP always starts regardless of MQTT state).
    heartbeat_->start();
    http_->start(config_.web_server.port);

    running_ = true;
    last_reconnect_attempt_ = std::chrono::steady_clock::now();
    std::cout << "[App] Initialization complete, entering main loop" << std::endl;
    return true;
}

bool App::init_modules() {
    task_queue_ = std::unique_ptr<TaskQueue>(new TaskQueue(config_.task.queue_depth));

    // 1. Init MMF pipeline first (VI + ISP + VPSS) — must be before TDL.
    mmf_ = std::unique_ptr<MmfPipeline>(new MmfPipeline());
    if (!mmf_->init(768, 432, 1280, 720)) {
        std::cerr << "[App] MmfPipeline init failed" << std::endl;
        return false;
    }

    // 2. Init inference engine (binds to VPSS VBPool 2).
    inference_ = std::unique_ptr<InferenceEngine>(new InferenceEngine());
    if (!inference_->init(config_.inference.model_path,
                           config_.inference.threshold,
                           config_.inference.nms_threshold,
                           mmf_->grp_id(), 2)) {
        std::cerr << "[App] InferenceEngine init failed" << std::endl;
        return false;
    }

    mqtt_ = std::unique_ptr<MqttClient>(new MqttClient());
    http_ = std::unique_ptr<HttpServer>(new HttpServer());
    gpio_ = std::unique_ptr<GpioHandler>(new GpioHandler());
    offline_cache_ = std::unique_ptr<OfflineCache>(new OfflineCache());
    heartbeat_ = std::unique_ptr<Heartbeat>(new Heartbeat());

    gpio_->init(config_.task.debounce_ms, config_.task.long_press_ms);
    offline_cache_->init(config_.offline.cache_path);

    heartbeat_->init(mqtt_.get(), config_.device_id, config_.heartbeat.interval_seconds);
    heartbeat_->on_load_query([this](float& cpu, float& npu, int& memory_mb) {
        cpu = 45.0f; npu = 30.0f; memory_mb = 128;
    });

    return true;
}

bool App::connect_mqtt() {
    std::string lwt_topic = "edge/device/offline/" + config_.device_id;
    uint64_t now_ms = unix_ms();
    std::ostringstream lwt_oss;
    lwt_oss << "{\"device_id\":\"" << config_.device_id << "\","
            << "\"timestamp\":" << now_ms << ","
            << "\"status\":\"offline\"}";
    std::string lwt_payload = lwt_oss.str();

    set_state(DeviceState::CONNECTING);
    return mqtt_->connect(config_.mqtt.broker_host, config_.mqtt.broker_port,
                          config_.mqtt.client_id, lwt_topic, lwt_payload,
                          config_.mqtt.keepalive_seconds);
}

void App::publish_online() {
    uint64_t now_ms = unix_ms();
    std::ostringstream oss;
    oss << "{\"device_id\":\"" << config_.device_id << "\","
        << "\"timestamp\":" << now_ms << ","
        << "\"status\":\"online\"}";
    mqtt_->publish("edge/device/online/" + config_.device_id, oss.str(), 1);
}

void App::setup_mqtt_subscriptions() {
    mqtt_->subscribe("edge/task/result/" + config_.device_id, 1,
        [this](const std::string& topic, const std::string& payload) {
            on_task_result(topic, payload);
        });
    mqtt_->subscribe("cloud/task/result/" + config_.device_id, 1,
        [this](const std::string& topic, const std::string& payload) {
            on_task_result(topic, payload);
        });
    mqtt_->subscribe("edge/schedule/command/" + config_.device_id, 1,
        [this](const std::string& topic, const std::string& payload) {
            on_schedule_command(topic, payload);
        });
}

void App::setup_http_callbacks() {
    http_->on_action([this](const std::string& action) {
        if (action == "attendance") trigger_face_attendance();
        else if (action == "behavior") trigger_behavior_analyze();
        else if (action == "report") trigger_report_generate();
    });
    http_->on_policy_change([this](const std::string& policy) {
        current_policy_ = policy;
        heartbeat_->set_policy(policy);
        http_->set_policy(policy);
    });
}

void App::setup_gpio_callbacks() {
    gpio_->on_event([this](GpioHandler::Event event) { on_gpio_event(event); });
}

// --- Main Loop ---

void App::run() {
    last_person_count_time_ = std::chrono::steady_clock::now();
    last_screenshot_time_ = std::chrono::steady_clock::now();

    while (running_) {
        auto now = std::chrono::steady_clock::now();

        // Person count loop (only during active session).
        if (state_ == DeviceState::ACTIVE) {
            auto elapsed_pc = std::chrono::duration_cast<std::chrono::seconds>(
                now - last_person_count_time_).count();
            if (elapsed_pc >= config_.person_count.interval_seconds) {
                person_count_loop();
                last_person_count_time_ = now;
            }
        }

        // Screenshot loop.
        if (state_ == DeviceState::ACTIVE || state_ == DeviceState::IDLE ||
            state_ == DeviceState::DEGRADED) {
            auto elapsed_ss = std::chrono::duration_cast<std::chrono::seconds>(
                now - last_screenshot_time_).count();
            if (elapsed_ss >= config_.camera.screenshot_interval_seconds) {
                screenshot_loop();
                last_screenshot_time_ = now;
            }
        }

        // Connection monitoring: detect loss → go offline.
        if (!mqtt_->is_connected() && state_ != DeviceState::OFFLINE &&
            state_ != DeviceState::CONNECTING) {
            on_network_offline();
        }

        // Background reconnection: when offline, periodically retry (non-blocking).
        if (state_ == DeviceState::OFFLINE || state_ == DeviceState::CONNECTING) {
            auto elapsed_reconn = std::chrono::duration_cast<std::chrono::seconds>(
                now - last_reconnect_attempt_).count();
            if (!mqtt_->is_connected() && elapsed_reconn >= reconnect_interval_sec_) {
                std::cout << "[App] Attempting MQTT reconnection..." << std::endl;
                last_reconnect_attempt_ = now;
                if (connect_mqtt()) {
                    setup_mqtt_subscriptions();
                    std::cout << "[App] Reconnection successful" << std::endl;
                    on_network_online();
                } else {
                    std::cout << "[App] Reconnection failed, will retry in "
                              << reconnect_interval_sec_ << "s" << std::endl;
                    if (state_ == DeviceState::CONNECTING) {
                        set_state(DeviceState::OFFLINE);
                    }
                }
            }
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
}

void App::shutdown() {
    running_ = false;
    if (heartbeat_) heartbeat_->stop();
    if (http_) http_->stop();
    if (gpio_) gpio_->stop();
    if (mqtt_) mqtt_->disconnect();
    // MMF deinit via MmfPipeline destructor.
}

// --- Frame capture helper ---

bool App::capture_screenshot_jpeg(VIDEO_FRAME_INFO_S& frame) {
    // Get a frame and encode a small JPEG from the center region.
    // For simplicity, store raw dimensions — full JPEG encoding
    // requires IVE or software encoder. In v1, we send frame metadata.
    last_screenshot_jpeg_.clear();

    // Store frame metadata as placeholder screenshot.
    std::ostringstream oss;
    oss << "{\"width\":" << frame.stVFrame.u32Width
        << ",\"height\":" << frame.stVFrame.u32Height << "}";
    std::string meta = oss.str();
    last_screenshot_jpeg_.assign(meta.begin(), meta.end());
    return true;
}

// --- MQTT Handlers ---

void App::on_task_result(const std::string& topic, const std::string& payload) {
    last_result_json_ = payload;
    http_->set_last_result(payload);
}

void App::on_schedule_command(const std::string& topic, const std::string& payload) {
    if (payload.find("\"session_restore\"") != std::string::npos) {
        size_t sid_pos = payload.find("\"session_id\"");
        if (sid_pos != std::string::npos) {
            size_t val_start = payload.find('"', sid_pos + 13) + 1;
            size_t val_end = payload.find('"', val_start);
            std::string session_id = payload.substr(val_start, val_end - val_start);

            std::string policy = "adaptive";
            size_t pol_pos = payload.find("\"policy\"");
            if (pol_pos != std::string::npos) {
                size_t p_start = payload.find('"', pol_pos + 9) + 1;
                size_t p_end = payload.find('"', p_start);
                policy = payload.substr(p_start, p_end - p_start);
            }
            on_session_start(session_id, policy);
        }
    }
    if (payload.find("\"policy_change\"") != std::string::npos) {
        size_t pol_pos = payload.find("\"policy\"");
        if (pol_pos != std::string::npos) {
            size_t p_start = payload.find('"', pol_pos + 9) + 1;
            size_t p_end = payload.find('"', p_start);
            current_policy_ = payload.substr(p_start, p_end - p_start);
            heartbeat_->set_policy(current_policy_);
            http_->set_policy(current_policy_);
        }
    }
}

// --- GPIO Event Handlers ---

void App::on_gpio_event(GpioHandler::Event event) {
    switch (event) {
        case GpioHandler::Event::BTN_1_SHORT:
            if (current_policy_ == "greedy_nearby") current_policy_ = "load_balance";
            else if (current_policy_ == "load_balance") current_policy_ = "adaptive";
            else current_policy_ = "greedy_nearby";
            heartbeat_->set_policy(current_policy_);
            http_->set_policy(current_policy_);
            break;

        case GpioHandler::Event::BTN_1_LONG:
            force_local_mode_ = true;
            set_state(DeviceState::DEGRADED);
            while (!task_queue_->empty()) { TaskRequest dummy; task_queue_->pop(dummy); }
            http_->set_error_message("已切换为纯本地模式");
            break;

        case GpioHandler::Event::BTN_2_SHORT:
            trigger_face_attendance();
            break;

        case GpioHandler::Event::BTN_2_LONG:
            trigger_behavior_analyze();
            break;

        case GpioHandler::Event::BTN_3_SHORT:
            trigger_report_generate();
            break;
    }
}

// --- Task Triggers ---

void App::trigger_person_count() {
    if (!inference_->is_initialized() || !mmf_->is_initialized()) return;

    VIDEO_FRAME_INFO_S frame;
    memset(&frame, 0, sizeof(frame));

    if (!mmf_->get_frame(frame, 2000)) return;

    double latency_ms = 0;
    int count = inference_->detect_persons(&frame,
        [&latency_ms](int c, double l) { (void)c; latency_ms = l; });

    mmf_->release_frame(frame);

    if (count < 0) return;  // Inference error.

    current_person_count_ = count;
    http_->set_person_count(count);

    std::string task_id = generate_task_id();
    std::ostringstream oss;
    oss << "{"
        << "\"task_id\":\"" << task_id << "\","
        << "\"task_type\":\"person_count\","
        << "\"status\":\"COMPLETED\","
        << "\"result\":{\"count\":" << count << ",\"timestamp\":\"" << iso8601_now() << "\"},"
        << "\"metrics\":{\"inference_latency_ms\":" << latency_ms << "}"
        << "}";
    std::string task_json = oss.str();

    if (mqtt_->is_connected()) {
        mqtt_->publish("edge/status/person_count/" + config_.device_id, task_json, 0);
        heartbeat_->add_bandwidth_bytes(static_cast<uint64_t>(task_json.size()));
    } else {
        offline_cache_->append(task_json);
    }
}

void App::trigger_face_attendance() {
    if (state_ == DeviceState::OFFLINE) {
        http_->set_error_message("当前离线，无法执行此操作");
        return;
    }

    TaskRequest req;
    req.task_id = generate_task_id();
    req.task_type = TaskType::FACE_ATTENDANCE;
    req.trigger_source = TriggerSource::USER_BUTTON;
    req.session_id = current_session_id_;
    req.device_id = config_.device_id;
    req.created_at = iso8601_now();

    // Capture a frame from MMF for the task image.
    VIDEO_FRAME_INFO_S frame;
    memset(&frame, 0, sizeof(frame));
    if (mmf_->get_frame(frame, 2000)) {
        // Encode frame metadata as base64 placeholder (real encoding needs IVE).
        std::ostringstream meta;
        meta << "{\"w\":" << frame.stVFrame.u32Width
             << ",\"h\":" << frame.stVFrame.u32Height << "}";
        req.image_base64 = meta.str();
        mmf_->release_frame(frame);
    }

    if (!task_queue_->push(req)) {
        http_->set_error_message("任务进行中，请稍后再试");
        return;
    }

    TaskRequest queued;
    if (task_queue_->pop(queued)) {
        publish_task_request(queued.task_type, queued.trigger_source, queued.image_base64);
    }
}

void App::trigger_behavior_analyze() {
    if (state_ == DeviceState::OFFLINE) {
        http_->set_error_message("当前离线，无法执行此操作");
        return;
    }

    TaskRequest req;
    req.task_id = generate_task_id();
    req.task_type = TaskType::BEHAVIOR_ANALYZE;
    req.trigger_source = TriggerSource::USER_BUTTON;
    req.session_id = current_session_id_;
    req.device_id = config_.device_id;
    req.created_at = iso8601_now();

    VIDEO_FRAME_INFO_S frame;
    memset(&frame, 0, sizeof(frame));
    if (mmf_->get_frame(frame, 2000)) {
        std::ostringstream meta;
        meta << "{\"w\":" << frame.stVFrame.u32Width
             << ",\"h\":" << frame.stVFrame.u32Height << "}";
        req.image_base64 = meta.str();
        mmf_->release_frame(frame);
    }

    if (!task_queue_->push(req)) {
        http_->set_error_message("任务进行中，请稍后再试");
        return;
    }

    TaskRequest queued;
    if (task_queue_->pop(queued)) {
        publish_task_request(queued.task_type, queued.trigger_source, queued.image_base64);
    }
}

void App::trigger_report_generate() {
    if (state_ == DeviceState::OFFLINE) {
        http_->set_error_message("当前离线，无法执行此操作");
        return;
    }
    publish_task_request(TaskType::REPORT_GENERATE, TriggerSource::USER_BUTTON);
}

void App::publish_task_request(TaskType type, TriggerSource source,
                                const std::string& image_base64) {
    if (!mqtt_->is_connected()) return;

    std::string type_str;
    switch (type) {
        case TaskType::FACE_ATTENDANCE: type_str = "face_attendance"; break;
        case TaskType::BEHAVIOR_ANALYZE: type_str = "behavior_analyze"; break;
        case TaskType::REPORT_GENERATE: type_str = "report_generate"; break;
        default: return;
    }

    std::ostringstream oss;
    oss << "{"
        << "\"task_id\":\"" << generate_task_id() << "\","
        << "\"task_type\":\"" << type_str << "\","
        << "\"trigger_source\":\""
        << (source == TriggerSource::USER_BUTTON ? "user_button" : "system_timer") << "\","
        << "\"session_id\":\"" << current_session_id_ << "\","
        << "\"device_id\":\"" << config_.device_id << "\","
        << "\"created_at\":\"" << iso8601_now() << "\","
        << "\"image\":\"" << image_base64 << "\","
        << "\"params\":{}"
        << "}";

    std::string payload = oss.str();
    mqtt_->publish("edge/task/request/" + config_.device_id, payload, 1);
    heartbeat_->add_bandwidth_bytes(static_cast<uint64_t>(payload.size()));
    heartbeat_->set_queue_depth(static_cast<int>(task_queue_->size()));
}

std::string App::generate_task_id() const {
    auto now = unix_ms();
    static thread_local std::mt19937_64 rng(std::random_device{}());
    uint64_t suffix = rng();
    std::ostringstream oss;
    oss << std::hex << config_.device_id << "-" << now << "-" << suffix;
    return oss.str();
}

// --- Periodic Loops ---

void App::person_count_loop() {
    if (!task_queue_->empty()) return;  // Drop frame, prioritize user task.
    trigger_person_count();
    if (!task_queue_->empty()) {
        TaskRequest req;
        if (task_queue_->pop(req)) {
            publish_task_request(req.task_type, req.trigger_source, req.image_base64);
        }
    }
}

void App::screenshot_loop() {
    VIDEO_FRAME_INFO_S frame;
    memset(&frame, 0, sizeof(frame));
    if (mmf_->get_frame(frame, 2000)) {
        capture_screenshot_jpeg(frame);
        http_->set_screenshot(last_screenshot_jpeg_);
        mmf_->release_frame(frame);
    }
}

// --- State Management ---

void App::set_state(DeviceState new_state) {
    DeviceState old = state_.exchange(new_state);
    if (old == new_state) return;
    const char* names[] = {"INIT","CONNECTING","ONLINE","ACTIVE","IDLE","DEGRADED","OFFLINE"};
    std::cout << "[App] State: " << names[static_cast<int>(old)]
              << " -> " << names[static_cast<int>(new_state)] << std::endl;
}

void App::on_online() {
    set_state(DeviceState::ONLINE);
    http_->set_network_status("online");
    http_->set_error_message("");
}

void App::on_session_start(const std::string& session_id, const std::string& policy) {
    current_session_id_ = session_id;
    current_policy_ = policy;
    force_local_mode_ = false;
    set_state(DeviceState::ACTIVE);
    heartbeat_->set_session_id(session_id);
    heartbeat_->set_policy(policy);
    http_->set_session_id(session_id);
    http_->set_policy(policy);
    http_->set_network_status("online");
    http_->set_error_message("");
}

void App::on_session_end() {
    current_session_id_.clear();
    set_state(DeviceState::IDLE);
    heartbeat_->set_session_id("");
    http_->set_session_id("");
    http_->set_person_count(0);
    http_->set_error_message("");
}

void App::on_edge_offline() {
    set_state(DeviceState::DEGRADED);
    http_->set_network_status("edge_offline");
    http_->set_error_message("本地服务器不可用，请联系管理员检查本地服务器");
}

void App::on_edge_online() {
    if (!force_local_mode_) {
        set_state(current_session_id_.empty() ? DeviceState::IDLE : DeviceState::ACTIVE);
    }
    http_->set_network_status("online");
    http_->set_error_message("");
}

void App::on_network_offline() {
    set_state(DeviceState::OFFLINE);
    http_->set_network_status("offline");
    http_->set_error_message("网络连接已断开");
}

void App::on_network_online() {
    auto records = offline_cache_->read_all();
    for (const auto& rec : records) {
        mqtt_->publish("edge/status/person_count/" + config_.device_id, rec, 0);
        heartbeat_->add_bandwidth_bytes(static_cast<uint64_t>(rec.size()));
    }
    offline_cache_->clear();

    uint64_t now_ms = unix_ms();
    std::ostringstream oss;
    oss << "{\"device_id\":\"" << config_.device_id << "\","
        << "\"timestamp\":" << now_ms << ","
        << "\"status\":\"online\"}";
    mqtt_->publish("edge/device/online/" + config_.device_id, oss.str(), 1);

    on_online();
}

// --- Helpers ---

std::string App::iso8601_now() const {
    auto now = std::chrono::system_clock::now();
    auto t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()) % 1000;
    char buf[32];
    strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", gmtime(&t));
    std::ostringstream oss;
    oss << buf << "." << std::setfill('0') << std::setw(3) << ms.count();
    return oss.str();
}

uint64_t App::unix_ms() const {
    return static_cast<uint64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count());
}
