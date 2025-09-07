"""
examples/client.py

Simple example client for running anycast traceroute with Voltadomar Go controller.

Usage:
    python client.py <source> <destination> [runs]

Arguments:
    source (str): The source anycast node to send the traceroute from.
    destination (str): The destination address to send the traceroute to.
    runs (int): Number of traceroute runs to perform (default: 1).

Example:
    python client.py agent1 8.8.8.8 3

Requirements:
    pip install grpcio grpcio-tools protobuf

Author: David Song <davsong@cs.washington.edu>
"""

import grpc
import argparse
import sys
import os

# Add the proto directory to the path so we can import the generated files
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src', 'voltadomar', 'proto', 'anycast'))

try:
    import anycast_pb2 as pb
    import anycast_pb2_grpc as pb_grpc
except ImportError:
    print("Error: Could not import gRPC generated files.")
    print("Make sure you have generated the Python gRPC files from the .proto file.")
    print("Run: cd src/voltadomar && python -m grpc_tools.protoc --python_out=proto/anycast --grpc_python_out=proto/anycast -I proto/anycast proto/anycast/anycast.proto")
    sys.exit(1)


def run(source, destination, runs, controller_address='localhost:50051'):
    """Run traceroute measurements using the Go controller."""
    print(f"Connecting to Voltadomar controller at {controller_address}...")

    with grpc.insecure_channel(controller_address) as channel:
        stub = pb_grpc.AnycastServiceStub(channel)

        for i in range(runs):
            print(f"\n--- Traceroute {i+1}/{runs} ---")
            print(f"Running: volta {source} {destination}")

            # Create the request
            request = pb.Request(command=f"volta {source} {destination}")

            try:
                # Send the request to the controller
                response = stub.UserRequest(request)

                if response.code == 200:
                    print("Traceroute completed successfully:")
                    print(response.output)
                else:
                    print(f"Error (code {response.code}):")
                    print(response.output)

            except grpc.RpcError as e:
                print(f"gRPC error: {e.code()} - {e.details()}")
            except Exception as e:
                print(f"Unexpected error: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Client for Voltadomar Anycast Traceroute')
    parser.add_argument('source', type=str, help='The anycast source node (agent ID)')
    parser.add_argument('destination', type=str, help='The destination address to traceroute to')
    parser.add_argument('runs', type=int, nargs='?', default=1, help='Number of traceroute runs to perform (default: 1)')
    parser.add_argument('-c', '--controller', type=str, default='localhost:50051',
                       help='Controller address (default: localhost:50051)')

    args = parser.parse_args()

    print("Voltadomar Traceroute Client")
    print(f"Source: {args.source}")
    print(f"Destination: {args.destination}")
    print(f"Runs: {args.runs}")
    print(f"Controller: {args.controller}")

    run(args.source, args.destination, args.runs, args.controller)
