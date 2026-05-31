# Cloud 端 Windows 使用指南

本文说明如何在 Windows 10/11 上运行项目的 cloud 端。cloud 端负责接收边侧转发的高复杂度任务、执行行为分析、生成课堂报告、提供报告 HTTP 服务，并通过 MQTT 上报云端状态。

## 1. 环境准备

建议使用 Python 3.11 或 3.10 的 64 位版本，并在 PowerShell 中执行以下命令：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r cloud/requirements.txt
pip install pytest
```

如果 PowerShell 拦截虚拟环境脚本，可临时执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 2. MQTT Broker

cloud 端通过 MQTT 连接边侧 Broker。推荐在边侧 Atlas 上运行 Mosquitto；Windows 本机联调时也可以安装 Mosquitto for Windows。

本机联调可用默认端口启动：

```powershell
mosquitto -p 1883 -v
```

然后把 `cloud/config/cloud_config.yaml` 中的 `mqtt.broker_host` 改成 Broker 所在机器 IP；如果 Broker 就在 Windows 本机，填 `127.0.0.1`。

## 3. 目录和模型

默认配置使用仓库内相对路径，适合 Windows：

```yaml
paths:
  models: "../data/models"
  reports: "../data/reports"
behavior:
  model_path: "../data/models/yolov5m.onnx"
```

启动前需要准备：

- 模型文件：`cloud/data/models/yolov5m.onnx`
- 报告目录：`cloud/data/reports`

报告目录会由服务自动创建。模型文件必须存在，否则 cloud 端会在启动阶段快速失败，避免运行到任务执行时才暴露配置错误。

## 4. 配置

默认配置文件是 `cloud/config/cloud_config.yaml`。也可以用环境变量指定其他配置：

```powershell
$env:CLOUD_CONFIG = "D:\smart_class\cloud\config\cloud_config.yaml"
```

关键字段：

- `cloud_id`：云端节点标识，默认 `cloud-main`
- `mqtt.broker_host` / `mqtt.broker_port`：边侧或本机 Mosquitto 地址
- `grpc.listen_address`：接收边侧 gRPC 状态上报的监听地址，默认 `0.0.0.0:50051`
- `http.host` / `http.port`：报告 HTTP 服务地址，默认 `0.0.0.0:8081`
- `paths.models`：模型目录
- `paths.reports`：报告输出目录
- `behavior.model_path`：YOLOv5m ONNX 模型路径

相对路径会按配置文件所在目录解析。例如 `../data/reports` 会解析到 `cloud/data/reports`。

## 5. 测试

在仓库根目录运行 cloud 单元测试：

```powershell
pytest test/cloud -q
```

如果需要验证真实 MQTT 链路，先启动 Mosquitto，然后运行集成测试：

```powershell
pytest test/integration/test_cloud_broker_link.py -q
```

集成测试也支持连接已有 Broker：

```powershell
$env:SMART_CLASS_MQTT_BROKER_HOST = "127.0.0.1"
$env:SMART_CLASS_MQTT_BROKER_PORT = "1883"
pytest test/integration/test_cloud_broker_link.py -q
```

## 6. 启动前自检

启动服务前建议先运行自检。它会检查配置文件、Python 依赖、模型文件和报告目录：

```powershell
python cloud/src/main.py --check
```

也可以使用项目提供的 PowerShell 包装脚本：

```powershell
.\cloud\run_cloud_windows.ps1 -Check
```

如果使用自定义配置：

```powershell
python cloud/src/main.py --check --config D:\smart_class\cloud\config\cloud_config.yaml
```

看到 `cloud check passed` 后再启动服务。若输出 `[ERROR]`，按提示补齐依赖、模型或目录配置。

## 7. 启动 cloud 端

确认虚拟环境已激活、Broker 可连接、模型文件已放好后，在仓库根目录执行：

```powershell
python cloud/src/main.py
```

等价的 PowerShell 包装脚本：

```powershell
.\cloud\run_cloud_windows.ps1
```

使用自定义配置启动：

```powershell
python cloud/src/main.py --config D:\smart_class\cloud\config\cloud_config.yaml
```

启动成功后 cloud 端会：

- 预检查 `cloud/data/models/yolov5m.onnx`
- 连接 MQTT Broker
- 订阅 `cloud/task/request/#`
- 启动 gRPC 服务
- 启动报告 HTTP 服务
- 周期性发布 `cloud/status/report`

Windows 下按 `Ctrl+C` 停止服务。程序会执行 MQTT、HTTP 和 gRPC 的关闭流程。

## 8. 报告访问

报告生成后会写入 `cloud/data/reports`。默认 HTTP 地址：

```text
http://127.0.0.1:8081/reports/<report-file>.html
```

边侧调度器会从 cloud 端任务结果中的 `report_url` 获取报告路径。

## 9. 常见问题

`FileNotFoundError: model path does not exist`：检查 `cloud/data/models/yolov5m.onnx` 是否存在，或修改 `cloud/config/cloud_config.yaml` 中的 `behavior.model_path`。

`MQTT connect failed`：确认 Mosquitto 已启动，`mqtt.broker_host` 是 Windows 能访问到的地址，防火墙允许 1883 端口。

`grpcio` 或 `opencv-python` 安装失败：确认 Python 是 64 位版本，并先升级 pip。必要时重新创建虚拟环境后再安装 `cloud/requirements.txt`。
