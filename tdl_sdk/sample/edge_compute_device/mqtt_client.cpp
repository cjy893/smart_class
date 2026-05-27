#include "mqtt_client.h"
#include <iostream>
#include <cstring>
#include <MQTTAsync.h>

// paho.mqtt.c callback signatures (API version 1.2.x / 1.3.x compatible).

static int on_message_arrived(void* context, char* topic_name, int topic_len,
                               MQTTAsync_message* mqtt_msg) {
    auto* self = static_cast<MqttClient*>(context);
    std::string topic(topic_name, topic_len);
    std::string payload(static_cast<char*>(mqtt_msg->payload),
                        static_cast<char*>(mqtt_msg->payload) + mqtt_msg->payloadlen);
    self->handle_message(topic, payload);
    MQTTAsync_freeMessage(&mqtt_msg);
    MQTTAsync_free(topic_name);
    return 1;
}

static void on_connection_lost(void* context, char* cause) {
    auto* self = static_cast<MqttClient*>(context);
    std::cerr << "[MqttClient] Connection lost: " << (cause ? cause : "unknown") << std::endl;
    self->set_connected(false);
}

static void on_delivery_complete(void* context, MQTTAsync_token token) {
    (void)context;
    (void)token;
}

// ---- Public API ----

MqttClient::~MqttClient() { disconnect(); }

bool MqttClient::connect(const std::string& broker_host, int broker_port,
                          const std::string& client_id, const std::string& lwt_topic,
                          const std::string& lwt_payload, int keepalive_seconds) {
    std::string broker_url = "tcp://" + broker_host + ":" + std::to_string(broker_port);

    MQTTAsync client;
    int rc = MQTTAsync_create(&client, broker_url.c_str(), client_id.c_str(),
                               MQTTCLIENT_PERSISTENCE_NONE, NULL);
    if (rc != MQTTASYNC_SUCCESS) {
        std::cerr << "[MqttClient] MQTTAsync_create failed: " << rc << std::endl;
        return false;
    }
    mqtt_client_ = client;

    rc = MQTTAsync_setCallbacks(client, this, on_connection_lost, on_message_arrived,
                                 on_delivery_complete);
    if (rc != MQTTASYNC_SUCCESS) {
        std::cerr << "[MqttClient] setCallbacks failed: " << rc << std::endl;
    }

    MQTTAsync_connectOptions opts = MQTTAsync_connectOptions_initializer;
    opts.keepAliveInterval = keepalive_seconds;
    opts.cleansession = 0;
    opts.context = this;

    // LWT — API version where will.message is const char* (not a struct).
    MQTTAsync_willOptions will = MQTTAsync_willOptions_initializer;
    will.topicName = lwt_topic.c_str();
    will.message = lwt_payload.c_str();
    will.qos = 1;
    will.retained = 1;
    opts.will = &will;

    rc = MQTTAsync_connect(client, &opts);
    if (rc != MQTTASYNC_SUCCESS) {
        std::cerr << "[MqttClient] MQTTAsync_connect failed: " << rc << std::endl;
        MQTTAsync_destroy(&client);
        mqtt_client_ = NULL;
        return false;
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    connected_ = (MQTTAsync_isConnected(client) != 0);
    if (connected_) {
        std::cout << "[MqttClient] Connected to " << broker_url << std::endl;
    }
    return connected_;
}

bool MqttClient::publish(const std::string& topic, const std::string& payload, int qos) {
    if (!mqtt_client_ || !connected_) return false;
    MQTTAsync client = static_cast<MQTTAsync>(mqtt_client_);

    MQTTAsync_message msg = MQTTAsync_message_initializer;
    msg.payload = const_cast<char*>(payload.c_str());
    msg.payloadlen = static_cast<int>(payload.size());
    msg.qos = qos;
    msg.retained = 0;

    MQTTAsync_responseOptions opts = MQTTAsync_responseOptions_initializer;
    int rc = MQTTAsync_sendMessage(client, topic.c_str(), &msg, &opts);
    return rc == MQTTASYNC_SUCCESS;
}

bool MqttClient::subscribe(const std::string& topic, int qos, MessageCallback callback) {
    if (!mqtt_client_ || !connected_) return false;
    MQTTAsync client = static_cast<MQTTAsync>(mqtt_client_);
    {
        std::lock_guard<std::mutex> lock(callback_mutex_);
        subscriptions_.emplace_back(topic, std::move(callback));
    }
    MQTTAsync_responseOptions opts = MQTTAsync_responseOptions_initializer;
    int rc = MQTTAsync_subscribe(client, topic.c_str(), qos, &opts);
    return rc == MQTTASYNC_SUCCESS;
}

void MqttClient::start_loop() {}
void MqttClient::stop_loop() {}

void MqttClient::disconnect() {
    if (mqtt_client_) {
        MQTTAsync client = static_cast<MQTTAsync>(mqtt_client_);
        MQTTAsync_disconnectOptions opts = MQTTAsync_disconnectOptions_initializer;
        MQTTAsync_disconnect(client, &opts);
        MQTTAsync_destroy(&client);
        mqtt_client_ = NULL;
    }
    connected_ = false;
}

// ---- Message dispatch ----

void MqttClient::handle_message(const std::string& topic, const std::string& payload) {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    for (auto& pair : subscriptions_) {
        const std::string& sub_topic = pair.first;
        const MessageCallback& cb = pair.second;
        if (sub_topic.back() == '#' &&
            topic.find(sub_topic.substr(0, sub_topic.size() - 1)) == 0) {
            cb(topic, payload);
            return;
        }
        if (topic == sub_topic) {
            cb(topic, payload);
            return;
        }
    }
    if (default_callback_) {
        default_callback_(topic, payload);
    }
}
