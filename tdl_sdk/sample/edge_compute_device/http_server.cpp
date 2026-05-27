#include "http_server.h"
#include <iostream>
#include <sstream>
#include <cstring>

#include <microhttpd.h>

static std::string json_escape(const std::string& s) {
    std::string out;
    for (char c : s) {
        if (c == '"') out += "\\\"";
        else if (c == '\\') out += "\\\\";
        else if (c == '\n') out += "\\n";
        else out += c;
    }
    return out;
}

HttpServer::~HttpServer() { stop(); }

bool HttpServer::start(int port) {
    daemon_ = MHD_start_daemon(
        MHD_USE_THREAD_PER_CONNECTION,
        port,
        nullptr, nullptr,
        &HttpServer::request_handler, this,
        MHD_OPTION_END);
    if (!daemon_) {
        std::cerr << "[HttpServer] MHD_start_daemon failed on port " << port << std::endl;
        return false;
    }
    running_ = true;
    std::cout << "[HttpServer] Started on port " << port << std::endl;
    return true;
}

void HttpServer::stop() {
    running_ = false;
    if (daemon_) {
        MHD_stop_daemon(static_cast<struct MHD_Daemon*>(daemon_));
        daemon_ = nullptr;
    }
}

void HttpServer::set_person_count(int count) {
    std::lock_guard<std::mutex> lock(mutex_);
    person_count_ = count;
}
void HttpServer::set_policy(const std::string& policy) {
    std::lock_guard<std::mutex> lock(mutex_);
    policy_ = policy;
}
void HttpServer::set_network_status(const std::string& status) {
    std::lock_guard<std::mutex> lock(mutex_);
    network_status_ = status;
}
void HttpServer::set_session_id(const std::string& id) {
    std::lock_guard<std::mutex> lock(mutex_);
    session_id_ = id;
}
void HttpServer::set_last_result(const std::string& json) {
    std::lock_guard<std::mutex> lock(mutex_);
    last_result_json_ = json;
}
void HttpServer::set_screenshot(const std::vector<uint8_t>& jpeg) {
    std::lock_guard<std::mutex> lock(mutex_);
    screenshot_jpeg_ = jpeg;
}
void HttpServer::set_error_message(const std::string& msg) {
    std::lock_guard<std::mutex> lock(mutex_);
    error_message_ = msg;
}

void HttpServer::on_action(ActionCallback callback) {
    action_callback_ = std::move(callback);
}
void HttpServer::on_policy_change(std::function<void(const std::string&)> callback) {
    policy_callback_ = std::move(callback);
}

std::string HttpServer::build_status_json() const {
    std::lock_guard<std::mutex> lock(mutex_);
    std::ostringstream oss;
    oss << "{"
        << "\"person_count\":" << person_count_ << ","
        << "\"policy\":\"" << json_escape(policy_) << "\","
        << "\"network_status\":\"" << json_escape(network_status_) << "\","
        << "\"session_id\":\"" << json_escape(session_id_) << "\","
        << "\"error\":\"" << json_escape(error_message_) << "\""
        << "}";
    return oss.str();
}

std::string HttpServer::build_last_result_json() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return last_result_json_.empty() ? "{}" : last_result_json_;
}

MHD_Result HttpServer::request_handler(void* cls, struct MHD_Connection* connection,
                                        const char* url, const char* method,
                                        const char* version, const char* upload_data,
                                        size_t* upload_data_size, void** ptr) {
    (void)version;
    auto* self = static_cast<HttpServer*>(cls);
    std::string response;
    int status_code = MHD_HTTP_OK;

    if (strcmp(method, "GET") == 0) {
        status_code = self->handle_get(url, response);
    } else if (strcmp(method, "POST") == 0) {
        // Accumulate upload data for POST requests.
        if (*ptr == nullptr) {
            *ptr = new std::string();
            *upload_data_size = 0;
            return MHD_YES;
        }
        auto* body = static_cast<std::string*>(*ptr);
        if (*upload_data_size > 0) {
            body->append(upload_data, *upload_data_size);
            *upload_data_size = 0;
            return MHD_YES;
        }
        status_code = self->handle_post(url, body->c_str(), body->size(), response);
        delete static_cast<std::string*>(*ptr);
        *ptr = nullptr;
    } else {
        status_code = MHD_HTTP_METHOD_NOT_ALLOWED;
        response = "Method Not Allowed";
    }

    auto* mhd_response = MHD_create_response_from_buffer(
        response.size(), const_cast<char*>(response.c_str()), MHD_RESPMEM_MUST_COPY);
    MHD_add_response_header(mhd_response, "Content-Type", "application/json; charset=utf-8");
    MHD_add_response_header(mhd_response, "Access-Control-Allow-Origin", "*");
    MHD_Result ret = MHD_queue_response(static_cast<struct MHD_Connection*>(connection), status_code, mhd_response);
    MHD_destroy_response(mhd_response);
    return ret;
}

int HttpServer::handle_get(const char* url, std::string& response) {
    std::string path(url);

    if (path == "/" || path == "/index.html") {
        // Served as static file by MHD, handled separately.
        response = "text/html placeholder";
        return MHD_HTTP_OK;
    }
    if (path == "/api/status") {
        response = build_status_json();
        return MHD_HTTP_OK;
    }
    if (path == "/api/last_result") {
        response = build_last_result_json();
        return MHD_HTTP_OK;
    }
    if (path == "/api/screenshot") {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!screenshot_jpeg_.empty()) {
            response.assign(reinterpret_cast<const char*>(screenshot_jpeg_.data()),
                            screenshot_jpeg_.size());
            return MHD_HTTP_OK;
        }
        response = "";
        return MHD_HTTP_NO_CONTENT;
    }

    response = "{\"error\":\"not found\"}";
    return MHD_HTTP_NOT_FOUND;
}

int HttpServer::handle_post(const char* url, const char* upload_data, size_t upload_size,
                             std::string& response) {
    (void)upload_data;
    (void)upload_size;
    std::string path(url);

    if (path == "/api/action/attendance") {
        if (action_callback_) action_callback_("attendance");
        response = "{\"status\":\"ok\"}";
        return MHD_HTTP_OK;
    }
    if (path == "/api/action/behavior") {
        if (action_callback_) action_callback_("behavior");
        response = "{\"status\":\"ok\"}";
        return MHD_HTTP_OK;
    }
    if (path == "/api/action/report") {
        if (action_callback_) action_callback_("report");
        response = "{\"status\":\"ok\"}";
        return MHD_HTTP_OK;
    }
    // /api/action/policy/{name}
    if (path.find("/api/action/policy/") == 0) {
        std::string policy = path.substr(21);
        if (policy_callback_) policy_callback_(policy);
        response = "{\"status\":\"ok\"}";
        return MHD_HTTP_OK;
    }

    response = "{\"error\":\"not found\"}";
    return MHD_HTTP_NOT_FOUND;
}

