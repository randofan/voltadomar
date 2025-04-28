# Voltadomar

> Distributed anycast network measurement toolkit

[![PyPI version](https://badge.fury.io/py/voltadomar.svg)](https://badge.fury.io/py/voltadomar)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

## Overview

Voltadomar is a Python package for performing distributed network [traceroute](https://linux.die.net/man/8/traceroute) measurements on anycast networks. It provides a controller-agent architecture for coordinating network probing operations across multiple anycast nodes.

The name "Voltadomar" comes from the Portuguese phrase "volta do mar" (turn of the sea), a navigation technique used by Portuguese sailors in the Age of Discovery to leverage oceanic wind patterns - much like how this toolkit leverages distributed anycast nodes to provide insights into Internet routing.

## Motivation

Since its inception in the 1990s, anycast has been widely adopted for various applications, including DNS and content delivery networks. The concept of anycast is simple: multiple nodes share the same IP address, and routing protocols direct packets to the nearest node based on network topology. However, this simplicity can lead to complex routing behaviors, making it challenging to understand how packets traverse the network.

Anecdotal evidence suggests that anycast routing can be unpredictable, with packets from the same source being directed to different anycast nodes. This can result in [broken TCP connections](https://blog.tohojo.dk/2025/03/ecn-ecmp-and-anycast-a-cocktail-of-broken-connections.html), poor latency, and other issues. To address these challenges, we developed Voltadomar to provide a comprehensive toolkit for measuring and analyzing anycast networks routing behaviors with an anycast adaption of traceroute.

Voltadomar is designed to be extensible, allowing researchers and network operators to add new measurement types and customize existing ones. It provides a low-level interface for constructing and parsing packets, enabling precise measurements of network behavior.

## Features

- **Distributed Architecture**: Controller-agent model for coordinating measurements between multiple anycast nodes and multiple controllers
- **Accurate Packet Handling**: Low-level packet construction and parsing for precise measurements
- **Asynchronous Operation**: Non-blocking I/O for efficient concurrent measurements
- **Extensible Design**: Easy to add new measurement types beyond basic traceroute

## Installation

### Requirements

- Python 3.11 or higher
- Root/administrator privileges (for raw socket operations)
- Linux-based OS recommended (though can run on other platforms with limitations)

### From Source

```bash
git clone git@bitbucket.org:uwpatio/voltadomar.git
pip install -e .
```

## Architecture

Voltadomar uses a controller-agent architecture:

- **Controller**: Central server that allocates measurement tasks, collects results, and interfaces with users
- **Agents**: Distributed measurement points that perform network probing tasks
- **Communication**: gRPC-based secure bidirectional communication between controller and agents

<p align="center">
  <img src="docs/images/rpc.png" alt="Voltadomar RPC protocol" width="600">
</p>

## Usage

See the [Examples](examples/) directory for detailed usage examples. Consult the [API documentation](docs/api.md) for more information on available classes and methods.

### Running a Controller

Start a controller on a server that's reachable by all agents:

```python
from voltadomar import Controller

controller = Controller(port=50051, start_id=1000, end_id=2000, block_size=100)
await controller.run()
```

### Running an Agent

On each anycast node, start an agent that connects to the controller:

```python
from voltadomar import Agent

agent = Agent(agent_id="node1", controller_address="controller.example.com:50051")
await agent.run()
```

### Performing Measurements

Connect to the controller with a client:

```python
import grpc
from voltadomar import Request, AnycastServiceStub

with grpc.insecure_channel("controller.example.com:50051") as channel:
    stub = AnycastServiceStub(channel)
    request = Request(command="volta node1 google.com -m 30")
    response = stub.UserRequest(request)
    if response.code == 200:
        print("User details received:\n", response.output)
    else:
        print("Error:\n", response.output)
```

## Example Output

A traceroute measurement might produce output like:

```
Traceroute to google.com (142.250.72.110) from node1, 3 probes, 30 hops max
1  192.168.1.1 (192.168.1.1) node1  0.324 ms  0.298 ms  0.276 ms
2  10.0.0.1 (10.0.0.1) node1  5.432 ms  5.298 ms  5.387 ms
3  172.16.0.1 (172.16.0.1) node1  10.231 ms  10.198 ms  10.287 ms
...
12  142.250.72.110 (142.250.72.110) node1  35.432 ms  35.298 ms  35.387 ms
```

## Packet Types

Voltadomar supports several packet types for network measurements:

- **IP**: Base protocol for all other packets
- **UDP**: Used for most probing operations
- **ICMP**: Used for echo requests and processing traceroute replies

## Advanced Configuration

The following option flags match the command line options of the `traceroute` command:

### ECN Support

Toggle the TOS field for ECN support. `-t 2` enables ECN while `-t 1` disables it.

```python
request = Request(command="volta node1 google.com -t 2")
```

### Customizing Traceroute Parameters

```python
# Customize max TTL, number of queries per hop, and wait time
request = Request(command="volta node1 google.com -m 30 -q 5 -w 2")
```

### Send ICMP Echo Request Probes

```python
request = Request(command="volta node1 google.com -I")
```

## Documentation

- [API Reference](docs/api.md)
- [Examples](examples/)

## License

MIT License - See [LICENSE](LICENSE) file for details.

## Citation

If you use Voltadomar in your research, please consider citing:

```bibtex
@software{voltadomar,
  author = {Song, David},
  title = {Voltadomar: Distributed Anycast Network Measurement Toolkit},
  url = {https://bitbucket.org/uwpatio/voltadomar},
  year = {2025},
}
```

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.
