#define LOG_TAG "SamplePD"
#define LOG_LEVEL LOG_LEVEL_INFO

#include "core/utils/vpss_helper.h"
#include "cvi_tdl.h"
#include "cvi_tdl_app.h"
#include "sample_comm.h"
#include "vi_vo_utils.h"

#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define DEST_IP "192.168.42.114"
#define DEST_PORT 8888

static int udp_socket = -1;
static struct sockaddr_in dest_addr;

int InitUDPSender() {
    udp_socket = socket(AF_INET, SOCK_DGRAM, 0);
    if(udp_socket < 0) {
        perror("UDP socket creation failed");
        return -1;
    }

    memset(&dest_addr, 0, sizeof(dest_addr));
    dest_addr.sin_family = AF_INET;
    dest_addr.sin_port = htons(DEST_PORT);
    if(inet_pton(AF_INET, DEST_IP, &dest_addr.sin_addr) <= 0) {
        perror("Invalid destination IP address");
        return -1;
    }
    return 0;
}

void send_detections(int *frame_id, cvtdl_object_t *dets, int det_count) {
    if (udp_socket < 0) return;  // 未初始化

    char json_buf[2048];
    int offset = 0;
    int remaining = sizeof(json_buf);

    int written = snprintf(json_buf + offset, remaining,
                           "{\"frame\":%d,\"persons\":[", *frame_id);
    offset += written;
    remaining -= written;

    for (int i = 0; i < det_count; i++) {
        // 注意：根据你实际的 cvitdl_detection_t 结构体字段调整
        float x1 = dets->info[i].bbox.x1;
        float y1 = dets->info[i].bbox.y1;
        float x2 = dets->info[i].bbox.x2;
        float y2 = dets->info[i].bbox.y2;
        float score = dets->info[i].bbox.score;
        const char *sep = (i == det_count - 1) ? "" : ",";

        written = snprintf(json_buf + offset, remaining,
                           "{\"bbox\":[%.2f,%.2f,%.2f,%.2f],\"score\":%.2f}%s",
                           x1, y1, x2, y2, score, sep);
        
        if (written >= remaining) {
            printf("JSON buffer full, dropped %d detections\n", det_count - i);
            break;
        }
        offset += written;
        remaining -= written;
    }
    snprintf(json_buf + offset, remaining, "]}");

    int len = strlen(json_buf);
    ssize_t sent = sendto(udp_socket, json_buf, len, 0,
                          (struct sockaddr*)&dest_addr, sizeof(dest_addr));
    if (sent < 0) {
        perror("UDP sendto failed");
    } else {
        printf("Sent %zd bytes to server\n", sent);
        *frame_id += 1;
    }
}

// 程序退出时关闭 socket
void close_udp_sender() {
    if (udp_socket >= 0) close(udp_socket);
}

static volatile bool bExit = false;

static cvtdl_object_t g_stObjMeta = {0};

MUTEXAUTOLOCK_INIT(ResultMutex);

static void HandleSig(CVI_S32 signo) {
  signal(SIGINT, SIG_IGN);
  signal(SIGTERM, SIG_IGN);
  printf("handle signal, signo: %d\n", signo);
  if (SIGINT == signo || SIGTERM == signo) {
    bExit = true;
  }
}

int main(int argc, char *argv[]) {
    if (argc != 5) {
        printf("Usage: %s <od_model_name> <od_model_path> <config_path> <det_threshold>\n", argv[0]);
        return -1;
    }

    signal(SIGINT, HandleSig);
    signal(SIGTERM, HandleSig);

    const char *od_name = argv[1];
    const char *od_path = argv[2];
    const char *config_path = argv[3];
    float det_threshold = atof(argv[4]);

    VideoSystemContext vs_ctx = {0};
    if(InitVideoSystem(&vs_ctx, 25) != CVI_SUCCESS) {
        perror("failed to init video system\n");
        goto CLEANUP_SYSTEM;
    }

    cvitdl_handle_t tdl_handle = NULL;
    cvitdl_service_handle_t service_handle = NULL;
    cvitdl_app_handle_t app_handle = NULL;

    CVI_S32 ret = CVI_TDL_CreateHandle2(&tdl_handle, 1, 0);
    ret = CVI_TDL_Service_CreateHandle(&service_handle, tdl_handle);
    ret = CVI_TDL_APP_CreateHandle(&app_handle, tdl_handle);
    ret = CVI_TDL_APP_PersonCapture_Init(app_handle, 0);
    if(ret != CVI_TDL_SUCCESS) {
        printf("failed to init TDL app, ret=%x\n", ret);
        goto CLEANUP_SYSTEM;
    }
    ret = CVI_TDL_APP_PersonCapture_QuickSetUp(app_handle, od_name, od_path, NULL);
    if(ret != CVI_TDL_SUCCESS) {
        printf("failed to setup TDL app, ret=%x\n", ret);
        goto CLEANUP_SYSTEM;
    }

    CVI_TDL_SetVpssTimeout(tdl_handle, 1000);
    CVI_TDL_SetModelThreshold(tdl_handle, app_handle->person_cpt_info->od_model_index, det_threshold);
    CVI_TDL_SelectDetectClass(tdl_handle, app_handle->person_cpt_info->od_model_index, 0, CVI_TDL_DET_TYPE_PERSON);

    VIDEO_FRAME_INFO_S stVIFrame;
    int frame_counter = 0;

    ret = InitUDPSender();
    if(ret < 0) {
        printf("failed to init UDP sender\n");
        goto CLEANUP_SYSTEM;
    }

    while(bExit == false) {
        ret = CVI_VPSS_GetChnFrame(vs_ctx.vpssConfigs.vpssGrp, vs_ctx.vpssConfigs.vpssChntdl, &stVIFrame, 1000);
        if(ret != CVI_SUCCESS) {
            printf("CVI_VPSS_GetChnFrame failed with %#x\n", ret);
            continue;
        }

        ret = CVI_TDL_APP_PersonCapture_Run(app_handle, &stVIFrame);
        if(ret != CVI_TDL_SUCCESS) {
            printf("CVI_TDL_APP_PersonCapture_Run failed with %#x\n", ret);
        } else {
            cvtdl_object_t *objs = &app_handle->person_cpt_info->last_objects;
            send_detections(&frame_counter, objs, objs->size);
        }

        CVI_VPSS_ReleaseChnFrame(vs_ctx.vpssConfigs.vpssGrp, vs_ctx.vpssConfigs.vpssChntdl, &stVIFrame);
    }

    
CLEANUP_SYSTEM:
    close_udp_sender();
    CVI_TDL_APP_DestroyHandle(&app_handle);
    CVI_TDL_Service_DestroyHandle(&service_handle);
    CVI_TDL_DestroyHandle(&tdl_handle);
    DestroyVideoSystem(&vs_ctx);
    CVI_SYS_Exit();
    CVI_VB_Exit();
    printf("Exit program\n");
    return 0;
}