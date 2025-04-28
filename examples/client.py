"""
examples/client.py

Simple example client for running anycast traceroute with Voltadomar.

Usage:
    python client.py <source> <destination>

Arguments:
    source (str): The source anycast node to send the traceroute from.
    destination (str): The destination address to send the traceroute to.

Example:
    python client.py agent1 8.8.8.8

Author: David Song <davsong@cs.washington.edu>
"""

import grpc
import argparse

from voltadomar import Request, AnycastServiceStub


def run(source, destination, runs):
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = AnycastServiceStub(channel)
        for i in range(runs):
            print(f"Sending request {i}/{runs}...")
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
    parser.add_argument('runs', type=int, help='Number of runs to perform')
    args = parser.parse_args()
    run(args.source, args.destination, args.runs)
