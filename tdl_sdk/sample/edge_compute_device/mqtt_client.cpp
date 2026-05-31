#include "mqtt_client.h"
#include <iostream>
#include <cstring>
#include <vector>
#include <cerrno>
#include <sys/time.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>

// ─── MQTT 3.1.1 raw socket implementation ────────────────────────────
// Replaces paho.mqtt.c due to musl libc thread compatibility issues.

static constexpr unsigned char MQTT_CONNECT  = 0x10;
static constexpr unsigned char MQTT_CONNACK  = 0x20;
static constexpr unsigned char MQTT_PUBLISH  = 0x30;
static constexpr unsigned char MQTT_SUBSCRIBE = 0x82;
static constexpr unsigned char MQTT_SUBACK   = 0x90;
static constexpr unsigned char MQTT_PINGREQ  = 0xC0;
static constexpr unsigned char MQTT_PINGRESP = 0xD0;
static constexpr unsigned char MQTT_DISCONNECT = 0xE0;

void MqttClient::encode_remaining_length(unsigned char* buf, size_t& pos, uint32_t length) {
    do {
        unsigned char byte = length & 0x7F;
        length >>= 7;
        if (length > 0) byte |= 0x80;
        buf[pos++] = byte;
    } while (length > 0);
}

void MqttClient::encode_string(unsigned char* buf, size_t& pos, const std::string& s) {
    uint16_t len = static_cast<uint16_t>(s.size());
    buf[pos++] = (len >> 8) & 0xFF;
    buf[pos++] = len & 0xFF;
    memcpy(buf + pos, s.data(), len);
    pos += len;
}

int MqttClient::send_packet(const unsigned char* data, size_t len) {
    std::lock_guard<std::mutex> lock(send_mutex_);
    ssize_t sent = ::send(sock_fd_, data, len, 0);
    last_send_time_ = std::chrono::steady_clock::now();
    return sent == static_cast<ssize_t>(len) ? 0 : -1;
}

// ─── Public API ──────────────────────────────────────────────────────

MqttClient::~MqttClient() { disconnect(); }

