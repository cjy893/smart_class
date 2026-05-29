#pragma once
#include <cvi_comm.h>
#include <sample_comm.h>
#include <core/utils/vpss_helper.h>

extern "C" {
#include "sample_video/middleware_utils.h"
}

// Thin wrapper over the Cvitek MMF VI→VPSS pipeline.
// Replaces the V4L2 Camera module — Milk-V accesses the image sensor
// through VI/ISP/VPSS, not through /dev/video0.
class MmfPipeline {
public:
    MmfPipeline() = default;
    ~MmfPipeline();

    // Initialize VI, ISP, VPSS, and VBPools.
    // Must be called before TDL SDK init (CVI_TDL_SetVBPool depends on it).
    bool init(int tdl_width = 768, int tdl_height = 432,
              int stream_width = 1280, int stream_height = 720);

    // Get a frame from the VPSS TDL channel. Blocks up to timeout_ms.
    // Returns true on success. Caller must call release_frame() after use.
    bool get_frame(VIDEO_FRAME_INFO_S& frame, int timeout_ms = 2000);

    // Release a frame back to VPSS.
    void release_frame(VIDEO_FRAME_INFO_S& frame);

    // Tear down the pipeline.
    void deinit();

    bool is_initialized() const { return initialized_; }

    // Accessors for TDL SDK binding.
    int grp_id() const { return grp_id_; }
    int vpss_chn() const { return vpss_chn_; }

private:
    SAMPLE_TDL_MW_CONTEXT mw_ctx_;
    bool initialized_ = false;
    int grp_id_ = 0;
    int vpss_chn_ = 0;   // VPSS channel bound to TDL
};
