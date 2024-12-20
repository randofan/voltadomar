import socket
from scapy.all import IP, UDP


def build_udp_packet(destination_ip, ttl, sequence, source_port, base_port):
    dst_port = base_port + sequence
    packet = IP(dst=destination_ip, ttl=ttl) / UDP(sport=source_port, dport=dst_port)
    return bytes(packet)


def resolve_hostname(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return ip


def resolve_ip(hostname):
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None
