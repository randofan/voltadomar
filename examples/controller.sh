#!/bin/bash
# examples/controller.sh
#
# Simple example script for running the Voltadomar Go controller.
# The user specifies the port, range of session IDs, and session ID block size.
#
# For example, the user allocates a range of session IDs from 1000 to 2000 with
# a block size of 100. So, the first program will get session IDs from 1000 to 1099,
# the second program will get session IDs from 1100 to 1199, and so on.
#
# Usage:
#     ./controller.sh --port <port> --range <start-end> --block <block_size>
#
# Arguments:
#     --port <port>            Port to run the server on (default: 50051)
#     --range <start-end>      Controller session ID allocation range (e.g., 1000-2000)
#     --block <block_size>     Session ID block size per program
#
# Example:
#     ./controller.sh --port 50051 --range 10000-20000 --block 100
#
# Author: David Song <davsong@cs.washington.edu>

set -e

# Default values
PORT=50051
RANGE=""
BLOCK=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --port)
            PORT="$2"
            shift 2
            ;;
        --range)
            RANGE="$2"
            shift 2
            ;;
        --block)
            BLOCK="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Voltadomar Controller - Distributed anycast network measurement controller"
            echo ""
            echo "Options:"
            echo "  --port <port>        Port to run the server on (default: 50051)"
            echo "  --range <start-end>  Controller session ID allocation range (e.g., 1000-2000)"
            echo "  --block <block_size> Session ID block size per program"
            echo "  -h, --help          Show this help message"
            echo ""
            echo "Example:"
            echo "  $0 --port 50051 --range 10000-20000 --block 100"
            echo ""
            echo "The controller manages session ID allocation and coordinates measurement"
            echo "tasks between user clients and distributed agents."
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Validate required parameters
if [[ -z "$RANGE" ]]; then
    echo "Error: Range parameter is required (e.g., --range 1000-2000)"
    exit 1
fi

if [[ -z "$BLOCK" ]]; then
    echo "Error: Block size parameter is required (e.g., --block 100)"
    exit 1
fi

# Validate range format
if [[ ! "$RANGE" =~ ^[0-9]+-[0-9]+$ ]]; then
    echo "Error: Invalid range format. Use format: START-END (e.g., 1000-2000)"
    exit 1
fi

# Extract start and end from range
IFS='-' read -r START END <<< "$RANGE"

# Validate range values
if [[ $START -lt 0 ]]; then
    echo "Error: Start ID must be non-negative"
    exit 1
fi

if [[ $START -ge $END ]]; then
    echo "Error: Start ID must be less than end ID"
    exit 1
fi

if [[ $BLOCK -le 0 ]]; then
    echo "Error: Block size must be positive"
    exit 1
fi

# Check if block size is reasonable for the range
RANGE_SIZE=$((END - START))
if [[ $BLOCK -gt $RANGE_SIZE ]]; then
    echo "Warning: Block size $BLOCK is larger than the available range $RANGE_SIZE. Only one program can run concurrently."
fi

echo "Starting Voltadomar Controller"
echo "Port: $PORT"
echo "Session ID Range: $START-$END"
echo "Block Size: $BLOCK"

# Build the controller if it doesn't exist
CONTROLLER_BINARY="src/voltadomar/controller-binary"
if [[ ! -f "$CONTROLLER_BINARY" ]]; then
    echo "Building controller binary..."
    cd src/voltadomar
    export PATH=$PATH:$(go env GOPATH)/bin
    go build -o controller-binary ./cmd/controller
    cd ../..
fi

# Run the controller
echo "Starting controller..."
exec "$CONTROLLER_BINARY" --port "$PORT" --range "$RANGE" --block "$BLOCK"
