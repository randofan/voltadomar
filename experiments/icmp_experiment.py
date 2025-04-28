import asyncio
import socket
import struct
import time
from dataclasses import dataclass, field
from collections import defaultdict
import matplotlib.pyplot as plt
import numpy as np
import json
import os
from voltadomar.packets import IP, ICMP

# List of DNS servers to test
DNS_SERVERS = {
    "Google 1": "8.8.8.8",
    "Google 2": "8.8.4.4",
    "Control D 1": "76.76.2.0",
    "Control D 2": "76.76.10.0",
    "Quad9 1": "9.9.9.9",
    "Quad9 2": "149.112.112.112",
    "OpenDNS 1": "208.67.222.222",
    "OpenDNS 2": "208.67.220.220",
    "Cloudflare 1": "1.1.1.1",
    "Cloudflare 2": "1.0.0.1",
    "AdGuard 1": "94.140.14.14",
    "AdGuard 2": "94.140.15.15",
    "CleanBrowsing 1": "185.228.168.9",
    "CleanBrowsing 2": "185.228.169.9",
    "Alternate DNS 1": "76.76.19.19",
    "Alternate DNS 2": "76.223.122.150",
}

DNS_IDENTIFIERS = {name: i + 0x0001 for i, name in enumerate(DNS_SERVERS.keys())}

MAX_TTL = 15
PAYLOAD_SIZE = 40
TIMEOUT_SECONDS = 120
RETRIES = 3


@dataclass
class IcmpRequest:
    """Represents an ICMP request with tracking info"""

    dst_ip: str
    ttl: int
    seq: int
    identifier: int
    sent_time: float = 0.0
    sent: bool = False


@dataclass
class IcmpResponse:
    """Tracks an ICMP response and payload information"""

    src_ip: str
    dst_ip: str
    ttl: int
    seq: int
    identifier: int
    icmp_type: int
    payload_size: int
    rtt_ms: float


@dataclass
class ExperimentResults:
    """Stores all results from the experiment"""

    requests: list[IcmpRequest] = field(default_factory=list)
    responses: list[IcmpResponse] = field(default_factory=list)
    hops_by_target: dict = field(default_factory=lambda: defaultdict(dict))


def build_icmp_probe(destination_ip, ttl, seq, identifier):
    """Creates an ICMP probe packet with the given parameters."""
    ip_packet = IP(dst=destination_ip, ttl=ttl, proto=1)
    icmp_packet = ICMP(type=8, code=0)

    header_data = struct.pack("!HH", identifier, seq)
    payload_data = b"ubiquitous" * 4  # 40 bytes

    icmp_packet._original_data = header_data + payload_data
    return bytes(ip_packet) + bytes(icmp_packet)


async def send_probes(results, socket_obj):
    """Send all the ICMP probes for the experiment"""
    loop = asyncio.get_event_loop()

    for request in results.requests:
        if request.sent:
            continue

        packet = build_icmp_probe(
            destination_ip=request.dst_ip,
            ttl=request.ttl,
            seq=request.seq,
            identifier=request.identifier,
        )

        try:
            await loop.sock_sendto(socket_obj, packet, (request.dst_ip, 0))
            request.sent_time = time.time()
            request.sent = True
            await asyncio.sleep(0.05)

        except Exception:
            await asyncio.sleep(0.1)


async def receive_responses(results, socket_obj):
    """Receive and process ICMP responses"""
    loop = asyncio.get_event_loop()
    start_time = time.time()

    while time.time() - start_time < TIMEOUT_SECONDS:
        try:
            socket_obj.settimeout(0.1)
            raw_packet = await loop.sock_recv(socket_obj, 65535)
            recv_time = time.time()

            if len(raw_packet) < 28:
                continue

            ip = IP(raw_packet)
            icmp = ICMP(ip.payload)

            if icmp.type == 11:  # Time Exceeded
                await process_time_exceeded(results, ip, icmp, recv_time)
            elif icmp.type == 0:  # Echo Reply
                await process_echo_reply(results, ip, icmp, recv_time)

        except socket.timeout:
            pass
        except Exception:
            pass

        await asyncio.sleep(0.01)


