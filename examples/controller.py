"""
examples/controller.py

Simple example of a Voltadomar controller.
The user specifies the port, range of session IDs, and session ID block size.

For example, the user allocates a range of session IDs from 1000 to 2000 with
a block size of 100. So, the first program will get session IDs from 1000 to 1099,
the second program will get session IDs from 1100 to 1199, and so on.

Usage:
    python controller.py --port <port> --range <start-end> --block <block_size>

Arguments:
    --port <port>            Port to run the server on (default: 50051)
    --range <start-end>      Controller session ID allocation range (e.g., 1000-2000)
    --block <block_size>     Session ID block size per program

Example:
    python controller.py --port 50051 --range 10000-20000 --block 100

Author: David Song <davsong@cs.washington.edu>
"""

import argparse
import asyncio

from voltadomar import Controller


def main():
    """Parses arguments and starts the server."""
    parser = argparse.ArgumentParser(description="Run the Anycast gRPC server.")
    parser.add_argument(
        "--port",
        type=int,
        default=50051,
        help="Port to run the server on (default: 50051)"
    )
    parser.add_argument(
        "--range",
        type=str,
        required=True,
        help="Controller session ID allocation range (e.g., 1000-2000)",
        metavar="START-END"
    )
    parser.add_argument(
        "--block",
        type=int,
        required=True,
        help="Session ID block size per program"
    )
    args = parser.parse_args()

    try:
        start_str, end_str = args.range.split('-')
        start = int(start_str)
        end = int(end_str)
        if not (0 <= start < end):
            raise ValueError("Invalid range: Start ID must be non-negative and less than end ID.")
        if args.block <= 0:
            raise ValueError("Block size must be positive.")
        if (start + args.block) > end and end - start > 0:
            print(f"Block size {args.block} is larger than the available range {args.range}. Only one program can run concurrently.")
        elif (end - start) < args.block:
            print(f"The range {args.range} is smaller than the block size {args.block}.")

    except ValueError as e:
        parser.error(f"Invalid argument: {e}")

    controller = Controller(port=args.port, start_id=start, end_id=end, block_size=args.block)
    try:
        asyncio.run(controller.run())
    except KeyboardInterrupt:
        print("Agent stopped by user.")


if __name__ == "__main__":
    main()
