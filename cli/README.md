# Voltadomar CLI

A GoLang CLI client for the Voltadomar distributed network measurement system. This CLI tool replaces the existing Python client implementation while providing the same functionality and command-line interface.

## Overview

This is a standalone GoLang CLI application that communicates with the Voltadomar controller via gRPC to perform distributed traceroute measurements. It provides a drop-in replacement for the Python client with enhanced performance and better error handling.

## Features

- **Full Python Client Compatibility**: Replicates all functionality of the original Python client
- **Flexible Argument Parsing**: Supports flags before or after positional arguments
- **Comprehensive Error Handling**: Detailed error messages and validation
- **gRPC Communication**: Connects to Voltadomar controller via gRPC protocol
- **Multiple Runs Support**: Execute multiple traceroute measurements sequentially

## Installation

### Prerequisites

- Go 1.21 or higher
- Protocol Buffers compiler (`protoc`) for development
- Access to a running Voltadomar controller

### Building from Source

```bash
# Navigate to the CLI directory
cd cli

# Install dependencies
go mod tidy

# Build the CLI
go build -o voltadomar-cli ./cmd/voltadomar-cli
```

## Usage

### Basic Syntax

```bash
./voltadomar-cli <source> <destination> [runs] [options]
```

### Arguments

- **source**: The anycast source node (agent ID)
- **destination**: The destination address to traceroute to  
- **runs**: Number of traceroute runs to perform (default: 1)

### Options

- `-c, --controller string`: Controller address (default: localhost:50051)
- `-h, --help`: Show help message

### Examples

```bash
# Basic traceroute
./voltadomar-cli agent1 8.8.8.8

# Multiple runs
./voltadomar-cli agent1 8.8.8.8 3

# Custom controller
./voltadomar-cli agent1 8.8.8.8 1 -c controller.example.com:50051

# Flags can be placed anywhere
./voltadomar-cli -c controller.example.com:50051 agent1 8.8.8.8 3
```

## Comparison with Python Client

The GoLang CLI provides identical functionality to the Python client:

| Feature | Python Client | GoLang CLI | Status |
|---------|---------------|------------|--------|
| Command-line interface | ✅ | ✅ | Identical |
| gRPC communication | ✅ | ✅ | Compatible |
| Multiple runs | ✅ | ✅ | Same behavior |
| Error handling | ✅ | ✅ | Enhanced |
| Flag parsing | ✅ | ✅ | More flexible |
| Output format | ✅ | ✅ | Consistent |

### Migration from Python Client

Replace your Python client calls:

```bash
# Old Python client
python examples/client.py agent1 8.8.8.8 3 --controller localhost:50051

# New GoLang CLI
./cli/voltadomar-cli agent1 8.8.8.8 3 --controller localhost:50051
```

## Development

### Project Structure

```
cli/
├── cmd/voltadomar-cli/     # Main CLI application
│   └── main.go            # Entry point and CLI logic
├── proto/anycast/         # Protocol buffer definitions
│   ├── anycast.proto      # gRPC service definition
│   ├── anycast.pb.go      # Generated protobuf code
│   └── anycast_grpc.pb.go # Generated gRPC code
├── go.mod                 # Go module definition
├── go.sum                 # Dependency checksums
└── README.md             # This file
```

### Regenerating Protocol Buffers

If the `.proto` file changes:

```bash
cd cli
protoc --go_out=. --go_opt=paths=source_relative \
       --go-grpc_out=. --go-grpc_opt=paths=source_relative \
       proto/anycast/anycast.proto
```

### Testing

```bash
# Build and test basic functionality
cd cli
go build -o voltadomar-cli ./cmd/voltadomar-cli
./voltadomar-cli -h

# Test with a running controller
./voltadomar-cli agent1 8.8.8.8 1 -c localhost:50051
```

## Error Handling

The CLI provides comprehensive error handling:

- **Invalid arguments**: Clear error messages for missing or invalid parameters
- **Connection errors**: Detailed gRPC error reporting
- **Validation**: Input validation for controller addresses and run counts
- **Graceful failures**: Continues with remaining runs if individual attempts fail

## License

This project follows the same license as the main Voltadomar project.
