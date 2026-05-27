#include "inference_engine.h"
#include <cstring>
#include <iostream>
#include "cvi_tdl.h"

InferenceEngine::~InferenceEngine() {
    if (tdl_handle_) {
        CVI_TDL_DestroyHandle(static_cast<cvitdl_handle_t>(tdl_handle_));
    }
}

bool InferenceEngine::init(const std::string& model_path, float threshold,
                            float nms_threshold, int vpss_grp, int vb_pool) {
    cvitdl_handle_t handle = nullptr;
    // CreateHandle2(handle, group_count, start_device).
    // We have 1 VPSS group, starting from device 0.
    CVI_S32 ret = CVI_TDL_CreateHandle2(&handle, 1, 0);
    if (ret != CVI_SUCCESS) {
        std::cerr << "[InferenceEngine] CVI_TDL_CreateHandle2 failed: 0x"
                  << std::hex << ret << std::endl;
        return false;
    }
    tdl_handle_ = handle;

    // Assign VBPool to TDL SDK for preprocessing.
    ret = CVI_TDL_SetVBPool(handle, 0, static_cast<CVI_U32>(vb_pool));
    if (ret != CVI_SUCCESS) {
        std::cerr << "[InferenceEngine] CVI_TDL_SetVBPool failed: 0x"
                  << std::hex << ret << std::endl;
        return false;
    }

    CVI_TDL_SetVpssTimeout(handle, 1000);

    ret = CVI_TDL_OpenModel(handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION,
                             model_path.c_str());
    if (ret != CVI_SUCCESS) {
        std::cerr << "[InferenceEngine] CVI_TDL_OpenModel failed: 0x"
                  << std::hex << ret << std::endl;
        return false;
    }

    CVI_TDL_SetModelThreshold(handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, threshold);
    CVI_TDL_SetModelNmsThreshold(handle, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, nms_threshold);

    initialized_ = true;
    std::cout << "[InferenceEngine] Initialized. model=" << model_path
              << " thr=" << threshold << " vpss_grp=" << vpss_grp << std::endl;
    return true;
}

int InferenceEngine::detect_persons(VIDEO_FRAME_INFO_S* frame,
                                     PersonCountCallback callback) {
    if (!initialized_ || !frame) return 0;
    cvitdl_handle_t handle = static_cast<cvitdl_handle_t>(tdl_handle_);

    auto t0 = std::chrono::steady_clock::now();

    cvtdl_object_t obj_meta = {0};
    CVI_S32 ret = CVI_TDL_Detection(handle, frame,
                                     CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION,
                                     &obj_meta);

    auto t1 = std::chrono::steady_clock::now();
    double latency_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();

    if (ret != CVI_SUCCESS) {
        std::cerr << "[InferenceEngine] Detection failed: 0x"
                  << std::hex << ret << std::endl;
        CVI_TDL_Free(&obj_meta);
        return -1;
    }

    int person_count = 0;
    for (uint32_t i = 0; i < obj_meta.size; i++) {
        if (obj_meta.info[i].classes == 0) {  // COCO class 0 = person
            person_count++;
        }
    }

    CVI_TDL_Free(&obj_meta);

    if (callback) {
        callback(person_count, latency_ms);
    }

    return person_count;
}
