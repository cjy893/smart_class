#pragma once
#include <string>
#include <vector>
#include <functional>
#include <microhttpd.h>
#include <atomic>
#include <thread>
#include <mutex>
#include <unordered_map>

// Minimal HTTP server (libmicrohttpd) for device-side Web UI.
// Serves: GET / (index.html), /api/status, /api/last_result, /api/screenshot
//         POST /api/action/attendance, /api/action/behavior, /api/action/report, /api/action/policy/{name}
class HttpServer {
public:
    using ActionCallback = std::function<void(const std::string& action)>;

    HttpServer() = default;
    ~HttpServer();

    bool start(int port);

    void stop();

    // Data setters — called from main thread to update in-memory state.
    void set_person_count(int count);
    void set_policy(const std::string& policy);
    void set_network_status(const std::string& status);  // "online" | "edge_offline" | "cloud_offline"
    void set_session_id(const std::string& session_id);
    void set_last_result(const std::string& json);
    void set_screenshot(const std::vector<uint8_t>& jpeg_data);
    void set_error_message(const std::string& msg);

    // Register action callbacks.
    void on_action(ActionCallback callback);
    void on_policy_change(std::function<void(const std::string&)> callback);

    std::string build_status_json() const;
    std::string build_last_result_json() const;

private:
    void* daemon_ = nullptr;  // MHD_Daemon
    std::atomic<bool> running_{false};
    std::thread server_thread_;

    // In-memory state (protected by mutex_).
    mutable std::mutex mutex_;
    int person_count_ = 0;
    std::string policy_ = "adaptive";
    std::string network_status_ = "online";
    std::string session_id_;
    std::string last_result_json_;
    std::vector<uint8_t> screenshot_jpeg_;
    std::string error_message_;

    ActionCallback action_callback_;
    std::function<void(const std::string&)> policy_callback_;

    static MHD_Result request_handler(void* cls, struct MHD_Connection* connection, const char* url,
                                       const char* method, const char* version,
                                       const char* upload_data, size_t* upload_data_size,
                                       void** ptr);
    int handle_get(const char* url, std::string& response);
    int handle_post(const char* url, const char* upload_data, size_t upload_size, std::string& response);
};
