import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class InferenceService:
    """MindX SDK mxVision 全局服务封装。

    管理 NPU 设备生命周期、模型加载/卸载。
    由于 MindX SDK 的 model.infer() 是同步调用，
    所有推理通过 asyncio.to_thread() 包装。

    环境要求：
    - Python 3.9+
    - MindX SDK 已安装并 source set_env.sh
    - 模型已转换为 .om 格式
    """

    def __init__(self, mindx_home: str = "/usr/local/Ascend/mindx_sdk",
                 device_id: int = 0):
        self.mindx_home = Path(mindx_home)
        self.device_id = device_id
        self._models: dict[str, "base.Model"] = {}
        self._initialized = False
        self._base = None  # mindx.sdk.base module

    async def init(self, model_paths: dict[str, str]) -> None:
        """初始化 MindX SDK 并预加载所有模型。

        Args:
            model_paths: {name: /path/to/model.om}
        """
        # 设置环境
        set_env = self.mindx_home / "set_env.sh"
        if not set_env.exists():
            logger.warning("MindX SDK set_env.sh not found at %s, assuming PATH is pre-configured",
                           set_env)

        await asyncio.to_thread(self._sync_init, model_paths)
        self._initialized = True
        logger.info("InferenceService initialized, %d models loaded", len(self._models))

    def _sync_init(self, model_paths: dict[str, str]) -> None:
        from mindx.sdk import base
        self._base = base
        base.mx_init()
        for name, path in model_paths.items():
            if not os.path.exists(path):
                logger.warning("Model not found: %s=%s", name, path)
                continue
            model = base.Model(modelPath=path, deviceID=self.device_id)
            self._models[name] = model
            logger.info("Model loaded: %s → %s", name, path)

    def get_model(self, name: str) -> Optional["base.Model"]:
        return self._models.get(name)

    async def deinit(self) -> None:
        if self._base:
            await asyncio.to_thread(self._base.mx_deinit)
        self._models.clear()
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized
