# Voltadomar API Reference

This document provides detailed information about the classes, methods, and services available in the Voltadomar package.

## Contents

- [gRPC Protocol (AnycastService)](#grpc-protocol-anycastservice)
- [Controller](#controller)
  - [Session ID Management](#session-id-management)
  - [Methods](#methods)
  - [gRPC Methods (AnycastService)](#grpc-methods-anycastservice)
- [Program](#program)
  - [ProgramConf](#programconf)
  - [Program](#program-1)
- [Traceroute](#traceroute)
  - [TracerouteConf](#tracerouteconf)
  - [TracerouteResult](#tracerouteresult)
  - [parse_traceroute_args](#parse_traceroute_args)
  - [Traceroute](#traceroute-1)
- [Agent](#agent)
- [WorkerManager](#workermanager)
- [Packets](#packets)
  - [IP](#ip)
  - [UDP](#udp)
  - [ICMP](#icmp)
- [Utilities](#utilities)
- [Exceptions](#exceptions)

## gRPC Protocol (AnycastService)

Voltadomar uses gRPC for communication between the Controller, Agents, and user clients. The service definition is `AnycastService`.

### RPC Methods

#### ControlStream

```protobuf
rpc ControlStream(stream Message) returns (stream Message);
```

A bidirectional stream between an Agent and the Controller.
- **Agent -> Controller:** Sends `REGISTER`, `DONE`, `REPLY`, `ERROR` messages.
- **Controller -> Agent:** Sends `JOB` messages.

#### UserRequest

```protobuf
rpc UserRequest(Request) returns (Response);
```

A unary RPC for user clients to request the Controller to run a measurement program.

### Message Structure

All communication over `ControlStream` uses the `Message` wrapper:

```protobuf
message Message {
  string type = 1;                    // Message type identifier
  google.protobuf.Any payload = 2;    // The actual payload message
}
```

The `type` field indicates the kind of payload contained within the `google.protobuf.Any` field. Possible values correspond to the payload message names (e.g., "REGISTER", "JOB", "DONE").

### Payload Messages

#### RegisterPayload

```protobuf
message RegisterPayload {
  string agent_id = 1; // Unique ID of the registering agent
}
```
Sent by an Agent to the Controller upon connection to identify itself.
**Type:** "REGISTER"

#### ErrorPayload

```protobuf
message ErrorPayload {
  int32 code = 1;      // Error code (e.g., HTTP status codes)
  string message = 2;  // Descriptive error message
}
```
Sent by either Agent or Controller to report an error.
**Type:** "ERROR"

#### CancelPayload

```protobuf
message CancelPayload {
  // Currently empty
}
```
*Note: This message is defined but not currently used in the implementation.*
**Type:** "CANCEL" (intended)

#### JobPayload

```protobuf
message JobPayload {
  int32 session_id = 1; // ID identifying the measurement session/program
  string dst_ip = 2;    // Destination IP address for probes
  int32 max_ttl = 3;    // Maximum TTL for probes
  int32 probe_num = 4;  // Number of probes per TTL
  int32 base_port = 5;  // Starting source port for UDP probes (used for sequence)
}
```
Sent by the Controller to an Agent to initiate a measurement job (e.g., sending traceroute probes).
**Type:** "JOB"

#### UdpAck

```protobuf
message UdpAck {
  int32 seq = 1;        // Sequence number (derived from source port)
  string sent_time = 2; // ISO 8601 timestamp when the probe was sent
}
```
Part of `DonePayload`, confirms the sending of a single UDP probe.

#### DonePayload

```protobuf
message DonePayload {
  int32 session_id = 1;           // ID identifying the measurement session/program
  repeated UdpAck udp_acks = 2; // List of acknowledgements for sent probes
}
```
Sent by an Agent to the Controller when it has finished sending all probes for a specific job.
**Type:** "DONE"

#### ReplyPayload

```protobuf
message ReplyPayload {
  bytes raw_packet = 1; // Raw bytes of the received ICMP reply packet
  string time = 2;      // ISO 8601 timestamp when the reply was received
}
```
Sent by an Agent to the Controller when it receives an ICMP reply potentially related to a measurement job.
**Type:** "REPLY"

#### Request

```protobuf
message Request {
  string command = 1; // The command string entered by the user (e.g., "volta agent1 google.com")
}
```
Sent by a user client to the Controller via the `UserRequest` RPC.

#### Response

```protobuf
message Response {
  int32 code = 1;      // Status code (e.g., 200 for success, 400 for bad request)
  string output = 2;   // Output string (e.g., formatted traceroute results or error message)
}
```
Returned by the Controller to the user client in response to a `UserRequest`.

## Controller

The Controller serves as the central coordinator for the Voltadomar system. It manages connections with multiple Agents, handles user requests for measurements, and orchestrates the execution of specific measurement tasks, which are encapsulated within `Program` subclasses (like `Traceroute`).

When a user initiates a measurement via the `UserRequest` gRPC method, the Controller parses the request, determines the appropriate `Program` type, allocates necessary resources (such as a unique `session_id` block using its [Session ID Management](#session-id-management) logic), and instantiates the corresponding `Program` object (e.g., `Traceroute`).

The Controller then calls the `run()` method on the `Program` instance. The `Program` instance contains the specific logic for the measurement. It interacts with the Controller (using the provided `controller` reference) to send `JOB` messages to the required Agent(s) via the `send_job()` method.

As Agents execute the job and receive replies, they send `DONE` and `REPLY` messages back to the Controller via the `ControlStream`. The Controller receives these messages and routes them to the appropriate active `Program` instance based on the `session_id` (for `DONE`) or by querying each program (for `REPLY`). The `Program` instance processes these incoming messages using its `handle_done()` and `handle_reply()` methods, updating its internal state.

Once the `Program`'s `run()` method completes (either successfully, by timeout, or due to an error), it returns the formatted results or status information to the Controller. The Controller then packages this into a `Response` message and sends it back to the originating user client. Finally, the Controller cleans up resources associated with the completed program, including releasing the allocated `session_id` block.

### Controller

```python
Controller(port: int, start_id: int, end_id: int, block_size: int)
```

**Parameters:**
- `port`: Port number to run the gRPC server on.
- `start_id`: Starting session ID for allocation. Defines the lower bound of the managed ID range.
- `end_id`: Maximum session ID that can be allocated. Defines the upper bound (exclusive) of the managed ID range.
- `block_size`: Size of ID blocks allocated per program.

**Properties:**
- `programs`: Dictionary mapping session start IDs to active `Program` instances.
- `agent_streams`: Dictionary mapping agent IDs to their gRPC `ServicerContext`.

### Session ID Management

The Controller manages a range of identifiers (`start_id` to `end_id`) to distinguish between concurrent measurement programs and their associated network probes. When a new program (like Traceroute) is initiated via `UserRequest`, the Controller allocates a contiguous block of IDs (`block_size`) for that program instance. The block size is configurable by the user to accommodate the expected usage patterns i.e. a larger block size for programs with many probes.

The starting ID of this block serves as the `session_id` for the program, used in `JobPayload` and `DonePayload` messages. The allocated block of IDs is used by the program and agents to uniquely identify individual probes. For example, in the `Traceroute` program, the UDP source port for each probe is calculated as `session_id + sequence_number`, ensuring that replies can be correctly matched to the corresponding program instance and probe sequence.

The Controller uses a **linear probing (next-fit)** strategy within the circular ID range (`start_id` to `end_id`) to find and allocate free blocks. It starts searching from the ID immediately following the previously allocated block and wraps around if necessary.

#### allocate_session_id()

```python
allocate_session_id() -> int
```

Allocates a new session ID block using a linear probing (next-fit) approach within the configured ID range. It starts searching from the position after the last allocation and wraps around the range if needed. Marks the found block as in use by adding the starting ID to the `in_use_blocks` set.

**Returns:** The start ID of the allocated block.
**Raises:** `RuntimeError` if no free blocks are available within the configured range (`start_id` to `end_id`).

#### release_session_id()

```python
release_session_id(session_id: int) -> None
```

Releases a previously allocated session ID block by removing it from the `in_use_blocks` set, making it available for future allocations. This is called when a program finishes execution.

**Parameters:**
- `session_id`: The start ID of the block to release.

### Methods:

#### send_job()

```python
async send_job(agent_id: str, job_payload: JobPayload) -> None
```

Sends a JOB message to a specific agent via its gRPC stream. This method is invoked by a Controller program instance to send a job payload to an agent.

**Parameters:**
- `agent_id`: The ID of the target agent.
- `job_payload`: The `JobPayload` protobuf message.

#### run()

```python
async run() -> None
```

Starts the gRPC server and waits for termination.

### gRPC Methods (AnycastService)

#### ControlStream()

```protobuf
rpc ControlStream(stream Message) returns (stream Message);
```

Handles the bidirectional gRPC stream with an agent. Receives `REGISTER`, `DONE`, `REPLY`, `ERROR` messages and sends `JOB` messages.

#### UserRequest()

```protobuf
rpc UserRequest(Request) returns (Response);
```

Handles a request from a user client to execute a program (e.g., traceroute). Parses the command, allocates resources, runs the program, and returns the result.

**Parameters:**
- `request`: A `Request` protobuf message containing the command string.
**Returns:** A `Response` protobuf message containing the status code and output string.

## Program

Base classes for measurement programs run by the Controller.

### ProgramConf

```python
@dataclass
class ProgramConf:
    pass
```

Base dataclass for program configuration. Specific program configurations should inherit from this.

### Program

```python
class Program(ABC):
    def __init__(self, controller: Controller, conf: ProgramConf) -> None:
        # ... implementation ...
```

Abstract base class for programs managed by the Controller.

**Parameters:**
- `controller`: The `Controller` instance managing this program.
- `conf`: A `ProgramConf` instance containing configuration for this program run.

**Abstract Methods:**

#### run()

```python
@abstractmethod
async def run(self) -> Any: # Return type depends on program
```

Runs the program logic (e.g., sending jobs, waiting for results).

**Returns:** Program-specific results.

#### handle_done()

```python
@abstractmethod
def handle_done(self, done_payload: DonePayload) -> None:
```

Handles a `DONE` message received from an agent related to this program instance.

**Parameters:**
- `done_payload`: The `DonePayload` protobuf message.

#### handle_reply()

```python
@abstractmethod
def handle_reply(self, reply_payload: ReplyPayload, agent_id: str) -> bool:
```

Handles a `REPLY` message received from an agent. Determines if the reply belongs to this program instance.

**Parameters:**
- `reply_payload`: The `ReplyPayload` protobuf message.
- `agent_id`: The ID of the agent that sent the reply.

**Returns:** `True` if the reply was processed by this program, `False` otherwise.

## Traceroute

Traceroute is the only program currently implemented. It sends UDP probes to a destination IP address with increasing TTL values, and records which anycast node receives the ICMP replies. The results are formatted and returned to the user. This enables the user to identify any inconsistencies in bidirectional routing paths, where the probes are sent from one anycast node, but the replies are received by another.

### TracerouteConf

```python
@dataclass
class TracerouteConf(ProgramConf):
    source_host: str
    destination_host: str
    start_id: int
    probe_num: int
    max_ttl: int
    timeout: int
    tos: int
```

Configuration specific to a traceroute program. Inherits from `ProgramConf`.

**Attributes:**
- `source_host`: Source agent hostname or ID.
- `destination_host`: Destination hostname or IP address.
- `start_id`: Starting session ID allocated by the Controller.
- `probe_num`: Number of probes per TTL (int).
- `max_ttl`: Maximum TTL to probe (int).
- `timeout`: Program timeout in seconds (int).
- `tos`: Type of Service value for IP header (currently unused in probe building) (int).

### TracerouteResult

```python
@dataclass
class TracerouteResult:
    seq: int
    t1: Optional[str]  # ISO timestamp
    t2: Optional[str]  # ISO timestamp
    receiver: Optional[str]
    gateway: Optional[str]
    timeout: bool
    final_dst: bool
```

Represents the result of a single traceroute probe.

**Attributes:**
- `seq`: Sequence number (derived from source port).
- `t1`: ISO timestamp when the probe was sent by the agent.
- `t2`: ISO timestamp when the reply was received by an agent.
- `receiver`: Agent ID that received the ICMP reply.
- `gateway`: IP address of the router that sent the ICMP reply.
- `timeout`: True if no reply was received for this probe.
- `final_dst`: True if the reply indicates the final destination was reached (ICMP Type 3).

### parse_traceroute_args

```python
parse_traceroute_args(command: str) -> tuple
```

Parses a traceroute command string into arguments.

**Parameters:**
- `command`: The command string (e.g., "volta agent1 google.com -m 25 -q 2").

**Returns:** A tuple containing: `(source, destination, max_ttls, waittime, tos, nqueries)`.

### Traceroute

```python
class Traceroute(Program):
    def __init__(self, controller, conf: TracerouteConf):
        # ... implementation ...
```

Handles the execution and result processing for a traceroute measurement. Inherits from `Program`.

**Parameters:**
- `controller`: The `Controller` instance.
- `conf`: A `TracerouteConf` instance.

**Methods:**

#### run()

```python
async run() -> str
```

Runs the traceroute program: sends the `JOB` to the source agent, waits for `DONE` and `REPLY` messages (or timeout), and formats the results.

**Returns:** Formatted traceroute results as a multi-line string.

#### handle_done()

```python
handle_done(done_payload: DonePayload) -> None
```

Processes a `DONE` message, recording the send times (`t1`) for each probe based on the `UdpAck` list.

**Parameters:**
- `done_payload`: The `DonePayload` from the source agent.

#### handle_reply()

```python
handle_reply(reply_payload: ReplyPayload, agent_id: str) -> bool
```

Processes a `REPLY` message, parsing the ICMP packet to extract gateway IP, determining the sequence number from the original UDP source port, and recording receive time (`t2`), receiver agent, and gateway. Updates the state and checks if the program is finished.

**Parameters:**
- `reply_payload`: The `ReplyPayload` from any agent.
- `agent_id`: The ID of the agent that sent the reply.

**Returns:** `True` if the reply belonged to this traceroute instance, `False` otherwise.

## Agent

The Agent class runs on each anycast node and executes network measurement jobs received from the Controller.

### Agent

```python
Agent(agent_id: str, controller_address: str)
```

**Parameters:**
- `agent_id`: Unique identifier for this agent.
- `controller_address`: The address (host:port) of the controller gRPC service.

**Methods:**

#### run()

```python
async run() -> None
```

Starts the agent's main processes: worker managers, gRPC connection handler, and packet sniffer. Handles graceful shutdown.

#### sender_worker()

```python
async sender_worker(payload: Any) -> Message
```

Processes a job payload to send UDP/ICMP probes or handles an error payload. Runs within the `sender_workers` pool.

**Parameters:**
- `payload`: Either a `JobPayload` containing probing instructions or an `ErrorPayload`.

**Returns:** A protobuf `Message` of type `DONE` upon successful job completion, or `ERROR` if an error occurred.

#### listener_worker()

```python
async def listener_worker(sniffed_packet: Tuple[bytes, str]) -> Message
```

Processes a sniffed ICMP packet and formats it as a `REPLY` message. Runs within the `listener_workers` pool.

**Parameters:**
- `sniffed_packet`: A tuple containing the raw packet bytes and the ISO timestamp string of reception.

**Returns:** A protobuf `Message` of type `REPLY`.

#### handle_controller()

```python
async handle_controller(context: grpc.aio.StreamStreamCall) -> None
```

Receives messages (`JOB`) from the controller via the gRPC stream and dispatches them to the `sender_workers`.

**Parameters:**
- `context`: The gRPC stream context for receiving messages.

#### handle_sniffer()

```python
async handle_sniffer() -> None
```

Listens for incoming ICMP packets on a raw socket and dispatches them to the `listener_workers`.

#### handle_output()

```python
async handle_output() -> AsyncIterator[Message]
```

Asynchronously generates messages (`REGISTER`, `DONE`, `REPLY`, `ERROR`) to be sent back to the controller via the gRPC stream. Collects results from worker output queues.

**Yields:** `Message` protobuf objects.

## WorkerManager

A utility class for managing a pool of asynchronous worker tasks.

### WorkerManager

```python
WorkerManager(worker_num: int, job_processor: JobProcessor)
```

**Parameters:**
- `worker_num`: Number of concurrent worker tasks.
- `job_processor`: An `async` function that takes one job argument and returns a result.

**Properties:**
- `input_queue`: `asyncio.Queue` for jobs to be processed.
- `output_queue`: `asyncio.Queue` for results from processed jobs.

**Methods:**

#### start()

```python
start() -> None
```

Creates and starts the worker tasks.

#### add_input()

```python
async add_input(job: Any) -> None
```

Adds a job to the input queue.

#### get_output()

```python
async get_output() -> Any
```

Retrieves a result from the output queue. Waits if the queue is empty.

#### join()

```python
async join() -> None
```

Waits until all items in the input queue have been processed and all items in the output queue have been retrieved.

#### stop()

```python
async stop() -> None
```

Signals workers to stop after processing remaining jobs and waits for them to finish. Sends `None` sentinel values to the input queue.

#### cancel()

```python
async cancel() -> None
```

Cancels all running worker tasks immediately and clears the queues.

## Packets

Voltadomar includes classes for handling various packet types.

### IP

```python
IP(raw: Optional[bytes] = None, dst: str = "0.0.0.0", src: str = "0.0.0.0",
   ttl: int = 64, proto: int = 17, ecn: bool = False)
```

Represents an IP packet.

**Parameters:**
- `raw`: Raw IP packet bytes for parsing. If provided, other parameters are ignored during initialization but fields are populated by parsing.
- `dst`: Destination IP address.
- `src`: Source IP address.
- `ttl`: Time to Live value.
- `proto`: Protocol number (e.g., 1 for ICMP, 17 for UDP).
- `ecn`: Enable ECN bits in the TOS field (sets TOS to 0x03 if True, 0x00 otherwise).

**Properties:**
- `src`: Source IP address (string).
- `dst`: Destination IP address (string).
- `ttl`: Time to Live (int).
- `proto`: Protocol number (int).
- `payload`: Packet payload (bytes).
- `ecn`: ECN bits status (int, 0 or 3). Can be set with a boolean.
- `version`, `ihl`, `tos`, `length`, `id`, `flags_offset`, `checksum`: Other IP header fields.

**Methods:**

#### \_\_bytes\_\_()

```python
__bytes__() -> bytes
```

Serializes the IP packet object (header + payload) into bytes. Calculates header length automatically. Does *not* calculate the checksum.

**Returns:** Raw packet bytes.

### UDP

```python
UDP(raw: Optional[bytes] = None, sport: int = 0, dport: int = 0,
    payload: bytes = b"", checksum: int = 0, length: int = 8)
```

Represents a UDP packet.

**Parameters:**
- `raw`: Raw UDP packet bytes for parsing. If provided, other parameters are ignored during initialization but fields are populated by parsing.
- `sport`: Source port.
- `dport`: Destination port.
- `payload`: UDP payload (bytes).
- `checksum`: UDP checksum (int). *Note: Checksum calculation is not implemented.*
- `length`: UDP packet length (header + payload) (int).

**Properties:**
- `sport`: Source port (int).
- `dport`: Destination port (int).
- `length`: UDP length (int).
- `checksum`: UDP checksum (int).
- `payload`: Packet payload (bytes).

**Methods:**

#### \_\_bytes\_\_()

```python
__bytes__() -> bytes
```

Serializes the UDP packet object (header + payload) into bytes.

**Returns:** Raw packet bytes.

### ICMP

```python
ICMP(raw: Optional[bytes] = None, type: int = 8, code: int = 0)
```

Represents an ICMP packet.

**Parameters:**
- `raw`: Raw ICMP packet bytes for parsing. If provided, other parameters are ignored during initialization but fields are populated by parsing.
- `type`: ICMP type (int).
- `code`: ICMP code (int).

**Properties:**
- `type`: ICMP packet type (int).
- `code`: ICMP code field (int).
- `checksum`: ICMP checksum (int).
- `original_data`: For echo request/reply, the data after the standard 4-byte header. For error messages (Type 3, 11), the original IP header and first 8 bytes of the original transport header that caused the error (bytes).
- `inner_data`: For error messages (Type 3, 11), the data *after* the inner IP header within `original_data`. Typically contains the start of the original transport (UDP/TCP/ICMP) header (bytes or None).

**Methods:**

#### \_\_bytes\_\_()

```python
__bytes__() -> bytes
```

Serializes the ICMP packet object into bytes. Calculates and inserts the checksum automatically.

**Returns:** Raw packet bytes.

## Utilities

Utility functions for network operations.

### resolve_ip()

```python
resolve_ip(hostname: str) -> Optional[str]
```

Resolves a hostname to an IP address using `socket.gethostbyname`.

**Parameters:**
- `hostname`: Hostname to resolve.

**Returns:** IP address as a string, or `None` if resolution fails.

### resolve_hostname()

```python
resolve_hostname(ip: str) -> str
```

Attempts to resolve an IP address to a hostname using `socket.gethostbyaddr`.

**Parameters:**
- `ip`: IP address string to resolve.

**Returns:** Hostname string, or the original IP string if resolution fails.

### build_udp_probe()

```python
build_udp_probe(destination_ip: str, ttl: int, source_port: int, dst_port: int) -> bytes
```

Builds a raw UDP probe packet (IP header + UDP header, no payload).

**Parameters:**
- `destination_ip`: Destination IP address.
- `ttl`: Time to Live value for the IP header.
- `source_port`: Source UDP port.
- `dst_port`: Destination UDP port.

**Returns:** Raw packet bytes.

### build_icmp_probe()

```python
build_icmp_probe(destination_ip: str, ttl: int, seq: int, identifier: int) -> bytes
```

Builds a raw ICMP Echo Request packet (IP header + ICMP header + data).

**Parameters:**
- `destination_ip`: Destination IP address.
- `ttl`: Time to Live value for the IP header.
- `seq`: ICMP sequence number.
- `identifier`: ICMP identifier.

**Returns:** Raw packet bytes including a 40-byte payload.

## Exceptions

Custom exceptions used in the package.

### PacketParseError

```python
class PacketParseError(Exception):
    pass
```

Raised when parsing raw bytes into a `IP`, `UDP`, or `ICMP` object fails due to malformed data or insufficient length.
