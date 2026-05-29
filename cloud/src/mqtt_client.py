import asyncio
import logging
import threading
from typing import Awaitable, Callable, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - exercised only in deployments missing paho
    mqtt = None

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str, str], Awaitable[None]]


class MqttClient:
    def __init__(self, broker_host: str, broker_port: int, client_id: str):
        if mqtt is None:
            raise RuntimeError("paho-mqtt is required to use the real cloud MQTT client")
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id
        self.client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._handlers: dict[str, MessageHandler] = {}
        self._subscriptions: dict[str, int] = {}
        self._connected = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread_id: Optional[int] = None

    async def connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        self._sync_connect()

    def _sync_connect(self) -> None:
        self.client.connect_async(self.broker_host, self.broker_port, keepalive=30)
        self.client.loop_start()

    async def subscribe(self, topic: str, qos: int, handler: MessageHandler) -> None:
        self._handlers[topic] = handler
        self._subscriptions[topic] = qos
        if self._loop and self._loop.is_running() and self._loop_thread_id is None:
            self._loop_thread_id = threading.get_ident()
        if self._connected and self._loop:
            self.client.subscribe(topic, qos)

    async def publish(self, topic: str, payload: str, qos: int = 0) -> None:
        if not self._connected or not self._loop:
            logger.warning("MQTT publish skipped while offline: %s", topic)
            return
        self.client.publish(topic, payload, qos=qos)

    async def disconnect(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
        self._connected = False

    def _on_connect(self, client, userdata, flags, rc):
        self._connected = rc == 0
        if not self._connected:
            logger.error("MQTT connect failed, rc=%s", rc)
            return
        for topic, qos in self._subscriptions.items():
            self.client.subscribe(topic, qos)

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace")
        for pattern, handler in self._handlers.items():
            if _topic_matches(pattern, msg.topic) and self._loop:
                self._schedule_handler(handler, msg.topic, payload)

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


def _topic_matches(pattern: str, topic: str) -> bool:
    if pattern.endswith("/#"):
        return topic.startswith(pattern[:-1])
    return pattern == topic
