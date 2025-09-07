# Voltadomar API Reference

This document provides comprehensive API documentation for the Voltadomar Go implementation - a distributed anycast network measurement toolkit.

## Overview

Voltadomar is a high-performance Go-based system for performing distributed network traceroute measurements across anycast networks. It uses a controller-agent architecture with gRPC communication to coordinate network probing operations.

## Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [gRPC Protocol](#grpc-protocol)
- [Controller Package](#controller-package)
- [Agent Package](#agent-package)
- [Packets Package](#packets-package)
- [Command-Line Tools](#command-line-tools)
- [Client Integration](#client-integration)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)

## Installation

### Prerequisites

- Go 1.21 or higher
- Protocol Buffers compiler (`protoc`) for development
- Root/administrator privileges for raw socket operations
- Linux-based OS recommended

### Building from Source

```bash
git clone https://github.com/randofan/voltadomar.git
cd voltadomar/src/voltadomar

# Install dependencies
go mod tidy

# Generate gRPC code (if needed)
go generate ./...

# Build binaries
go build -o controller-binary ./cmd/controller
go build -o agent-binary ./cmd/agent
```

### Running Tests

```bash
# Run all tests
go test ./...

# Run tests with verbose output
go test -v ./...

# Run specific package tests
go test ./pkg/packets -v
go test ./internal/controller -v
go test ./internal/agent -v
```

## Quick Start

### 1. Start the Controller

```bash
# Using the example script
./examples/controller.sh --port 50051 --range 10000-20000 --block 100

# Or directly with the binary
./controller-binary --port 50051 --range 10000-20000 --block 100
```

### 2. Start an Agent

```bash
# Using the example script (requires root for raw sockets)
sudo ./examples/agent.sh -i agent1 -c localhost:50051

# Or directly with the binary
sudo ./agent-binary -i agent1 -c localhost:50051
```

### 3. Run a Traceroute

```bash
# Using the Python client
python examples/client.py agent1 8.8.8.8 1

# Or using any gRPC client with the command: "volta agent1 8.8.8.8"
```

## gRPC Protocol

Voltadomar uses gRPC for communication between components. The service definition is `AnycastService` located in `proto/anycast/anycast.proto`.

### Service Definition

```protobuf
service AnycastService {
  rpc ControlStream(stream Message) returns (stream Message);
  rpc UserRequest(Request) returns (Response);
}
```

### RPC Methods

#### ControlStream

```protobuf
rpc ControlStream(stream Message) returns (stream Message);
```

Bidirectional streaming RPC between agents and the controller.

**Agent → Controller Messages:**
- `REGISTER`: Agent registration with unique ID
- `DONE`: Job completion with UDP acknowledgments
- `REPLY`: ICMP packet replies from network probes
- `ERROR`: Error reporting

**Controller → Agent Messages:**
- `JOB`: Measurement job instructions

#### UserRequest

```protobuf
rpc UserRequest(Request) returns (Response);
```

Unary RPC for clients to request measurement programs.

**Request Format:**
```protobuf
message Request {
  string command = 1; // e.g., "volta agent1 8.8.8.8"
}
```

**Response Format:**
```protobuf
message Response {
  int32 code = 1;    // HTTP-style status code
  string output = 2; // Formatted results or error message
}
```

### Message Structure

All `ControlStream` communication uses the `Message` wrapper:

```protobuf
message Message {
  google.protobuf.Any payload = 1;    // Serialized payload message with embedded type information
}
```

The message type is determined from the `TypeUrl` field of the `google.protobuf.Any` payload, eliminating redundant type information. This design:

- **Reduces Protocol Overhead**: Eliminates duplicate type information
- **Improves Type Safety**: Uses protobuf's built-in type system
- **Simplifies Message Handling**: Single payload field with embedded type information
- **Maintains Backward Compatibility**: Standard protobuf Any mechanism

### Message Types and Payloads

#### Register
```protobuf
message Register {
  string agent_id = 1;
}
```
**TypeUrl:** `"type.googleapis.com/Register"`
**Direction:** Agent → Controller
**Purpose:** Agent registration with unique identifier

#### Job
```protobuf
message Job {
  int32 session_id = 1;  // Session identifier
  string dst_ip = 2;     // Target IP address
  int32 max_ttl = 3;     // Maximum TTL value
  int32 probe_num = 4;   // Probes per TTL
  int32 base_port = 5;   // Base port for sequence calculation
}
```
**TypeUrl:** `"type.googleapis.com/Job"`
**Direction:** Controller → Agent
**Purpose:** Measurement job instructions

#### Done
```protobuf
message Done {
  int32 session_id = 1;
  repeated UdpAck udp_acks = 2;
}

message UdpAck {
  int32 seq = 1;
  string sent_time = 2;  // RFC3339Nano format
}
```
**TypeUrl:** `"type.googleapis.com/Done"`
**Direction:** Agent → Controller
**Purpose:** Job completion notification with probe acknowledgments

#### Reply
```protobuf
message Reply {
  bytes raw_packet = 1;  // Raw ICMP packet bytes
  string time = 2;       // RFC3339Nano timestamp
}
```
**TypeUrl:** `"type.googleapis.com/Reply"`
**Direction:** Agent → Controller
**Purpose:** ICMP reply forwarding

#### Error
```protobuf
message Error {
  int32 code = 1;
  string message = 2;
}
```
**TypeUrl:** `"type.googleapis.com/Error"`
**Direction:** Bidirectional
**Purpose:** Error reporting

## Controller Package

**Package:** `github.com/randofan/voltadomar/internal/controller`

The controller package implements the central coordination server for the Voltadomar system. It manages agent connections, handles user requests, and orchestrates measurement program execution.

### Architecture

The controller uses a session-based architecture where each measurement program receives a unique session ID block for probe identification. It maintains concurrent-safe maps for agent connections and active programs, using Go's built-in synchronization primitives.

### Controller Struct

```go
type Controller struct {
    // Configuration
    port      int
    startID   int32
    endID     int32
    blockSize int32

    // Session management
    nextSessionID int32
    inUseBlocks   map[int32]bool

    // Runtime state
    agentStreams map[string]pb.AnycastService_ControlStreamServer
    programs     map[int32]Program

    // Synchronization
    mu sync.RWMutex

    // gRPC server
    server *grpc.Server
}
```

### Constructor

```go
func NewController(port int, startID, endID, blockSize int32) *Controller
```

Creates a new controller instance with the specified configuration.

**Parameters:**
- `port`: gRPC server port
- `startID`: Starting session ID for allocation range
- `endID`: Ending session ID for allocation range (exclusive)
- `blockSize`: Size of ID blocks allocated per program

**Example:**
```go
controller := NewController(50051, 1000, 2000, 100)
```

### Methods

#### AllocateSessionID

```go
func (c *Controller) AllocateSessionID() (int32, error)
```

Allocates a new session ID block using a sliding window approach. Searches for available blocks starting from the next expected position and wraps around the configured range if necessary.

**Returns:**
- `int32`: Starting ID of the allocated block
- `error`: Error if no blocks are available

**Thread Safety:** This method is thread-safe using read-write mutex protection.

#### ReleaseSessionID

```go
func (c *Controller) ReleaseSessionID(sessionID int32)
```

Releases a previously allocated session ID block, making it available for future allocations.

**Parameters:**
- `sessionID`: Starting ID of the block to release

#### SendJob

```go
func (c *Controller) SendJob(agentID string, jobPayload *pb.JobPayload) error
```

Sends a job payload to a specific agent via its gRPC stream.

**Parameters:**
- `agentID`: Target agent identifier
- `jobPayload`: Job instructions

**Returns:**
- `error`: Error if agent not found or send fails

**Example:**
```go
jobPayload := &pb.JobPayload{
    SessionId: 1000,
    DstIp:     "8.8.8.8",
    MaxTtl:    20,
    ProbeNum:  3,
    BasePort:  1000,
}
err := controller.SendJob("agent1", jobPayload)
```

#### Run

```go
func (c *Controller) Run() error
```

Starts the gRPC server and blocks until termination. This method should be called in the main goroutine.

**Returns:**
- `error`: Server startup or runtime error

#### Stop

```go
func (c *Controller) Stop()
```

Gracefully stops the gRPC server and cleans up resources.

### gRPC Service Implementation

The controller implements the `AnycastService` gRPC service:

#### ControlStream

```go
func (c *Controller) ControlStream(stream pb.AnycastService_ControlStreamServer) error
```

Handles bidirectional streaming with agents. Processes incoming messages and maintains agent connection state.

**Message Flow:**
1. Agent sends `REGISTER` message
2. Controller stores agent stream reference
3. Agent receives `JOB` messages
4. Agent sends `DONE` and `REPLY` messages
5. Controller routes messages to appropriate programs

#### UserRequest

```go
func (c *Controller) UserRequest(ctx context.Context, request *pb.Request) (*pb.Response, error)
```

Handles user measurement requests. Parses commands, allocates resources, executes programs, and returns formatted results.

**Supported Commands:**
- `volta <source_agent> <destination> [options]`

**Example:**
```go
request := &pb.Request{Command: "volta agent1 8.8.8.8"}
response, err := controller.UserRequest(ctx, request)
```

### Session ID Management

The controller manages session IDs using a sliding window allocation strategy:

1. **Range Definition**: Session IDs are allocated within `[startID, endID)` range
2. **Block Allocation**: Each program receives a contiguous block of `blockSize` IDs
3. **Sliding Window**: Allocation starts from the next available position after the last allocation
4. **Wraparound**: When reaching the end of the range, allocation wraps to the beginning
5. **Conflict Resolution**: In-use blocks are tracked to prevent double allocation

**Session ID Usage:**
- Base session ID identifies the measurement program
- Individual probe IDs are calculated as `sessionID + sequenceNumber`
- UDP source ports use probe IDs for reply matching

### Program Interface

**Package:** `github.com/randofan/voltadomar/internal/controller`

The Program interface defines the contract for measurement programs executed by the controller.

```go
type Program interface {
    Run() (string, error)
    HandleDone(payload *pb.DonePayload)
    HandleReply(payload *pb.ReplyPayload, agentID string) bool
}
```

#### Methods

**Run**
```go
Run() (string, error)
```
Executes the measurement program and returns formatted results.

**HandleDone**
```go
HandleDone(payload *pb.DonePayload)
```
Processes job completion messages from agents.

**HandleReply**
```go
HandleReply(payload *pb.ReplyPayload, agentID string) bool
```
Processes ICMP reply messages. Returns `true` if the reply belongs to this program.

### ControllerInterface

Programs interact with the controller through this interface:

```go
type ControllerInterface interface {
    SendJob(agentID string, jobPayload *pb.JobPayload) error
}
```

This abstraction allows for easier testing and decoupling of program logic from controller implementation.

### Traceroute Implementation

**Package:** `github.com/randofan/voltadomar/internal/controller`

The Traceroute struct implements the Program interface for traceroute measurements.

#### TracerouteConf

```go
type TracerouteConf struct {
    ProgramConf
    SourceHost      string
    DestinationHost string
    MaxTTL          int
    ProbeNum        int
    Timeout         int
    TOS             int
    StartID         int32
}
```

Configuration for traceroute programs.

#### TracerouteResult

```go
type TracerouteResult struct {
    Seq       int
    T1        string  // Send time (RFC3339Nano)
    T2        string  // Receive time (RFC3339Nano)
    Receiver  string  // Receiving agent ID
    Gateway   string  // Gateway IP address
    Timeout   bool
    FinalDst  bool    // Reached final destination
}
```

Represents the result of a single traceroute probe.

#### Constructor

```go
func NewTraceroute(controller ControllerInterface, conf *TracerouteConf) (*Traceroute, error)
```

Creates a new traceroute program instance.

**Parameters:**
- `controller`: Controller interface for job dispatch
- `conf`: Traceroute configuration

**Returns:**
- `*Traceroute`: New traceroute instance
- `error`: Error if destination resolution fails

#### Methods

**Run**
```go
func (tr *Traceroute) Run() (string, error)
```

Executes the traceroute measurement:
1. Resolves destination hostname to IP
2. Sends job to source agent
3. Waits for completion or timeout
4. Returns formatted results

**HandleDone**
```go
func (tr *Traceroute) HandleDone(payload *pb.DonePayload)
```

Processes job completion, recording probe send times from UDP acknowledgments.

**HandleReply**
```go
func (tr *Traceroute) HandleReply(payload *pb.ReplyPayload, agentID string) bool
```

Processes ICMP replies:
1. Parses raw ICMP packet
2. Extracts sequence number from inner UDP header
3. Records receive time, gateway IP, and receiving agent
4. Updates result state

#### Command Parsing

```go
func ParseTracerouteArgs(command string) (*TracerouteConf, error)
```

Parses traceroute command strings into configuration.

**Supported Format:**
```
volta <source> <destination> [-m <max-ttls>] [-w <waittime>] [-q <nqueries>] [-t <tos>]
```

**Example:**
```go
conf, err := ParseTracerouteArgs("volta agent1 8.8.8.8 -m 20 -q 3")
```

## Agent Package

**Package:** `github.com/randofan/voltadomar/internal/agent`

The agent package implements the distributed measurement nodes that execute network probing jobs received from the controller.

### Architecture

Agents use a worker pool architecture with separate pools for sending probes and processing received packets:

- **Sender Workers**: Process job payloads and send UDP probes
- **Listener Workers**: Process incoming ICMP packets and forward replies
- **gRPC Handler**: Manages bidirectional communication with controller
- **Packet Sniffer**: Captures ICMP packets using raw sockets

### Agent Struct

```go
type Agent struct {
    agentID           string
    controllerAddress string

    // gRPC client
    conn   *grpc.ClientConn
    client pb.AnycastServiceClient
    stream pb.AnycastService_ControlStreamClient

    // Worker management
    senderWorkers   *WorkerPool
    listenerWorkers *WorkerPool

    // Packet sniffer
    icmpConn *net.IPConn

    // Communication channels
    outgoingMessages chan *pb.Message

    // Context and synchronization
    ctx    context.Context
    cancel context.CancelFunc
    wg     sync.WaitGroup
}
```

### Constructor

```go
func NewAgent(agentID, controllerAddress string) *Agent
```

Creates a new agent instance with the specified configuration.

**Parameters:**
- `agentID`: Unique identifier for this agent
- `controllerAddress`: Controller gRPC endpoint (host:port)

**Example:**
```go
agent := NewAgent("agent1", "controller.example.com:50051")
```

### Methods

#### Run

```go
func (a *Agent) Run() error
```

Starts the agent's main processes:
1. Establishes gRPC connection to controller
2. Sets up ICMP socket for packet capture (requires root)
3. Initializes worker pools
4. Registers with controller
5. Starts message handling goroutines

**Returns:**
- `error`: Startup or runtime error

**Example:**
```go
if err := agent.Run(); err != nil {
    log.Fatalf("Agent error: %v", err)
}
```

#### Stop

```go
func (a *Agent) Stop()
```

Gracefully stops the agent and cleans up resources.

### Worker Pool Architecture

The agent uses worker pools to handle concurrent job processing:

#### WorkerPool Struct

```go
type WorkerPool struct {
    workerCount int
    jobChan     chan interface{}
    workerFunc  func(interface{}) error
    ctx         context.Context
    cancel      context.CancelFunc
    wg          sync.WaitGroup
}
```

#### Constructor

```go
func NewWorkerPool(workerCount int, workerFunc func(interface{}) error) *WorkerPool
```

Creates a new worker pool with the specified number of workers and processing function.

#### Methods

**Start**
```go
func (wp *WorkerPool) Start()
```
Starts all worker goroutines.

**Stop**
```go
func (wp *WorkerPool) Stop()
```
Gracefully stops all workers and waits for completion.

**AddJob**
```go
func (wp *WorkerPool) AddJob(job interface{}) error
```
Adds a job to the processing queue.

### Worker Functions

#### Sender Worker

Processes job payloads to send UDP probes:
1. Parses job payload (destination, TTL, probe count)
2. Creates UDP sockets for probe transmission
3. Sends probes with incrementing TTL values
4. Records send times for each probe
5. Returns DONE message with UDP acknowledgments

#### Listener Worker

Processes incoming ICMP packets:
1. Parses raw ICMP packet data
2. Identifies ICMP error messages (destination unreachable, time exceeded)
3. Extracts source IP and timing information
4. Forwards REPLY messages to controller

## Packets Package

**Package:** `github.com/randofan/voltadomar/pkg/packets`

The packets package provides network packet manipulation functionality using the `gopacket` library. It offers high-level functions for building and parsing network packets.

### Packet Building Functions

#### BuildUDPProbe

```go
func BuildUDPProbe(destinationIP string, ttl uint8, sourcePort, destPort uint16) ([]byte, error)
```

Creates a UDP probe packet with specified parameters.

**Parameters:**
- `destinationIP`: Target IP address
- `ttl`: Time-to-Live value
- `sourcePort`: UDP source port
- `destPort`: UDP destination port

**Returns:**
- `[]byte`: Raw packet bytes
- `error`: Error if packet creation fails

**Example:**
```go
packet, err := BuildUDPProbe("8.8.8.8", 64, 12345, 53)
```

#### BuildICMPProbe

```go
func BuildICMPProbe(destinationIP string, ttl uint8, seq, identifier uint16) ([]byte, error)
```

Creates an ICMP echo request packet.

**Parameters:**
- `destinationIP`: Target IP address
- `ttl`: Time-to-Live value
- `seq`: ICMP sequence number
- `identifier`: ICMP identifier

**Returns:**
- `[]byte`: Raw packet bytes (includes 40-byte payload)
- `error`: Error if packet creation fails

### Packet Parsing

#### ParsedPacket Struct

```go
type ParsedPacket struct {
    Timestamp time.Time
    IPv4      *layers.IPv4
    ICMPv4    *layers.ICMPv4
    UDP       *layers.UDP
    Payload   []byte
}
```

Represents a parsed network packet with extracted layer information.

#### ParseICMPReply

```go
func ParseICMPReply(rawPacket []byte, timestamp time.Time) (*ParsedPacket, error)
```

Parses raw ICMP packet bytes and extracts layer information.

**Parameters:**
- `rawPacket`: Raw packet bytes
- `timestamp`: Packet capture timestamp

**Returns:**
- `*ParsedPacket`: Parsed packet structure
- `error`: Error if parsing fails

### Utility Methods

#### Packet Analysis

```go
func (p *ParsedPacket) IsICMPError() bool
func (p *ParsedPacket) GetSourceIP() string
func (p *ParsedPacket) GetDestinationIP() string
func (p *ParsedPacket) GetICMPType() int
func (p *ParsedPacket) GetICMPCode() int
```

#### Network Resolution

```go
func ResolveHostname(ip string) string
func ResolveIP(hostname string) (string, error)
```

**Example:**
```go
ip, err := ResolveIP("google.com")
hostname := ResolveHostname("8.8.8.8")
```

### Error Handling

#### PacketParseError

```go
type PacketParseError struct {
    Message string
}

func (e *PacketParseError) Error() string
```

Custom error type for packet parsing failures.

## Command-Line Tools

Voltadomar provides two main command-line tools built as Go binaries.

### Controller Binary

**Location:** `src/voltadomar/controller-binary`
**Source:** `cmd/controller/main.go`

```bash
./controller-binary [options]
```

**Options:**
- `--port <port>`: gRPC server port (default: 50051)
- `--range <start-end>`: Session ID allocation range (required)
- `--block <size>`: Session ID block size per program (required)
- `-h, --help`: Show help message

**Example:**
```bash
./controller-binary --port 50051 --range 10000-20000 --block 100
```

### Agent Binary

**Location:** `src/voltadomar/agent-binary`
**Source:** `cmd/agent/main.go`

```bash
./agent-binary [options]
```

**Options:**
- `-i, --agent-id <id>`: Unique agent identifier (default: hostname)
- `-c, --controller-address <addr>`: Controller gRPC endpoint (default: 127.0.0.1:50051)
- `-h, --help`: Show help message

**Example:**
```bash
sudo ./agent-binary -i agent1 -c controller.example.com:50051
```

**Note:** Root privileges are required for raw socket operations.

## Client Integration

### gRPC Client Libraries

Voltadomar can be integrated with any gRPC client library. The service definition is available in `proto/anycast/anycast.proto`.

#### Python Client Example

```python
import grpc
import anycast_pb2 as pb
import anycast_pb2_grpc as pb_grpc

# Connect to controller
with grpc.insecure_channel('localhost:50051') as channel:
    stub = pb_grpc.AnycastServiceStub(channel)

    # Send traceroute request
    request = pb.Request(command="volta agent1 8.8.8.8")
    response = stub.UserRequest(request)

    if response.code == 200:
        print(response.output)
    else:
        print(f"Error: {response.output}")
```

#### Go Client Example

```go
package main

import (
    "context"
    "log"

    "google.golang.org/grpc"
    "google.golang.org/grpc/credentials/insecure"

    pb "github.com/randofan/voltadomar/proto/anycast"
)

func main() {
    // Connect to controller
    conn, err := grpc.NewClient("localhost:50051",
        grpc.WithTransportCredentials(insecure.NewCredentials()))
    if err != nil {
        log.Fatal(err)
    }
    defer conn.Close()

    client := pb.NewAnycastServiceClient(conn)

    // Send traceroute request
    request := &pb.Request{Command: "volta agent1 8.8.8.8"}
    response, err := client.UserRequest(context.Background(), request)
    if err != nil {
        log.Fatal(err)
    }

    if response.Code == 200 {
        fmt.Println(response.Output)
    } else {
        fmt.Printf("Error: %s\n", response.Output)
    }
}
```

## Examples

### Complete Workflow Example

This example demonstrates a complete Voltadomar measurement workflow:

#### 1. Start Controller

```bash
# Terminal 1: Start controller
cd src/voltadomar
./controller-binary --port 50051 --range 10000-20000 --block 100
```

#### 2. Start Agent

```bash
# Terminal 2: Start agent (requires root)
cd src/voltadomar
sudo ./agent-binary -i agent1 -c localhost:50051
```

#### 3. Run Measurement

```bash
# Terminal 3: Run traceroute
python examples/client.py agent1 8.8.8.8 1
```

**Expected Output:**
```
Traceroute to 8.8.8.8 (8.8.8.8) from agent1, 3 probes, 20 hops max
1  192.168.1.1 (192.168.1.1) agent1  1.234 ms  1.456 ms  1.678 ms
2  10.0.0.1 (10.0.0.1) agent1  5.123 ms  5.234 ms  5.345 ms
...
```

### Advanced Configuration

#### Multi-Agent Setup

```bash
# Controller with larger session range
./controller-binary --port 50051 --range 1000-50000 --block 1000

# Multiple agents on different nodes
sudo ./agent-binary -i nyc-agent -c controller.example.com:50051
sudo ./agent-binary -i lax-agent -c controller.example.com:50051
sudo ./agent-binary -i fra-agent -c controller.example.com:50051
```

#### Custom Traceroute Parameters

```bash
# Extended traceroute with custom parameters
python examples/client.py nyc-agent google.com -m 30 -q 5 -w 10
```

### Integration Examples

#### Automated Measurement Script

```python
#!/usr/bin/env python3
import grpc
import time
import json
from datetime import datetime

# Import generated gRPC files
import anycast_pb2 as pb
import anycast_pb2_grpc as pb_grpc

def run_measurement(agent, destination, controller_addr="localhost:50051"):
    """Run a single traceroute measurement."""
    with grpc.insecure_channel(controller_addr) as channel:
        stub = pb_grpc.AnycastServiceStub(channel)

        request = pb.Request(command=f"volta {agent} {destination}")
        response = stub.UserRequest(request)

        return {
            "timestamp": datetime.now().isoformat(),
            "agent": agent,
            "destination": destination,
            "success": response.code == 200,
            "output": response.output
        }

# Run measurements from multiple agents
agents = ["nyc-agent", "lax-agent", "fra-agent"]
destinations = ["8.8.8.8", "1.1.1.1", "208.67.222.222"]

results = []
for agent in agents:
    for dest in destinations:
        result = run_measurement(agent, dest)
        results.append(result)
        print(f"Completed: {agent} -> {dest}")
        time.sleep(1)  # Rate limiting

# Save results
with open("measurements.json", "w") as f:
    json.dump(results, f, indent=2)
```

## Troubleshooting

### Common Issues

#### Permission Denied (Raw Sockets)

**Problem:** Agent fails to start with "operation not permitted" error.

**Solution:**
```bash
# Run agent with root privileges
sudo ./agent-binary -i agent1 -c localhost:50051

# Or set capabilities (Linux only)
sudo setcap cap_net_raw+ep ./agent-binary
./agent-binary -i agent1 -c localhost:50051
```

#### Connection Refused

**Problem:** Agent cannot connect to controller.

**Diagnosis:**
```bash
# Check if controller is running
netstat -tlnp | grep :50051

# Test connectivity
telnet controller-host 50051
```

**Solutions:**
- Verify controller is running and listening on correct port
- Check firewall rules allow gRPC traffic
- Ensure correct controller address in agent configuration

#### Session ID Exhaustion

**Problem:** Controller returns "no available session ID blocks" error.

**Solutions:**
```bash
# Increase session ID range
./controller-binary --range 1000-100000 --block 100

# Reduce block size for more concurrent programs
./controller-binary --range 1000-10000 --block 50
```

#### Packet Parsing Errors

**Problem:** Agent reports packet parsing failures.

**Diagnosis:**
- Check agent logs for specific parsing errors
- Verify network interface captures ICMP traffic
- Test with known working destinations

**Solutions:**
- Ensure agent has proper network interface access
- Check for network filtering or NAT issues
- Verify ICMP traffic is not blocked by firewalls

### Performance Tuning

#### Controller Optimization

```bash
# Increase worker pools for high-throughput scenarios
# (Modify source code worker pool sizes)

# Use larger session ranges for many concurrent measurements
./controller-binary --range 10000-1000000 --block 1000
```

#### Agent Optimization

```bash
# Monitor system resources
top -p $(pgrep agent-binary)

# Check network interface statistics
ip -s link show

# Monitor ICMP traffic
tcpdump -i any icmp
```

### Debugging

#### Enable Verbose Logging

Modify log levels in source code for detailed debugging:

```go
// In main.go files, add:
log.SetLevel(log.DebugLevel)
```

#### Network Diagnostics

```bash
# Test UDP connectivity
nc -u destination-ip 33434

# Monitor ICMP traffic
sudo tcpdump -i any -n icmp

# Check routing table
ip route show
```

#### gRPC Debugging

```bash
# Enable gRPC logging (environment variable)
export GRPC_GO_LOG_VERBOSITY_LEVEL=99
export GRPC_GO_LOG_SEVERITY_LEVEL=info
```

### Getting Help

For additional support:

1. **Check Logs**: Review controller and agent logs for specific error messages
2. **Test Connectivity**: Verify network connectivity between components
3. **Validate Configuration**: Ensure all parameters are within valid ranges
4. **Monitor Resources**: Check system resources (CPU, memory, network)
5. **Review Documentation**: Consult this API reference and README.md

**Common Log Locations:**
- Controller: stdout/stderr or configured log file
- Agent: stdout/stderr or configured log file
- System logs: `/var/log/syslog` or `journalctl -u voltadomar`
```
