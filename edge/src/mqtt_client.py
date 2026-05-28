import asyncio
import json
import logging
from typing import Optional, Callable, Awaitable

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str, str], Awaitable[None]]


class MqttClient:
    """paho-mqtt async wrapper. 单线程 asyncio 集成，通过 loop.run_in_executor
       将同步 paho 回调桥接到 async handler。"""

    def __init__(self, broker_host: str, broker_port: int, client_id: str):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id
        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        self._handlers: dict[str, MessageHandler] = {}
        self._subscriptions: dict[str, int] = {}
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self, lwt_topic: str = "", lwt_payload: str = "") -> None:
        self._loop = asyncio.get_running_loop()
        if lwt_topic:
            self.client.will_set(lwt_topic, lwt_payload, qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        await self._loop.run_in_executor(None, self._sync_connect)

    def _sync_connect(self):
        self.client.connect(self.broker_host, self.broker_port, keepalive=30)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, rc):
        self._connected = (rc == 0)
        if rc == 0:
            logger.info("MQTT connected to %s:%d", self.broker_host, self.broker_port)
            for topic, qos in self._subscriptions.items():
                self.client.subscribe(topic, qos)
        else:
            logger.error("MQTT connect failed, rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        logger.warning("MQTT disconnected")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")
        for pattern, handler in self._handlers.items():
            if _topic_matches(pattern, topic) and self._loop:
                asyncio.run_coroutine_threadsafe(handler(topic, payload), self._loop)

    async def subscribe(self, topic: str, qos: int, handler: MessageHandler) -> None:
        self._handlers[topic] = handler
        self._subscriptions[topic] = qos
        if self._connected:
            await self._loop.run_in_executor(None, lambda: self.client.subscribe(topic, qos))

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        if not self._connected:
            logger.warning("MQTT publish skipped (offline): %s", topic)
            return
        await self._loop.run_in_executor(
            None, lambda: self.client.publish(topic, payload, qos=qos)
        )

    async def disconnect(self) -> None:
        self.client.loop_stop()
        await self._loop.run_in_executor(None, self.client.disconnect)
        self._connected = False


def _topic_matches(pattern: str, topic: str) -> bool:
    if pattern.endswith("/#"):
        return topic.startswith(pattern[:-1])
    return pattern == topic
