import sys
import types


def pytest_configure():
    client_module = types.ModuleType("paho.mqtt.client")
    client_module.MQTTv311 = object()
    client_module.Client = lambda client_id=None, protocol=None: None

    mqtt_module = types.ModuleType("paho.mqtt")
    mqtt_module.client = client_module

    paho_module = types.ModuleType("paho")
    paho_module.mqtt = mqtt_module

    sys.modules.setdefault("paho", paho_module)
    sys.modules.setdefault("paho.mqtt", mqtt_module)
    sys.modules.setdefault("paho.mqtt.client", client_module)
