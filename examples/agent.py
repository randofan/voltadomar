"""
examples/agent.py

Simple example of a Voltadomar agent that connects to a controller.
The user specifies the agent ID and the controller address.

Usage:
    python agent.py -i <agent_id> -c <controller_address>

Arguments:
    -i, --agent-id <agent_id>       The unique ID for this agent (defaults to hostname)
    -c, --controller-address <address>  The address (host:port) of the controller gRPC service

Example:
    python agent.py -i agent1 -c 127.0.0.1:50051

Author: David Song <davsong@cs.washington.edu>
"""

import asyncio
import argparse
import socket

from voltadomar import Agent

# TODO move arguments to a config file


def main():
    """Parses arguments and runs the agent."""
    parser = argparse.ArgumentParser(description="Voltadomar Agent")
    parser.add_argument(
        "-i", "--agent-id",
        default=socket.gethostname(),
        help="The unique ID for this agent (defaults to hostname)"
    )
    parser.add_argument(
        "-c", "--controller-address",
        default="127.0.0.1:50051",
        help="The address (host:port) of the controller gRPC service"
    )
    args = parser.parse_args()

    agent = Agent(agent_id=args.agent_id, controller_address=args.controller_address)
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        print("Agent stopped by user.")


if __name__ == "__main__":
    main()
