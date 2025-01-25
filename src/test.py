from datetime import datetime
from asyncio import sleep, get_event_loop, run, gather
from dataclasses import dataclass
import socket
from scapy.all import IP, UDP


def build_udp_probe(destination_ip, ttl, sequence, source_port, base_port):
    dst_port = base_port + sequence
    packet = IP(dst=destination_ip, ttl=ttl) / UDP(sport=source_port, dport=dst_port)
    return bytes(packet)


@dataclass
class JobPayload:
    dst_ip: str
    base_port: int
    udp_requests: list


@dataclass
class UdpRequest:
    ttl: int
    seq: int


async def sender_worker(job_payload, udp_socket):
    session_id = 0x5555
    loop = get_event_loop()
    for udp_request in job_payload.udp_requests:
        packet = build_udp_probe(
            destination_ip=job_payload.dst_ip,
            ttl=udp_request.ttl,
            sequence=udp_request.seq,
            source_port=session_id,
            base_port=job_payload.base_port,
        )
        try:
            num = await loop.sock_sendto(udp_socket, packet, (job_payload.dst_ip, 0))
            sent_time = datetime.now().isoformat()
            print(f"Sent packet {udp_request.seq} with {num} bytes at {sent_time}")
        except BlockingIOError:
            print("Socket is full, try again later")
            await sleep(0.1)


async def receiver_worker(icmp_socket):
    loop = get_event_loop()
    while True:
        try:
            packet = await loop.sock_recv(icmp_socket, 65535)
            received_time = datetime.now().isoformat()
            print(f"Received ICMP packet at {received_time} with {len(packet)} bytes")
        except Exception as e:
            print(f"Error receiving ICMP packet: {e}")
            await sleep(0.1)


async def main(job_payload):
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    udp_socket.setblocking(False)

    icmp_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    icmp_socket.setblocking(False)

    sender_task = sender_worker(job_payload, udp_socket)
    receiver_task = receiver_worker(icmp_socket)

    await gather(sender_task, receiver_task)


if __name__ == '__main__':
    job = JobPayload(
        dst_ip="8.8.8.8",
        base_port=33434,
        udp_requests=[
            UdpRequest(ttl=5, seq=0),
            UdpRequest(ttl=5, seq=1),
            UdpRequest(ttl=5, seq=2),
            UdpRequest(ttl=6, seq=3),
            UdpRequest(ttl=6, seq=4),
            UdpRequest(ttl=6, seq=5),
            UdpRequest(ttl=7, seq=6),
            UdpRequest(ttl=7, seq=7),
            UdpRequest(ttl=7, seq=8),
        ]
    )
    run(main(job))