async def process_time_exceeded(results, ip, icmp, recv_time):
    """Process a Time Exceeded ICMP message"""
    try:
        if len(icmp.original_data) < 28:
            return

        inner_ip = IP(icmp.original_data)
        inner_data = icmp.get_inner_icmp_data()

        if inner_data and len(inner_data) >= 4:
            identifier, seq = struct.unpack("!HH", inner_data[:4])

            dns_name = next(
                (name for name, id_ in DNS_IDENTIFIERS.items() if id_ == identifier),
                None,
            )

            if dns_name and inner_ip.dst == DNS_SERVERS[dns_name]:
                payload_size = len(inner_data) - 4 if len(inner_data) > 4 else 0

                matching_requests = [
                    req
                    for req in results.requests
                    if req.dst_ip == inner_ip.dst and req.seq == seq and req.identifier == identifier
                ]

                if matching_requests:
                    req = matching_requests[0]
                    rtt = (recv_time - req.sent_time) * 1000
                    response = IcmpResponse(
                        src_ip=ip.src,
                        dst_ip=req.dst_ip,
                        ttl=req.ttl,
                        seq=seq,
                        identifier=identifier,
                        icmp_type=icmp.type,
                        payload_size=payload_size,
                        rtt_ms=rtt,
                    )
                    results.responses.append(response)

                    results.hops_by_target[req.dst_ip][req.ttl] = {
                        "router": ip.src,
                        "payload_size": payload_size,
                        "rtt_ms": rtt,
                    }

    except Exception:
        pass


async def process_echo_reply(results, ip, icmp, recv_time):
    """Process an Echo Reply ICMP message"""
    try:
        if len(icmp.original_data) >= 4:
            identifier, seq = struct.unpack("!HH", icmp.original_data[:4])

            dns_name = next(
                (name for name, id_ in DNS_IDENTIFIERS.items() if id_ == identifier),
                None,
            )

            if dns_name and ip.src == DNS_SERVERS[dns_name]:
                payload_size = (
                    len(icmp.original_data) - 4 if len(icmp.original_data) > 4 else 0
                )

                matching_requests = [
                    req
                    for req in results.requests
                    if req.dst_ip == ip.src and req.seq == seq and req.identifier == identifier
                ]

                if matching_requests:
                    req = matching_requests[0]
                    rtt = (recv_time - req.sent_time) * 1000
                    response = IcmpResponse(
                        src_ip=ip.src,
                        dst_ip=req.dst_ip,
                        ttl=req.ttl,
                        seq=seq,
                        identifier=identifier,
                        icmp_type=icmp.type,
                        payload_size=payload_size,
                        rtt_ms=rtt,
                    )
                    results.responses.append(response)

                    results.hops_by_target[req.dst_ip][req.ttl] = {
                        "router": ip.src,
                        "payload_size": payload_size,
                        "rtt_ms": rtt,
                        "destination": True,
                    }

    except Exception:
        pass


async def run_experiment():
    """Run the complete traceroute payload experiment"""
    # Create experiment results container
    results = ExperimentResults()

    # Generate all ICMP requests we'll need
    for dns_name, ip in DNS_SERVERS.items():
        identifier = DNS_IDENTIFIERS[dns_name]
        seq = 1  # Start at 1 for each DNS server

        for ttl in range(1, MAX_TTL + 1):
            for _ in range(RETRIES):  # Send multiple probes per hop for reliability
                results.requests.append(
                    IcmpRequest(dst_ip=ip, ttl=ttl, seq=seq, identifier=identifier)
                )
                seq += 1

    # Create the raw sockets
    raw_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    raw_socket.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

    icmp_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    icmp_socket.setblocking(False)

    # Run sender and receiver concurrently
    receiver_task = asyncio.create_task(receive_responses(results, icmp_socket))
    sender_task = asyncio.create_task(send_probes(results, raw_socket))

    await sender_task
    await receiver_task

    # Close sockets
    raw_socket.close()
    icmp_socket.close()

    # Generate results
    await generate_results(results)

    return results


async def generate_results(results):
    """Generate visualization and save results"""
    output_dir = "/home/david/Documents/voltadomar/test/results"
    os.makedirs(output_dir, exist_ok=True)

    save_json_results(results, output_dir)
    plot_payload_distribution(results, output_dir)


def save_json_results(results, output_dir):
    """Save raw results as JSON for further analysis"""
    # Convert to serializable format
    data = {
        "responses": [
            {
                "src_ip": r.src_ip,
                "dst_ip": r.dst_ip,
                "dns_name": next(
                    (name for name, ip in DNS_SERVERS.items() if ip == r.dst_ip), None
                ),
                "ttl": r.ttl,
                "seq": r.seq,
                "identifier": r.identifier,
                "icmp_type": r.icmp_type,
                "payload_size": r.payload_size,
                "rtt_ms": r.rtt_ms,
            }
            for r in results.responses
        ],
        "hops_by_target": dict(results.hops_by_target),
        "dns_identifiers": DNS_IDENTIFIERS,
    }

    # Save to file
    with open(f"{output_dir}/traceroute_results.json", "w") as f:
        json.dump(data, f, indent=2)

    print(f"Raw data saved to {output_dir}/traceroute_results.json")


