#include "camera.h"
#include <iostream>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <linux/videodev2.h>

Camera::~Camera() { close(); }

bool Camera::open(const std::string& device, int width, int height) {
    device_ = device;
    width_ = width;
    height_ = height;

    fd_ = ::open(device.c_str(), O_RDWR);
    if (fd_ < 0) {
        std::cerr << "[Camera] Cannot open " << device << std::endl;
        return false;
    }

    // Query capabilities.
    struct v4l2_capability cap;
    if (ioctl(fd_, VIDIOC_QUERYCAP, &cap) < 0) {
        std::cerr << "[Camera] VIDIOC_QUERYCAP failed" << std::endl;
        close();
        return false;
    }
    if (!(cap.capabilities & V4L2_CAP_VIDEO_CAPTURE)) {
        std::cerr << "[Camera] Not a video capture device" << std::endl;
        close();
        return false;
    }

    // Set format to MJPEG or YUYV.
    struct v4l2_format fmt;
    memset(&fmt, 0, sizeof(fmt));
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = width;
    fmt.fmt.pix.height = height;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG;  // Try MJPEG first (for JPEG screenshots).
    fmt.fmt.pix.field = V4L2_FIELD_NONE;

    if (ioctl(fd_, VIDIOC_S_FMT, &fmt) < 0) {
        // Fallback to YUYV.
        fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUYV;
        if (ioctl(fd_, VIDIOC_S_FMT, &fmt) < 0) {
            std::cerr << "[Camera] VIDIOC_S_FMT failed" << std::endl;
            close();
            return false;
        }
    }

    init_mmap();
    start_streaming();
    std::cout << "[Camera] Opened " << device << " " << width << "x" << height << std::endl;
    return true;
}

bool Camera::init_mmap() {
    struct v4l2_requestbuffers req;
    memset(&req, 0, sizeof(req));
    req.count = 4;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;
    if (ioctl(fd_, VIDIOC_REQBUFS, &req) < 0) return false;

    buffers_.resize(req.count);
    for (uint32_t i = 0; i < req.count; i++) {
        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        if (ioctl(fd_, VIDIOC_QUERYBUF, &buf) < 0) return false;

        buffers_[i].length = buf.length;
        buffers_[i].start = mmap(nullptr, buf.length, PROT_READ | PROT_WRITE,
                                  MAP_SHARED, fd_, buf.m.offset);
        if (buffers_[i].start == MAP_FAILED) return false;
    }
    buffer_count_ = req.count;
    return true;
}

bool Camera::start_streaming() {
    for (int i = 0; i < buffer_count_; i++) {
        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;
        if (ioctl(fd_, VIDIOC_QBUF, &buf) < 0) return false;
    }
    int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    return ioctl(fd_, VIDIOC_STREAMON, &type) >= 0;
}

bool Camera::stop_streaming() {
    int type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    return ioctl(fd_, VIDIOC_STREAMOFF, &type) >= 0;
}

void Camera::close() {
    if (fd_ >= 0) {
        stop_streaming();
        for (auto& buf : buffers_) {
            munmap(buf.start, buf.length);
        }
        ::close(fd_);
        fd_ = -1;
    }
}

bool Camera::capture_rgb(std::vector<uint8_t>& rgb_data, int& width, int& height) {
    if (fd_ < 0) return false;

    struct v4l2_buffer buf;
    memset(&buf, 0, sizeof(buf));
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buf.memory = V4L2_MEMORY_MMAP;

    if (ioctl(fd_, VIDIOC_DQBUF, &buf) < 0) return false;

    // For MJPEG, decode to RGB. For YUYV, convert to RGB.
    // Simplified: just copy raw data (caller handles conversion).
    rgb_data.assign(static_cast<uint8_t*>(buffers_[buf.index].start),
                    static_cast<uint8_t*>(buffers_[buf.index].start) + buf.bytesused);
    width = width_;
    height = height_;

    ioctl(fd_, VIDIOC_QBUF, &buf);
    return true;
}

bool Camera::capture_jpeg(std::vector<uint8_t>& jpeg_data) {
    return capture_rgb(jpeg_data, width_, height_);
}
