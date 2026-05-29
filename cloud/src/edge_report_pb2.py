"""Minimal checked-in protobuf message classes for EdgeReport.

This mirrors cloud/proto/edge_report.proto so deployments do not need to run
grpcio-tools during startup.
"""

from google.protobuf import descriptor_pb2
from google.protobuf import descriptor_pool
from google.protobuf import message_factory


DESCRIPTOR = descriptor_pool.Default()


def _register_file():
    file_proto = descriptor_pb2.FileDescriptorProto()
    file_proto.name = "edge_report.proto"
    file_proto.package = "smart_class.cloud"
    file_proto.syntax = "proto3"

    status = file_proto.message_type.add()
    status.name = "StatusReport"
    _field(status, "edge_id", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    _field(status, "cpu_percent", 2, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    _field(status, "npu_percent", 3, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    _field(status, "memory_mb", 4, descriptor_pb2.FieldDescriptorProto.TYPE_DOUBLE)
    _field(status, "task_queue_depth", 5, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)
    _field(status, "connected_devices", 6, descriptor_pb2.FieldDescriptorProto.TYPE_INT32)
    _field(status, "timestamp", 7, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    heartbeat = file_proto.message_type.add()
    heartbeat.name = "HeartbeatRequest"
    _field(heartbeat, "edge_id", 1, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)
    _field(heartbeat, "timestamp", 2, descriptor_pb2.FieldDescriptorProto.TYPE_STRING)

    ack = file_proto.message_type.add()
    ack.name = "Ack"
    _field(ack, "ok", 1, descriptor_pb2.FieldDescriptorProto.TYPE_BOOL)

    service = file_proto.service.add()
    service.name = "EdgeReport"
    method = service.method.add()
    method.name = "ReportStatus"
    method.input_type = ".smart_class.cloud.StatusReport"
    method.output_type = ".smart_class.cloud.Ack"
    method = service.method.add()
    method.name = "Heartbeat"
    method.input_type = ".smart_class.cloud.HeartbeatRequest"
    method.output_type = ".smart_class.cloud.Ack"

    try:
        DESCRIPTOR.Add(file_proto)
    except Exception:
        pass


def _field(message, name, number, field_type):
    field = message.field.add()
    field.name = name
    field.number = number
    field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
    field.type = field_type


_register_file()

StatusReport = message_factory.GetMessageClass(
    DESCRIPTOR.FindMessageTypeByName("smart_class.cloud.StatusReport")
)
HeartbeatRequest = message_factory.GetMessageClass(
    DESCRIPTOR.FindMessageTypeByName("smart_class.cloud.HeartbeatRequest")
)
Ack = message_factory.GetMessageClass(
    DESCRIPTOR.FindMessageTypeByName("smart_class.cloud.Ack")
)
