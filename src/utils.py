import socket

from packets import IP, UDP


def build_udp_probe(destination_ip, ttl, source_port, dst_port):
    '''
    Creates a UDP probe packet with the given parameters.
    '''
    ip_packet = IP(dst=destination_ip, ttl=ttl, proto=17)
    udp_packet = UDP(sport=source_port, dport=dst_port)
    return bytes(ip_packet) + bytes(udp_packet)


def resolve_hostname(ip):
    '''
    Resolve the hostname of a given IP address.
    '''
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return ip


def resolve_ip(hostname):
    '''
    Resolve the IP address of a given hostname.
    '''
    try:
        return socket.gethostbyname(hostname)
    except socket.gaierror:
        return None
