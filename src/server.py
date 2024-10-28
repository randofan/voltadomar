import grpc
from concurrent import futures
import subprocess
import command_service_pb2
import command_service_pb2_grpc


class CommandServiceServicer(command_service_pb2_grpc.CommandServiceServicer):
    def RunCommand(self, request, context):
        try:
            result = subprocess.run(request.command, shell=True, capture_output=True, text=True)
            output = result.stdout
            error = result.stderr
        except Exception as e:
            output = ""
            error = str(e)
        return command_service_pb2.CommandResponse(output=output, error=error)


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    command_service_pb2_grpc.add_CommandServiceServicer_to_server(CommandServiceServicer(), server)
    server.add_insecure_port('0.0.0.0:50051')
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
