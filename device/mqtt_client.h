#pragma once
#include <string>
#include <vector>
#include <functional>
#include <atomic>
#include <thread>
#include <mutex>

// Minimal MQTT 3.1.1 client using raw sockets (no paho dependency).
// Avoids musl libc thread compatibility issues with paho.mqtt.c on Milk-V.
class MqttClient {
public:
    using MessageCallback = std::function<void(const std::string& topic, const std::string& payload)>;

    MqttClient() = default;
    ~MqttClient();

    // Connect to broker, send MQTT CONNECT, wait for CONNACK.
    bool connect(const std::string& broker_host, int broker_port,
                 const std::string& client_id, const std::string& lwt_topic,
                 const std::string& lwt_payload, int keepalive_seconds);

    // Publish message to topic with given QoS (QoS 0 or 1 supported).
    bool publish(const std::string& topic, const std::string& payload, int qos = 0);

    // Subscribe to topic with callback. QoS 0 only for simplicity.
    bool subscribe(const std::string& topic, int qos, MessageCallback callback);

    // Start receive thread.
    void start_loop();
    void stop_loop();

    bool is_connected() const { return connected_; }
    void disconnect();

    void set_connected(bool val) { connected_ = val; }
    void stop_connect_loop() { stop_requested_ = true; }
    void handle_message(const std::string& topic, const std::string& payload);

    void set_default_callback(MessageCallback cb) { default_callback_ = std::move(cb); }

private:
    int send_packet(const unsigned char* data, size_t len);
    bool wait_for_connack(int timeout_ms);

    int sock_fd_ = -1;
    std::atomic<bool> connected_{false};
    std::atomic<bool> stop_requested_{false};
    std::thread recv_thread_;
    std::atomic<bool> recv_running_{false};
    std::mutex send_mutex_;

    // Keepalive
    int keepalive_sec_ = 10;
    std::chrono::steady_clock::time_point last_send_time_;

    // Subscription dispatch
    std::mutex callback_mutex_;
    std::vector<std::pair<std::string, MessageCallback>> subscriptions_;
    MessageCallback default_callback_;

    // MQTT packet helpers
    static void encode_remaining_length(unsigned char* buf, size_t& pos, uint32_t length);
    static void encode_string(unsigned char* buf, size_t& pos, const std::string& s);
    void recv_loop();
};
