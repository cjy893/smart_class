#pragma once
#include <string>
#include <vector>
#include <cstdint>

// V4L2 camera capture. Provides raw RGB frames and JPEG screenshots.
class Camera {
public:
    Camera() = default;
    ~Camera();

    // Open camera device and configure format.
    bool open(const std::string& device, int width, int height);

    // Capture one frame into RGB buffer. Returns true on success.
    bool capture_rgb(std::vector<uint8_t>& rgb_data, int& width, int& height);

    // Capture one frame as JPEG. Returns true on success.
    bool capture_jpeg(std::vector<uint8_t>& jpeg_data);

    void close();
    bool is_open() const { return fd_ >= 0; }

private:
    int fd_ = -1;
    int width_ = 0;
    int height_ = 0;
    std::string device_;

    bool init_mmap();
    bool start_streaming();
    bool stop_streaming();

    struct Buffer {
        void* start;
        size_t length;
    };
    std::vector<Buffer> buffers_;
    int buffer_count_ = 0;
};
