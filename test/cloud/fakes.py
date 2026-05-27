import json


class FakeMqttClient:
    def __init__(self):
        self.connected = False
        self.subscriptions = []
        self.published = []
        self.handlers = {}

    async def connect(self):
        self.connected = True

    async def subscribe(self, topic, qos, handler):
        self.subscriptions.append((topic, qos))
        self.handlers[topic] = handler

    async def publish(self, topic, payload, qos=0):
        self.published.append((topic, json.loads(payload), qos))

    async def disconnect(self):
        self.connected = False


class FakeBehaviorEngine:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {
            "total_detected": 2,
            "hand_up": 1,
            "standing": 0,
            "head_down": 0,
            "talking": 1,
        }

    async def analyze(self, image_bytes, params=None):
        self.calls.append((image_bytes, params or {}))
        return self.result


class FakeReportGenerator:
    def __init__(self):
        self.calls = []

    def generate(self, payload):
        self.calls.append(payload)
        return {
            "report_url": "/reports/report.html",
            "summary": {"avg_count": 31, "behavior_events": 2},
        }


class FakeMetricsProvider:
    def __init__(self):
        self.queue_depth = 3

    def snapshot(self):
        return {
            "cpu_percent": 55.0,
            "gpu_percent": 40.0,
            "memory_mb": 4096,
        }