bool MqttClient::connect(const std::string& broker_host, int broker_port,
                          const std::string& client_id, const std::string& lwt_topic,
                          const std::string& lwt_payload, int keepalive_seconds) {
    if (connected_) disconnect();
    // 确保上次 recv 线程已完全退出（兼容掉线后 recv_running_ 未清零的情况）
    stop_loop();

    keepalive_sec_ = keepalive_seconds;
    stop_requested_ = false;

    // ── TCP connect ──
    sock_fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (sock_fd_ < 0) {
        std::cerr << "[MqttClient] socket() failed errno=" << errno << std::endl;
        return false;
    }

    struct timeval tv = {10, 0};
    setsockopt(sock_fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(sock_fd_, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(broker_port);
    inet_pton(AF_INET, broker_host.c_str(), &addr.sin_addr);

    if (::connect(sock_fd_, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        std::cerr << "[MqttClient] connect() failed errno=" << errno << std::endl;
        close(sock_fd_); sock_fd_ = -1;
        return false;
    }

    // ── MQTT CONNECT packet ──
    unsigned char pkt[256];
    size_t pos = 0;
    memset(pkt, 0, sizeof(pkt));

    pkt[pos++] = MQTT_CONNECT;  // header

    // Variable header
    uint8_t flags = 0x02;  // clean session
    if (!lwt_topic.empty()) {
        flags |= 0x04;  // will flag
        flags |= ((lwt_payload.empty() ? 0 : 0) << 2);  // will QoS 0
        flags |= ((0) << 5);  // will retain = 0
    }

    size_t vh_start = pos;
    pos++;  // remaining length placeholder

    encode_string(pkt, pos, "MQTT");  // protocol name
    pkt[pos++] = 4;                    // protocol level 3.1.1
    pkt[pos++] = flags;               // connect flags
    pkt[pos++] = (keepalive_seconds >> 8) & 0xFF;  // keepalive MSB
    pkt[pos++] = keepalive_seconds & 0xFF;          // keepalive LSB

    // Payload: client ID
    encode_string(pkt, pos, client_id);

    // Will topic + message (if set)
    if (!lwt_topic.empty()) {
        encode_string(pkt, pos, lwt_topic);
        encode_string(pkt, pos, lwt_payload);
    }

    // Fill remaining length
    uint32_t rem_len = pos - vh_start - 1;
    size_t rl_pos = vh_start;
    encode_remaining_length(pkt, rl_pos, rem_len);
    // Shift payload if remaining-length encoding is longer than 1 byte
    if (rl_pos > vh_start + 1) {
        size_t shift = rl_pos - (vh_start + 1);
        memmove(pkt + rl_pos, pkt + vh_start + 1, pos - (vh_start + 1));
        pos += shift;
    }

    if (send_packet(pkt, pos) != 0) {
        std::cerr << "[MqttClient] send() CONNECT failed errno=" << errno << std::endl;
        close(sock_fd_); sock_fd_ = -1;
        return false;
    }

    // ── Wait for CONNACK ──
    if (!wait_for_connack(3)) {
        std::cerr << "[MqttClient] CONNACK timeout" << std::endl;
        close(sock_fd_); sock_fd_ = -1;
        return false;
    }

    connected_ = true;
    last_send_time_ = std::chrono::steady_clock::now();
    start_loop();
    std::cout << "[MqttClient] Connected to tcp://" << broker_host << ":" << broker_port << std::endl;
    return true;
}

bool MqttClient::wait_for_connack(int timeout_ms) {
    unsigned char buf[4];
    int elapsed = 0;
    while (elapsed < timeout_ms * 1000) {
        if (stop_requested_) return false;
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(sock_fd_, &fds);
        struct timeval tv = {0, 100000};  // 100ms
        int ret = select(sock_fd_ + 1, &fds, NULL, NULL, &tv);
        if (ret < 0) return false;
        if (ret > 0) {
            ssize_t n = recv(sock_fd_, buf, 4, 0);
            if (n < 4) return false;
            unsigned char type = buf[0] >> 4;
            unsigned char code = buf[3];
            if (type == 2 && code == 0) return true;  // CONNACK accepted
            std::cerr << "[MqttClient] CONNACK rejected: return_code=" << (int)code << std::endl;
            return false;
        }
        elapsed += 100;
    }
    return false;
}

bool MqttClient::publish(const std::string& topic, const std::string& payload, int qos) {
    if (!connected_ || sock_fd_ < 0) return false;

    unsigned char pkt[2048];
    size_t pos = 0;

    // Header
    unsigned char header = MQTT_PUBLISH;
    if (qos > 0) header |= (qos << 1);
    pkt[pos++] = header;

    // Remaining length: write first, then data follows
    uint32_t data_len = 2 + topic.size() + (qos > 0 ? 2 : 0) + payload.size();
    unsigned char rl_buf[4];
    size_t rl_len = 0;
    encode_remaining_length(rl_buf, rl_len, data_len);
    for (size_t i = 0; i < rl_len; i++) pkt[pos++] = rl_buf[i];

    // Topic + packet ID + payload
    encode_string(pkt, pos, topic);
    if (qos > 0) {
        static uint16_t packet_id = 0;
        packet_id++;
        pkt[pos++] = (packet_id >> 8) & 0xFF;
        pkt[pos++] = packet_id & 0xFF;
    }
    memcpy(pkt + pos, payload.data(), payload.size());
    pos += payload.size();

    std::cout << "[MqttClient] publish sent topic=" << topic << " len=" << payload.size() << std::endl;
    return send_packet(pkt, pos) == 0;
}

bool MqttClient::subscribe(const std::string& topic, int qos, MessageCallback callback) {
    if (!connected_ || sock_fd_ < 0) {
        std::cerr << "[MqttClient] subscribe FAILED: connected=" << connected_ << " fd=" << sock_fd_ << std::endl;
        return false;
    }

    {
        std::lock_guard<std::mutex> lock(callback_mutex_);
        subscriptions_.emplace_back(topic, std::move(callback));
    }

    // Send SUBSCRIBE packet
    unsigned char pkt[256];
    size_t pos = 0;

    pkt[pos++] = MQTT_SUBSCRIBE;

    // Remaining length first
    uint32_t data_len = 2 + 2 + topic.size() + 1;  // packetID(2) + topicLen(2) + topic + qos(1)
    unsigned char rl_buf[4];
    size_t rl_len = 0;
    encode_remaining_length(rl_buf, rl_len, data_len);
    for (size_t i = 0; i < rl_len; i++) pkt[pos++] = rl_buf[i];

    pkt[pos++] = 0x00;  // packet ID MSB
    pkt[pos++] = 0x01;  // packet ID LSB
    encode_string(pkt, pos, topic);
    pkt[pos++] = static_cast<unsigned char>(qos);  // requested QoS

    bool ok = send_packet(pkt, pos) == 0;
    std::cout << "[MqttClient] subscribe " << (ok ? "OK" : "FAIL")
              << " topic=" << topic << " qos=" << qos << std::endl;
    return ok;
}

void MqttClient::start_loop() {
    if (recv_running_) return;
    recv_running_ = true;
    recv_thread_ = std::thread(&MqttClient::recv_loop, this);
}

void MqttClient::stop_loop() {
    recv_running_ = false;
    if (recv_thread_.joinable()) recv_thread_.join();
}

void MqttClient::disconnect() {
    stop_requested_ = true;
    stop_loop();

    connected_ = false;
    if (sock_fd_ >= 0) {
        // Send DISCONNECT
        unsigned char disc[] = {MQTT_DISCONNECT, 0x00};
        ::send(sock_fd_, disc, 2, 0);
        close(sock_fd_);
        sock_fd_ = -1;
    }
}

// ─── Receive loop (background thread) ───────────────────────────────

void MqttClient::recv_loop() {
    std::cout << "[MqttClient] recv_loop started fd=" << sock_fd_ << std::endl;
    unsigned char buf[2048];
    unsigned char type_buf;

    while (recv_running_) {
        fd_set fds;
        FD_ZERO(&fds);
        FD_SET(sock_fd_, &fds);
        struct timeval tv = {1, 0};  // 1s timeout to check recv_running_

        int ret = select(sock_fd_ + 1, &fds, NULL, NULL, &tv);
        if (ret <= 0) {
            // Timeout: send PINGREQ if keepalive elapsed
            auto now = std::chrono::steady_clock::now();
            auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                now - last_send_time_).count();
            if (connected_ && elapsed >= keepalive_sec_ / 2) {
                unsigned char ping[] = {MQTT_PINGREQ, 0x00};
                send_packet(ping, 2);
            }
            if (ret < 0) {
                std::cerr << "[MqttClient] select error: " << errno << std::endl;
                connected_ = false;
                break;
            }
            continue;
        }

        std::cout << "[MqttClient] select returned " << ret << " fd=" << sock_fd_ << std::endl;

        // Read packet type
        ssize_t n = recv(sock_fd_, &type_buf, 1, MSG_PEEK);
        if (n <= 0) {
            if (n == 0 || errno != EAGAIN) {
                connected_ = false;
                break;
            }
            continue;
        }

        // Read fixed header: control byte + remaining length (1-4 bytes)
        unsigned char ctrl;
        n = recv(sock_fd_, &ctrl, 1, 0);
        if (n <= 0) {
            std::cerr << "[MqttClient] ctrl recv err: n=" << n << " errno=" << errno << std::endl;
            connected_ = false; break;
        }

        uint32_t rem_len = 0;
        int multiplier = 1;
        int rl_bytes = 0;
        unsigned char rl_byte;
        do {
            n = recv(sock_fd_, &rl_byte, 1, 0);
            if (n <= 0) {
                std::cerr << "[MqttClient] rl recv err: n=" << n << " errno=" << errno << std::endl;
                connected_ = false; break;
            }
            rem_len += (rl_byte & 0x7F) * multiplier;
            multiplier *= 128;
            rl_bytes++;
        } while ((rl_byte & 0x80) && rl_bytes < 4);

        if (!connected_) break;

        std::cout << "[MqttClient] packet type=0x" << std::hex << (int)(ctrl & 0xF0)
                  << std::dec << " rem_len=" << rem_len << std::endl;

        // Read remaining data
        size_t total = 0;
        while (total < rem_len) {
            ssize_t chunk = recv(sock_fd_, buf + total, rem_len - total, 0);
            if (chunk <= 0) {
                std::cerr << "[MqttClient] body recv err: chunk=" << chunk << " errno=" << errno << std::endl;
                connected_ = false; break;
            }
            total += chunk;
        }
        if (!connected_) break;

        // Dispatch
        unsigned char pkt_type = ctrl & 0xF0;
        if (pkt_type == MQTT_PINGRESP) {
            std::cout << "[MqttClient] recv PINGRESP" << std::endl;
        } else if (pkt_type == MQTT_PUBLISH) {
            // Parse topic
            if (total < 2) continue;
            uint16_t topic_len = (buf[0] << 8) | buf[1];
            if (total < 2 + topic_len) continue;
            std::string topic(reinterpret_cast<char*>(buf + 2), topic_len);
            size_t payload_offset = 2 + topic_len;
            std::string payload;
            if (total > payload_offset) {
                payload.assign(reinterpret_cast<char*>(buf + payload_offset),
                              total - payload_offset);
            }
            std::cout << "[MqttClient] recv PUBLISH topic=" << topic
                      << " len=" << payload.size() << std::endl;
            handle_message(topic, payload);
        }
        // SUBACK, CONNACK — ignore in recv loop
    }
}

// ─── Message dispatch ────────────────────────────────────────────────

void MqttClient::handle_message(const std::string& topic, const std::string& payload) {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    for (auto& pair : subscriptions_) {
        const std::string& sub_topic = pair.first;
        if (sub_topic.back() == '#' &&
            topic.find(sub_topic.substr(0, sub_topic.size() - 1)) == 0) {
            pair.second(topic, payload);
            return;
        }
        if (topic == sub_topic) {
            pair.second(topic, payload);
            return;
        }
    }
    if (default_callback_) {
        default_callback_(topic, payload);
    }
}