def plot_payload_distribution(results, output_dir):
    """Create a stacked bar chart showing distribution of payload sizes by DNS provider"""
    plt.figure(figsize=(15, 8))

    # Group responses by DNS provider
    dns_stats = {}
    # Count how many requests were sent per DNS provider
    requests_per_dns = {}

    for req in results.requests:
        dns_name = next(
            (name for name, ip in DNS_SERVERS.items() if ip == req.dst_ip), req.dst_ip
        )
        requests_per_dns[dns_name] = requests_per_dns.get(dns_name, 0) + 1

    for resp in results.responses:
        dns_name = next(
            (name for name, ip in DNS_SERVERS.items() if ip == resp.dst_ip), resp.dst_ip
        )
        if dns_name not in dns_stats:
            dns_stats[dns_name] = {
                "zero": 0,
                "partial": 0,
                "full": 0,
                "extra": 0,
                "total": 0,
            }

        dns_stats[dns_name]["total"] += 1
        if resp.payload_size == 0:
            dns_stats[dns_name]["zero"] += 1
        elif resp.payload_size < PAYLOAD_SIZE:
            dns_stats[dns_name]["partial"] += 1
        elif resp.payload_size == PAYLOAD_SIZE:
            dns_stats[dns_name]["full"] += 1
        else:
            dns_stats[dns_name]["extra"] += 1

    # Add missing DNS providers with zero responses
    for dns_name in requests_per_dns:
        if dns_name not in dns_stats:
            dns_stats[dns_name] = {
                "zero": 0,
                "partial": 0,
                "full": 0,
                "extra": 0,
                "total": 0,
            }

    # Calculate dropped packets
    for dns_name, stats in dns_stats.items():
        stats["dropped"] = requests_per_dns.get(dns_name, 0) - stats["total"]
        stats["total_with_dropped"] = requests_per_dns.get(dns_name, 0)

    # Prepare data for plotting
    providers = list(dns_stats.keys())
    zero_pct = [
        stats["zero"] / stats["total_with_dropped"] * 100
        for stats in dns_stats.values()
    ]
    partial_pct = [
        stats["partial"] / stats["total_with_dropped"] * 100
        for stats in dns_stats.values()
    ]
    full_pct = [
        stats["full"] / stats["total_with_dropped"] * 100
        for stats in dns_stats.values()
    ]
    extra_pct = [
        stats["extra"] / stats["total_with_dropped"] * 100
        for stats in dns_stats.values()
    ]
    dropped_pct = [
        stats["dropped"] / stats["total_with_dropped"] * 100
        for stats in dns_stats.values()
    ]

    # Create stacked bar chart
    bar_width = 0.8
    x = np.arange(len(providers))

    # Plot dropped packets at the bottom (black)
    plt.bar(
        x, dropped_pct, bar_width, label="Dropped Packets", color="black", alpha=0.7
    )
    bottom = dropped_pct

    plt.bar(
        x,
        zero_pct,
        bar_width,
        bottom=bottom,
        label="Zero Payload",
        color="red",
        alpha=0.7,
    )
    bottom = [i + j for i, j in zip(bottom, zero_pct)]

    plt.bar(
        x,
        partial_pct,
        bar_width,
        bottom=bottom,
        label="Partial Payload",
        color="orange",
        alpha=0.7,
    )
    bottom = [i + j for i, j in zip(bottom, partial_pct)]

    plt.bar(
        x,
        full_pct,
        bar_width,
        bottom=bottom,
        label="Full Payload",
        color="green",
        alpha=0.7,
    )
    bottom = [i + j for i, j in zip(bottom, full_pct)]

    plt.bar(
        x,
        extra_pct,
        bar_width,
        bottom=bottom,
        label="Extra Payload",
        color="purple",
        alpha=0.7,
    )

    # Add labels and title
    plt.xlabel("DNS Provider")
    plt.ylabel("Percentage of Requests")
    plt.title("Distribution of Payload Sizes by DNS Provider")
    plt.xticks(x, providers, rotation=45, ha="right")
    plt.legend()
    plt.tight_layout()

    # Save figure
    plt.savefig(f"{output_dir}/payload_distribution.png", dpi=300)
    print(f"Payload distribution chart saved to {output_dir}/payload_distribution.png")


if __name__ == "__main__":
    asyncio.run(run_experiment())
