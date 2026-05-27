# Milk-V Duo256M 平台开发须知与技巧

## 1. 平台概览

| 项目 | 规格 |
|---|---|
| SoC | CVITEK CV1812H (CV181x 系列) |
| CPU | RISC-V 64 (C906), musl libc |
| NPU | 内置, INT8 量化推理 |
| 内存 | 256MB DDR3 |
| 系统 | Buildroot Linux, 无 MMU 限制 |
| 摄像头 | MIPI CSI, 通过 VI+ISP+VPSS 管线访问 |
| 交叉编译 | `riscv64-unknown-linux-musl-gcc/g++` |

## 2. 摄像头访问

### ❌ 不能直接用 V4L2

`/dev/video0` **不存在**。摄像头通过 Cvitek 专有的 MMF (Multimedia Framework) 管线访问：

```
Sensor → MIPI → VI (Video Input) → ISP (Image Signal Processor) → VPSS (Video Processing) → VBPool → AI Model
```

### ✅ 正确的访问方式

1. 从 `/mnt/data/sensor_cfg.ini` 读取传感器配置
2. 调用 `SAMPLE_TDL_Init_WM()` 初始化整个管线（VI + ISP + VPSS + VENC + VBPool）
3. 通过 `CVI_VPSS_GetChnFrame(grp_id, vpss_chn, &frame, timeout)` 获取帧
4. 帧直接传给 `CVI_TDL_Detection()` 做推理
5. 用 `CVI_VPSS_ReleaseChnFrame()` 释放帧
6. 退出时调用 `SAMPLE_TDL_Destroy_MW()` 清理

### VBPool 分配策略（3 个 Pool）

| Pool | 用途 | 格式 | 分辨率 |
|---|---|---|---|
| 0 | VI 输入 | `VI_PIXEL_FORMAT` (YUV) | 传感器原始 (1920×1080) |
| 1 | VPSS 流输出 | `VI_PIXEL_FORMAT` (YUV) | 流分辨率 (1280×720) |
| 2 | TDL SDK 推理输入 | `PIXEL_FORMAT_BGR_888_PLANAR` | 推理分辨率 (768×432) |

> Pool 2 设置 `bBind = false`，由 TDL SDK 通过 `CVI_TDL_SetVBPool()` 自动绑定并完成 YUV→RGB 格式转换。

### VPSS 模式（CV181x 平台）

```c
#ifndef __CV186X__
    stVpssMode.aenInput[0] = VPSS_INPUT_MEM;
    stVpssMode.enMode = VPSS_MODE_DUAL;
    stVpssMode.ViPipe[0] = 0;
    stVpssMode.aenInput[1] = VPSS_INPUT_ISP;
    stVpssMode.ViPipe[1] = 0;
#endif
```

**CV181x 必须设置 DUAL 模式**，否则 `CVI_VPSS_CreateGrp` 返回 `0xc0068003`。

### VPSS 通道配置

| 通道 | 分辨率 | 格式 | 用途 |
|---|---|---|---|
| CHN0 (绑定 VI) | 768×432 | `VI_PIXEL_FORMAT` | TDL 推理输入（下采样即可，不要改像素格式） |
| CHN1 | 1280×720 | `VI_PIXEL_FORMAT` | VENC 流输出 |

### 清理必须完整

退出时必须调用：
1. `SAMPLE_TDL_Destroy_MW()` — 释放 VI/ISP/VPSS/VENC
2. `CVI_TDL_DestroyHandle()` — 释放 TDL SDK

否则 MMF 资源泄漏，**下次运行 VPSS 会创建失败**（资源被占用）。

## 3. TDL SDK 集成

### 模型选择

- 使用官方 `cv181x` 平台预编译模型，免去自己转换
- 模型 ID: `CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION`
- 推荐模型: `yolov8n_det_coco80_640_640_INT8_cv181x.cvimodel`
- COCO class 0 = person

### TDL Handle 创建

```c
CVI_TDL_CreateHandle2(&handle, 1, 0);  // 1个VPSS组, 从设备0开始
CVI_TDL_SetVBPool(handle, 0, 2);       // 设备0绑定VBPool 2
CVI_TDL_SetVpssTimeout(handle, 1000);  // VPSS超时1秒
```

### 推理 API

```c
cvtdl_object_t obj_meta = {0};
CVI_TDL_Detection(handle, &frame, CVI_TDL_SUPPORTED_MODEL_YOLOV8_DETECTION, &obj_meta);
// 遍历 obj_meta.info[i].classes == 0 计数 person
CVI_TDL_Free(&obj_meta);
```

### 头文件注意事项

- **TDL SDK 头文件不要用 `extern "C"` 包裹** —— 内部已处理 C/C++ 链接，且包含 C++ 函数重载（如 `CVI_TDL_FreeCpp`），包裹后会导致 conflicting declaration 编译错误
- **middleware_utils.h 等纯 C 头文件必须用 `extern "C"` 包裹** —— 否则 C++ 编译会产生 name mangling 导致链接时 undefined reference
- `middleware_utils.h` 无条件 include `<rtsp.h>`，需要添加 `${CVI_RTSP_INCLUDE}` 到 include 路径并链接 `libcvi_rtsp.so`

## 4. 交叉编译环境

### 工具链

- 编译器: `riscv64-unknown-linux-musl-gcc/g++`
- C++ 标准: **gnu++11**（TDL SDK 硬编码，不可改）
- 编译标志: `-mcpu=c906fdv -march=rv64imafdcv0p7xthead -mabi=lp64d`

