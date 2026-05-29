#pragma once
#include <string>
#include <functional>
#include <atomic>
#include <chrono>
#include <cvi_comm.h>

// Wrapper over TDL SDK YOLOv8n for person detection.
// Works directly on VPSS VIDEO_FRAME_INFO_S frames (no raw RGB copy).
class InferenceEngine {
public:
    using PersonCountCallback = std::function<void(int count, double latency_ms)>;

    InferenceEngine() = default;
    ~InferenceEngine();

    // Create TDL handle, set VBPool, open model.
    bool init(const std::string& model_path, float threshold, float nms_threshold,
              int vpss_grp = 0, int vb_pool = 2);

    // Detect persons in a VPSS frame. Returns count, or -1 on error.
    int detect_persons(VIDEO_FRAME_INFO_S* frame, PersonCountCallback callback = nullptr);

    bool is_initialized() const { return initialized_; }

private:
    void* tdl_handle_ = nullptr;    // cvitdl_handle_t
    bool initialized_ = false;
};
