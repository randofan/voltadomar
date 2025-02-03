'''
This is a sample client for Anycast Traceroute using gRPC.

Usage:
    python client.py <source> <destination>

Arguments:
    source (str): The source anycase node to send the traceroute from.
    destination (str): The destination address to send the traceroute to.

Example:
    python client.py 1 8.8.8.8
'''

import grpc
import argparse

from anycast.anycast_pb2 import Request
from anycast.anycast_pb2_grpc import AnycastServiceStub


def run(source, destination):
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = AnycastServiceStub(channel)
        request = Request(command=f"volta {source} {destination}")
        response = stub.UserRequest(request)
        if response.code == 200:
            print("User details received:\n", response.output)
        else:
            print("Error:\n", response.output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Client for Anycast Traceroute')
    parser.add_argument('source', type=str, help='The anycast source node')
    parser.add_argument('destination', type=str, help='The destination address')
    args = parser.parse_args()
    run(args.source, args.destination)
