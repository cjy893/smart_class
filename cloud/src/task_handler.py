import base64
import binascii
import json
import re
import time
from typing import Any


class CloudTaskHandler:
    def __init__(self, mqtt, behavior_engine, report_generator):
        self.mqtt = mqtt
        self.behavior_engine = behavior_engine
        self.report_generator = report_generator
        self._result_cache: dict[str, dict[str, Any]] = {}

    async def start(self) -> None:
        await self.mqtt.subscribe("cloud/task/request/#", 1, self.handle_message)

    async def handle_message(self, topic: str, payload: str) -> None:
        try:
            message = json.loads(payload)
        except json.JSONDecodeError as exc:
            await self._publish_invalid_json(topic, payload, exc)
            return

        task_id = str(message.get("task_id", ""))
        if task_id in self._result_cache:
            await self._publish_result(message, self._result_cache[task_id])
            return

        try:
            result_payload = await self._execute(message)
        except Exception as exc:
            result_payload = self._build_result(
                message=message,
                status="FAILED",
                result={},
                metrics={},
                error=str(exc),
            )

        if task_id:
            self._result_cache[task_id] = result_payload
        await self._publish_result(message, result_payload)

    async def _execute(self, message: dict[str, Any]) -> dict[str, Any]:
        _validate_required(message)
        task_type = message.get("task_type")
        t0 = time.perf_counter()

        if task_type == "behavior_analyze":
            image = message.get("image", "")
            try:
                image_bytes = base64.b64decode(image.encode("ascii"), validate=True)
            except (binascii.Error, UnicodeEncodeError) as exc:
                raise ValueError("invalid base64 image") from exc
            result = await self.behavior_engine.analyze(image_bytes, message.get("params") or {})
            metrics = {"inference_latency_ms": (time.perf_counter() - t0) * 1000}
            return self._build_result(message, "COMPLETED", result, metrics)

        if task_type == "report_generate":
            result = self.report_generator.generate(message)
            metrics = {"generation_latency_ms": (time.perf_counter() - t0) * 1000}
            return self._build_result(message, "COMPLETED", result, metrics)

        return self._build_result(
            message=message,
            status="REJECTED",
            result={},
            metrics={},
            error=f"unsupported task_type: {task_type}",
        )

    def get_queue_depth(self) -> int:
        return 0

    async def _publish_invalid_json(self, topic: str, payload: str,
                                    exc: json.JSONDecodeError) -> None:
        task_id = _extract_string(payload, "task_id")
        device_id = _extract_string(payload, "device_id") or _device_from_topic(topic)
        message = {
            "task_id": task_id,
            "task_type": "",
            "device_id": device_id,
            "status": "FAILED",
            "result": {},
            "metrics": {},
            "error": f"invalid json: {exc.msg}",
        }
        await self.mqtt.publish(f"cloud/task/result/{device_id}", json.dumps(message), qos=1)

    async def _publish_result(self, request: dict[str, Any], result: dict[str, Any]) -> None:
        device_id = request.get("device_id") or result.get("device_id", "")
        await self.mqtt.publish(
            f"cloud/task/result/{device_id}",
            json.dumps(result, ensure_ascii=False),
            qos=1,
        )

    def _build_result(self, message: dict[str, Any], status: str, result: dict[str, Any],
                      metrics: dict[str, Any], error: str = "") -> dict[str, Any]:
        payload = {
            "task_id": message.get("task_id", ""),
            "task_type": message.get("task_type", ""),
            "device_id": message.get("device_id", ""),
            "session_id": message.get("session_id", ""),
            "status": status,
            "result": result,
            "metrics": metrics,
        }
        if error:
            payload["error"] = error
        return payload


def _extract_string(payload: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', payload)
    return match.group(1) if match else ""


def _device_from_topic(topic: str) -> str:
    return topic.rsplit("/", 1)[-1] if "/" in topic else ""


def _validate_required(message: dict[str, Any]) -> None:
    required = ("task_id", "task_type", "trigger_source", "session_id", "device_id", "created_at")
    missing = [key for key in required if not message.get(key)]
    if missing:
        raise ValueError(f"missing required task fields: {', '.join(missing)}")
