import grpc
from anycast_pb2 import Request
from anycast_pb2_grpc import AnycastServiceStub


def run():
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = AnycastServiceStub(channel)
        request = Request(command="volta 1 www.google.com", settings="{}")
        response = stub.UserRequest(request)
        if response.code == 200:
            print("User details received:\n", response.output)
        else:
            print("Error:\n", response.output)


if __name__ == '__main__':
    run()
