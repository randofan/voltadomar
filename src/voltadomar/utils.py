"""
utils.py

Utility functions used throughout the application.

Author: David Song <davsong@cs.washington.edu>
"""

import socket
import struct

from voltadomar.packets import IP, UDP, ICMP


def build_udp_probe(destination_ip, ttl, source_port, dst_port):
    """Creates a UDP probe packet with the given parameters."""
    ip_packet = IP(dst=destination_ip, ttl=ttl, proto=17)
    udp_packet = UDP(sport=source_port, dport=dst_port)
    return bytes(ip_packet) + bytes(udp_packet)


def build_icmp_probe(destination_ip, ttl, seq, identifier):
    """Creates an ICMP probe packet with the given parameters."""
    ip_packet = IP(dst=destination_ip, ttl=ttl, proto=1)
    icmp_packet = ICMP(type=8, code=0)

    header_data = struct.pack("!HH", identifier, seq)
    # Depending on the router configuration, the payload is either
    # dropped, preserved, or padded in the corresponding ICMP echo
    # reply.
    payload_data = b"ubiquitous" * 4  # 40 bytes

    icmp_packet._original_data = header_data + payload_data
    return bytes(ip_packet) + bytes(icmp_packet)


def resolve_hostname(ip):
    """Resolve the hostname of a given IP address."""
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return ip


def resolve_ip(hostname):
    """Resolve the IP address of a given hostname."""
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None
