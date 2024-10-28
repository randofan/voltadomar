import grpc
import command_service_pb2
import command_service_pb2_grpc


def run(command):
    with grpc.insecure_channel('192.0.2.113:50051') as channel:
        stub = command_service_pb2_grpc.CommandServiceStub(channel)
        request = command_service_pb2.CommandRequest(command=command)

        response = stub.RunCommand(request)
        print("Output:", response.output)
        print("Error:", response.error)


if __name__ == '__main__':
    command = input("Enter command to execute: ")
    run(command)
