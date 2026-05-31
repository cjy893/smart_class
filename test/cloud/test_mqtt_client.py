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


def test_topic_matches_mqtt_hash_wildcard():
    assert _topic_matches("cloud/task/request/#", "cloud/task/request/classroom-301")
    assert not _topic_matches("cloud/task/request/#", "cloud/task/result/classroom-301")


def test_mqtt_reconnect_restores_pending_subscriptions(monkeypatch):
    fake_client = FakePahoClient()

    class FakeMqttModule:
        MQTTv311 = object()

        @staticmethod
        def Client(client_id=None, protocol=None):
            return fake_client

    monkeypatch.setattr(mqtt_client, "mqtt", FakeMqttModule)
    client = MqttClient("192.168.137.2", 1883, "cloud-main")

    async def handler(topic, payload):
        return None

    run(client.subscribe("cloud/task/request/#", 1, handler))
    fake_client.on_connect(fake_client, None, None, 0)

    assert fake_client.subscriptions == [("cloud/task/request/#", 1)]


def test_mqtt_dispatches_wildcard_messages(monkeypatch):
    fake_client = FakePahoClient()

    class FakeMqttModule:
        MQTTv311 = object()

        @staticmethod
        def Client(client_id=None, protocol=None):
            return fake_client

    monkeypatch.setattr(mqtt_client, "mqtt", FakeMqttModule)

    async def scenario():
        seen = []
        client = MqttClient("192.168.137.2", 1883, "cloud-main")
        client._loop = asyncio.get_running_loop()

        async def handler(topic, payload):
            seen.append((topic, payload))

        await client.subscribe("cloud/task/request/#", 1, handler)
        fake_client.on_message(
            fake_client,
            None,
            FakePahoMessage("cloud/task/request/classroom-301", b"payload"),
        )
        await asyncio.sleep(0)
        return seen

    assert run(scenario()) == [("cloud/task/request/classroom-301", "payload")]
