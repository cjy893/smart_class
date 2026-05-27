#pragma once
#include <string>
#include <vector>
#include <functional>
#include <atomic>
#include <thread>
#include <mutex>

// MQTT client wrapping paho.mqtt.c.
// Handles broker connection, pub/sub, LWT, QoS per topic.
class MqttClient {
public:
    using MessageCallback = std::function<void(const std::string& topic, const std::string& payload)>;

    MqttClient() = default;
    ~MqttClient();

    // Connect to broker and set LWT.
    bool connect(const std::string& broker_host, int broker_port,
                 const std::string& client_id, const std::string& lwt_topic,
                 const std::string& lwt_payload, int keepalive_seconds);

    // Publish message to topic with given QoS.
    bool publish(const std::string& topic, const std::string& payload, int qos = 0);

    // Subscribe to topic with callback.
    bool subscribe(const std::string& topic, int qos, MessageCallback callback);

    // Start MQTT network loop in background thread.
    void start_loop();
    void stop_loop();

    bool is_connected() const { return connected_; }
    void disconnect();

    // Called by static callbacks.
    void set_connected(bool val) { connected_ = val; }
    void handle_message(const std::string& topic, const std::string& payload);

    void set_default_callback(MessageCallback cb) { default_callback_ = std::move(cb); }

private:
    void* mqtt_client_ = nullptr;   // MQTTAsync client handle
    std::atomic<bool> connected_{false};
    std::thread loop_thread_;
    std::mutex callback_mutex_;
    std::vector<std::pair<std::string, MessageCallback>> subscriptions_;
    MessageCallback default_callback_;
};
