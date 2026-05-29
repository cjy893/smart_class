import asyncio
import json
import logging
import threading
from typing import Optional, Callable, Awaitable

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str, str], Awaitable[None]]


class MqttClient:
    """paho-mqtt async wrapper. 通过 paho 网络线程桥接到 async handler。"""

    def __init__(self, broker_host: str, broker_port: int, client_id: str):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id
        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        self._handlers: dict[str, MessageHandler] = {}
        self._subscriptions: dict[str, int] = {}
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread_id: Optional[int] = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self, lwt_topic: str = "", lwt_payload: str = "") -> None:
        self._loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        if lwt_topic:
            self.client.will_set(lwt_topic, lwt_payload, qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self._sync_connect()

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
                self._schedule_handler(handler, topic, payload)

    def _schedule_handler(self, handler: MessageHandler, topic: str, payload: str) -> None:
        if not self._loop or self._loop.is_closed():
            return
        if self._loop_thread_id == threading.get_ident():
            self._loop.create_task(handler(topic, payload))
            return
        self._loop.call_soon_threadsafe(
            self._loop.create_task,
            handler(topic, payload),
        )

    async def subscribe(self, topic: str, qos: int, handler: MessageHandler) -> None:
        self._handlers[topic] = handler
        self._subscriptions[topic] = qos
        if self._loop and self._loop.is_running() and self._loop_thread_id is None:
            self._loop_thread_id = threading.get_ident()
        if self._connected:
            self.client.subscribe(topic, qos)

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        if not self._connected:
            logger.warning("MQTT publish skipped (offline): %s", topic)
            return
        self.client.publish(topic, payload, qos=qos)

    async def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
        self._connected = False


def _topic_matches(pattern: str, topic: str) -> bool:
    if pattern.endswith("/#"):
        return topic.startswith(pattern[:-1])
    return pattern == topic
