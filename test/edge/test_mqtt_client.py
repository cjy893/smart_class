import asyncio

import mqtt_client
from mqtt_client import MqttClient, _topic_matches


class FakePahoMessage:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


class FakePahoClient:
    def __init__(self, client_id=None, protocol=None):
        self.client_id = client_id
        self.protocol = protocol
        self.subscriptions = []
        self.published = []
        self.connected = []
        self.loop_started = False
        self.loop_stopped = False
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None

    def connect(self, host, port, keepalive=30):
        self.connected.append((host, port, keepalive))
        if self.on_connect:
            self.on_connect(self, None, None, 0)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def subscribe(self, topic, qos):
        self.subscriptions.append((topic, qos))

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))

    def disconnect(self):
        pass


def run(coro):
    return asyncio.run(coro)


def install_fake_paho(monkeypatch, fake_client):
    class FakeMqttModule:
        MQTTv311 = object()

        @staticmethod
        def Client(client_id=None, protocol=None):
            return fake_client

    monkeypatch.setattr(mqtt_client, "mqtt", FakeMqttModule)


def test_topic_matches_mqtt_hash_wildcard():
    assert _topic_matches("cloud/task/result/#", "cloud/task/result/classroom-301")
    assert _topic_matches("edge/task/request/#", "edge/task/request/classroom-301")
    assert not _topic_matches("cloud/task/result/#", "cloud/task/request/classroom-301")


def test_mqtt_dispatches_wildcard_messages(monkeypatch):
    fake_client = FakePahoClient()
    install_fake_paho(monkeypatch, fake_client)

    async def scenario():
        seen = []
        client = MqttClient("127.0.0.1", 1883, "edge-atlas-01")
        client._loop = asyncio.get_running_loop()

        async def handler(topic, payload):
            seen.append((topic, payload))

        await client.subscribe("cloud/task/result/#", 1, handler)
        await client.connect()
        fake_client.on_message(
            fake_client,
            None,
            FakePahoMessage("cloud/task/result/classroom-301", b"payload"),
        )
        await asyncio.sleep(0)
        return seen

    assert run(scenario()) == [("cloud/task/result/classroom-301", "payload")]


def test_pending_subscriptions_are_instance_scoped(monkeypatch):
    first_fake = FakePahoClient()
    install_fake_paho(monkeypatch, first_fake)

    async def handler(topic, payload):
        return None

    first = MqttClient("127.0.0.1", 1883, "edge-first")
    run(first.subscribe("edge/task/request/#", 1, handler))

    second_fake = FakePahoClient()
    install_fake_paho(monkeypatch, second_fake)
    second = MqttClient("127.0.0.1", 1883, "edge-second")
    second._on_connect(second_fake, None, None, 0)

    assert second_fake.subscriptions == []


def test_reconnect_restores_client_subscriptions(monkeypatch):
    fake_client = FakePahoClient()
    install_fake_paho(monkeypatch, fake_client)

    async def handler(topic, payload):
        return None

    client = MqttClient("127.0.0.1", 1883, "edge-atlas-01")
    run(client.subscribe("cloud/task/result/#", 1, handler))
    run(client.connect())

    assert fake_client.subscriptions == [("cloud/task/result/#", 1)]
