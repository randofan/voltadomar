#!/bin/bash
# examples/agent.sh
#
# Simple example script for running the Voltadomar Go agent.
# The user specifies the agent ID and the controller address.
#
# Usage:
#     ./agent.sh -i <agent_id> -c <controller_address>
#
# Arguments:
#     -i, --agent-id <agent_id>       The unique ID for this agent (defaults to hostname)
#     -c, --controller-address <address>  The address (host:port) of the controller gRPC service
#
# Example:
#     ./agent.sh -i agent1 -c 127.0.0.1:50051
#
# Author: David Song <davsong@cs.washington.edu>

set -e

# Default values
AGENT_ID=""
CONTROLLER_ADDRESS="127.0.0.1:50051"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -i|--agent-id)
            AGENT_ID="$2"
            shift 2
            ;;
        -c|--controller-address)
            CONTROLLER_ADDRESS="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Voltadomar Agent - Distributed anycast network measurement agent"
            echo ""
            echo "Options:"
            echo "  -i, --agent-id <agent_id>           The unique ID for this agent (defaults to hostname)"
            echo "  -c, --controller-address <address>  The address (host:port) of the controller gRPC service"
            echo "  -h, --help                          Show this help message"
            echo ""
            echo "Example:"
            echo "  $0 -i agent1 -c 127.0.0.1:50051"
            echo ""
            echo "Note: This program requires root privileges for raw socket operations."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Set default agent ID to hostname if not provided
if [[ -z "$AGENT_ID" ]]; then
    AGENT_ID=$(hostname)
fi

# Validate controller address
if [[ -z "$CONTROLLER_ADDRESS" ]]; then
    echo "Error: Controller address is required"
    exit 1
fi

echo "Starting Voltadomar Agent"
echo "Agent ID: $AGENT_ID"
echo "Controller Address: $CONTROLLER_ADDRESS"

# Check if running as root (required for raw sockets)
if [[ $EUID -ne 0 ]]; then
    echo "Warning: Not running as root. Raw socket operations may fail."
    echo "Consider running with sudo for full functionality."
fi

# Build the agent if it doesn't exist
AGENT_BINARY="src/voltadomar/agent-binary"
if [[ ! -f "$AGENT_BINARY" ]]; then
    echo "Building agent binary..."
    cd src/voltadomar
    export PATH=$PATH:$(go env GOPATH)/bin
    go build -o agent-binary ./cmd/agent
    cd ../..
fi

# Run the agent
echo "Starting agent..."
exec "$AGENT_BINARY" -i "$AGENT_ID" -c "$CONTROLLER_ADDRESS"
