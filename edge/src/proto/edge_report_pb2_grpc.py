from proto import edge_report_pb2 as edge__report__pb2


class EdgeReportStub:
    """gRPC client stub for EdgeReport service."""

    def __init__(self, channel):
        import grpc
        self.ReportStatus = grpc.unary_unary(
            "/smart_class.cloud.EdgeReport/ReportStatus",
            request_serializer=edge__report__pb2.StatusReport.SerializeToString,
            response_deserializer=edge__report__pb2.Ack.FromString,
        )(channel)
        self.Heartbeat = grpc.unary_unary(
            "/smart_class.cloud.EdgeReport/Heartbeat",
            request_serializer=edge__report__pb2.HeartbeatRequest.SerializeToString,
            response_deserializer=edge__report__pb2.Ack.FromString,
        )(channel)


class EdgeReportServicer:
    def ReportStatus(self, request, context):
        raise NotImplementedError()

    def Heartbeat(self, request, context):
        raise NotImplementedError()


def add_EdgeReportServicer_to_server(servicer, server):
    import grpc

    rpc_method_handlers = {
        "ReportStatus": grpc.unary_unary_rpc_method_handler(
            servicer.ReportStatus,
            request_deserializer=edge__report__pb2.StatusReport.FromString,
            response_serializer=edge__report__pb2.Ack.SerializeToString,
        ),
        "Heartbeat": grpc.unary_unary_rpc_method_handler(
            servicer.Heartbeat,
            request_deserializer=edge__report__pb2.HeartbeatRequest.FromString,
            response_serializer=edge__report__pb2.Ack.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "smart_class.cloud.EdgeReport",
        rpc_method_handlers,
    )
    server.add_generic_rpc_handlers((generic_handler,))