### C++ 标准限制

| 特性 | 可用？ |
|---|---|
| `std::make_unique` | ❌ C++14 |
| `std::unique_ptr<T>(new T(...))` | ✅ C++11 |
| lambda | ✅ |
| `std::atomic` | ✅ |
| `auto` | ✅ |

### 第三方库集成

SDK 使用 `FetchContent` + 预编译 tarball 模式。新增库的步骤：

1. 创建 `cmake/xxx.cmake`，复用 `thirdparty.cmake` 的 `ARCHITECTURE` 变量和 `IS_LOCAL` / `TOP_DIR` 模式
2. 在顶层 `CMakeLists.txt` 中 `include(cmake/xxx.cmake)`
3. tarball 放在 `${TOP_DIR}/oss/oss_release_tarball/${ARCHITECTURE}/xxx.tar.gz`
4. tarball 结构: `include/*.h` + `lib/*.so*`（或 `.a`）
5. 在项目 `CMakeLists.txt` 中检查 `XXX_FOUND` 并链接

```cmake
if (IS_LOCAL)
  set(XXX_URL ${3RD_PARTY_URL_PREFIX}${ARCHITECTURE}/xxx.tar.gz)
else()
  set(XXX_URL ${TOP_DIR}/oss/oss_release_tarball/${ARCHITECTURE}/xxx.tar.gz)
endif()
```

### 不需要的 middleware 源文件

`sample_common_vo.c` 依赖 DSI 显示屏头文件（`dsi_hx8394_evb.h`），不需要 VO 输出时从源文件列表中移除。

### RTSP 库

即使使用 `SAMPLE_TDL_Destroy_MW_NO_RTSP`（跳过 RTSP 清理），`middleware_utils.h` 仍然无条件 include `<rtsp.h>` 且链接时需要 `libcvi_rtsp.so`。`_NO_RTSP` 版本的 `Init` 函数只有声明没有实现，只能使用完整的 `SAMPLE_TDL_Init_WM()`。

## 5. 运行时

### 系统库路径

- `/mnt/system/lib/` — 系统库（中间件、TDL SDK 等）
- `/mnt/data/` — 用户数据和配置
- `/mnt/data/sensor_cfg.ini` — 传感器配置文件（必须存在）
- 运行前设置: `export LD_LIBRARY_PATH=/mnt/system/lib:$LD_LIBRARY_PATH`

### 时钟问题

设备上电后 RTC 未设置，时间显示为 `19700101`（Unix epoch）。不影响功能，但日志时间戳不准确。

### 网络

- 通过 USB RNDIS 虚拟网卡连接: `192.168.42.1`
- MQTT Broker 需要在局域网内可达

### 资源竞争

- VI/VPSS 设备是独占资源，同一时间只能有一个进程使用
- 前一个进程必须完整清理 MMF 资源，否则后续进程无法打开设备

## 6. 调试技巧

### 构建日志

```bash
# 查看所有错误
grep -n "FAILED\|fatal error\|error:" log.txt

# 查看链接错误
grep "undefined reference" log.txt
```

### 运行时诊断

- `CVI_VPSS_CreateGrp` 返回 `0xc0068003` → VPSS 配置错误或设备被占用
- `CVI_VPSS_GetChnFrame` 返回 `0xc006800e` → 设备未就绪或已被释放
- `/dev/cvi-vo` 不存在 → 正常（无显示输出设备），不影响功能

### 交叉编译第三方库

- **CMake 项目**（如 paho.mqtt.c）: 使用 `-DCMAKE_TOOLCHAIN_FILE=...` 指定工具链
- **autotools 项目**（如 libmicrohttpd）: 使用 `--host=riscv64-unknown-linux-musl` 并设置 `CC`/`CXX` 等环境变量

### 关键编译问题速查

| 错误 | 原因 | 解决 |
|---|---|---|
| `fatal error: yaml-cpp/yaml.h` | SDK 无 yaml-cpp | 自实现 key=value 解析器 |
| `fatal error: MQTTAsync.h` | paho.mqtt.c 未集成 | FetchContent 导入预编译包 |
| `conflicting declaration of C function` | `extern "C"` 包裹了含 C++ 重载的头文件 | 去掉 `extern "C"` |
| `'make_unique' is not a member of 'std'` | C++11 不支持 C++14 特性 | 改用 `unique_ptr<T>(new T(...))` |
| `'vector' does not name a template type` | 头文件缺少 `#include <vector>` | 补齐 include |
| `cannot find -lpaho-mqtt3as` | 库名错误（无 SSL 编译） | 改为 `paho-mqtt3a` |
| `fatal error: rtsp.h` | 缺少 RTSP include 路径 | 添加 `${CVI_RTSP_INCLUDE}` |
| `undefined reference to SAMPLE_TDL_*` | C 函数从 C++ 调用 name mangling | `extern "C"` 包裹 middleware_utils.h |
| `undefined reference to CVI_RTSP_*` | 未链接 RTSP 库 | 添加 `${CVI_RTSP_LIBPATH}` |
| `CVI_VPSS_CreateGrp failed: 0xc0068003` | 缺少 VPSS DUAL 模式或 CHN 配置错误 | 添加 `VPSS_MODE_DUAL`，CHN 格式用 `VI_PIXEL_FORMAT` |
