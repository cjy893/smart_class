#include "mmf_pipeline.h"
#include <iostream>
#include <cstring>

MmfPipeline::~MmfPipeline() { deinit(); }

bool MmfPipeline::init(int tdl_width, int tdl_height,
                        int stream_width, int stream_height) {
    CVI_S32 s32Ret;

    // ---- Build middleware config ----
    SAMPLE_TDL_MW_CONFIG_S stMWConfig;
    memset(&stMWConfig, 0, sizeof(stMWConfig));

    // VI configuration from sensor_cfg.ini.
    s32Ret = SAMPLE_TDL_Get_VI_Config(&stMWConfig.stViConfig);
    if (s32Ret != CVI_SUCCESS || stMWConfig.stViConfig.s32WorkingViNum <= 0) {
        std::cerr << "[MmfPipeline] Failed to get VI config from /mnt/data/sensor_cfg.ini" << std::endl;
        return false;
    }

    // Get sensor size.
    PIC_SIZE_E enPicSize;
    s32Ret = SAMPLE_COMM_VI_GetSizeBySensor(
        stMWConfig.stViConfig.astViInfo[0].stSnsInfo.enSnsType, &enPicSize);
    if (s32Ret != CVI_SUCCESS) return false;

    SIZE_S stSensorSize;
    s32Ret = SAMPLE_COMM_SYS_GetPicSize(enPicSize, &stSensorSize);
    if (s32Ret != CVI_SUCCESS) return false;

    // ---- VBPool config (3 pools: VI, VPSS stream, TDL) ----
    stMWConfig.stVBPoolConfig.u32VBPoolCount = 3;

    // Pool 0: VI input.
    auto& pool0 = stMWConfig.stVBPoolConfig.astVBPoolSetup[0];
    pool0.enFormat = VI_PIXEL_FORMAT;
    pool0.u32BlkCount = 4;
    pool0.u32Height = stSensorSize.u32Height;
    pool0.u32Width = stSensorSize.u32Width;
    pool0.bBind = true;
    pool0.u32VpssChnBinding = VPSS_CHN0;
    pool0.u32VpssGrpBinding = (VPSS_GRP)0;

    // Pool 1: stream-size output.
    auto& pool1 = stMWConfig.stVBPoolConfig.astVBPoolSetup[1];
    pool1.enFormat = VI_PIXEL_FORMAT;
    pool1.u32BlkCount = 3;
    pool1.u32Height = static_cast<CVI_U32>(stream_height);
    pool1.u32Width = static_cast<CVI_U32>(stream_width);
    pool1.bBind = true;
    pool1.u32VpssChnBinding = VPSS_CHN1;
    pool1.u32VpssGrpBinding = (VPSS_GRP)0;

    // Pool 2: TDL input (RGB planar, smaller resolution for inference).
    auto& pool2 = stMWConfig.stVBPoolConfig.astVBPoolSetup[2];
    pool2.enFormat = PIXEL_FORMAT_BGR_888_PLANAR;
    pool2.u32BlkCount = 3;
    pool2.u32Height = static_cast<CVI_U32>(tdl_height);
    pool2.u32Width = static_cast<CVI_U32>(tdl_width);
    pool2.bBind = false;  // TDL SDK binds this pool via CVI_TDL_SetVBPool.

    // ---- VPSS config ----
    stMWConfig.stVPSSPoolConfig.u32VpssGrpCount = 1;
#ifndef __CV186X__
    stMWConfig.stVPSSPoolConfig.stVpssMode.aenInput[0] = VPSS_INPUT_MEM;
    stMWConfig.stVPSSPoolConfig.stVpssMode.enMode = VPSS_MODE_DUAL;
    stMWConfig.stVPSSPoolConfig.stVpssMode.ViPipe[0] = 0;
    stMWConfig.stVPSSPoolConfig.stVpssMode.aenInput[1] = VPSS_INPUT_ISP;
    stMWConfig.stVPSSPoolConfig.stVpssMode.ViPipe[1] = 0;
#endif
    auto& vpssCfg = stMWConfig.stVPSSPoolConfig.astVpssConfig[0];
    vpssCfg.bBindVI = true;
    VPSS_GRP_DEFAULT_HELPER2(&vpssCfg.stVpssGrpAttr, stSensorSize.u32Width,
                              stSensorSize.u32Height, VI_PIXEL_FORMAT, 1);

    vpssCfg.u32ChnCount = 2;
    vpssCfg.u32ChnBindVI = VPSS_CHN0;
    VPSS_CHN_DEFAULT_HELPER(&vpssCfg.astVpssChnAttr[0],
                             static_cast<CVI_U32>(tdl_width),
                             static_cast<CVI_U32>(tdl_height),
                             VI_PIXEL_FORMAT, false);
    VPSS_CHN_DEFAULT_HELPER(&vpssCfg.astVpssChnAttr[1],
                             static_cast<CVI_U32>(stream_width),
                             static_cast<CVI_U32>(stream_height),
                             VI_PIXEL_FORMAT, true);

    // ---- VENC config (used internally by middleware, even if we don't use RTSP) ----
    SAMPLE_TDL_Get_Input_Config(&stMWConfig.stVencConfig.stChnInputCfg);
    stMWConfig.stVencConfig.u32FrameWidth = static_cast<CVI_U32>(stream_width);
    stMWConfig.stVencConfig.u32FrameHeight = static_cast<CVI_U32>(stream_height);

    // RTSP config (not used, but structure must be zero-initialized).
    SAMPLE_TDL_Get_RTSP_Config(&stMWConfig.stRTSPConfig.stRTSPConfig);

    // ---- Initialize ----
    s32Ret = SAMPLE_TDL_Init_WM(&stMWConfig, &mw_ctx_);
    if (s32Ret != CVI_SUCCESS) {
        std::cerr << "[MmfPipeline] SAMPLE_TDL_Init_WM failed: 0x"
                  << std::hex << s32Ret << std::endl;
        return false;
    }

    grp_id_ = 0;
    vpss_chn_ = VPSS_CHN0;  // Channel 0 → TDL
    initialized_ = true;
    std::cout << "[MmfPipeline] Initialized. TDL channel: grp=" << grp_id_
              << " chn=" << vpss_chn_ << " size=" << tdl_width << "x" << tdl_height << std::endl;
    return true;
}

bool MmfPipeline::get_frame(VIDEO_FRAME_INFO_S& frame, int timeout_ms) {
    if (!initialized_) return false;
    CVI_S32 ret = CVI_VPSS_GetChnFrame(grp_id_, vpss_chn_, &frame, timeout_ms);
    if (ret != CVI_SUCCESS) {
        if (ret != 0xc006800e) {  // Timeout is normal, don't spam.
            std::cerr << "[MmfPipeline] GetChnFrame failed: 0x"
                      << std::hex << ret << std::dec << std::endl;
        }
        return false;
    }
    return true;
}

void MmfPipeline::release_frame(VIDEO_FRAME_INFO_S& frame) {
    if (!initialized_) return;
    CVI_VPSS_ReleaseChnFrame(grp_id_, vpss_chn_, &frame);
}

void MmfPipeline::deinit() {
    if (initialized_) {
        SAMPLE_TDL_Destroy_MW(&mw_ctx_);
        initialized_ = false;
        std::cout << "[MmfPipeline] Deinitialized." << std::endl;
    }
}
