from datetime import datetime
from asyncio import sleep, get_event_loop, run, gather
from dataclasses import dataclass
import socket
import time
from utils import build_udp_probe
from packets import IP, ICMP, UDP


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
            source_port=session_id,
            dst_port=udp_request.seq + job_payload.base_port,
        )
        try:
            num = await loop.sock_sendto(udp_socket, packet, (job_payload.dst_ip, 0))
            exact_time = time.time_ns() / 1e9
            sent_time = datetime.fromtimestamp(exact_time).isoformat()
            print(f"Sent packet {udp_request.seq} with {num} bytes at {sent_time}")
        except BlockingIOError:
            print("Socket is full, try again later")
            await sleep(0.1)


async def receiver_worker(icmp_socket):
    loop = get_event_loop()
    while True:
        raw_packet = await loop.sock_recv(icmp_socket, 65535)
        exact_time = time.time_ns() / 1e9
        recv_time = datetime.fromtimestamp(exact_time).isoformat()
        if len(raw_packet) < 36:
            return False

        ip = IP(raw_packet)
        icmp = ICMP(ip.payload)
        inner_ip = IP(icmp.original_data)
        udp = UDP(inner_ip.payload)

        ip_src = ip.src
        icmp_type = icmp.type
        src_port = udp.sport
        dst_port = udp.dport
        print(f"Received ICMP packet at {recv_time} with IP src: {ip_src}, ICMP type: {icmp_type}, UDP sport: {src_port}, UDP dport: {dst_port}")


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
