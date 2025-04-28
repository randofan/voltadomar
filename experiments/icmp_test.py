from datetime import datetime
from asyncio import sleep, get_event_loop, run, gather
from dataclasses import dataclass
import socket
import struct
import time
from packets import IP, ICMP


def build_icmp_probe(destination_ip, ttl, seq):
    """
    Creates an ICMP probe packet with the given parameters.
    """
    ip_packet = IP(dst=destination_ip, ttl=ttl, proto=1)  # proto=1 for ICMP
    icmp_packet = ICMP(type=8, code=0)
    identifier = 0x0001
    header_data = struct.pack("!HH", identifier, seq)
    payload_data = b"ubiquitous" * 4
    icmp_packet._original_data = header_data + payload_data
    return bytes(ip_packet) + bytes(icmp_packet)


@dataclass
class JobPayload:
    dst_ip: str
    icmp_requests: list


@dataclass
class IcmpRequest:
    ttl: int
    seq: int


async def sender_worker(job_payload, icmp_socket):
    loop = get_event_loop()
    for icmp_request in job_payload.icmp_requests:
        packet = build_icmp_probe(
            destination_ip=job_payload.dst_ip,
            ttl=icmp_request.ttl,
            seq=icmp_request.seq,
        )
        try:
            num = await loop.sock_sendto(icmp_socket, packet, (job_payload.dst_ip, 0))
            exact_time = time.time_ns() / 1e9
            sent_time = datetime.fromtimestamp(exact_time).isoformat()
            print(f"Sent ICMP packet {icmp_request.seq} with {num} bytes at {sent_time}")
        except BlockingIOError:
            print("Socket is full, try again later")
            await sleep(0.1)


async def receiver_worker(icmp_socket):
    loop = get_event_loop()
    while True:
        raw_packet = await loop.sock_recv(icmp_socket, 65535)
        exact_time = time.time_ns() / 1e9
        recv_time = datetime.fromtimestamp(exact_time).isoformat()
        if len(raw_packet) < 28:
            print(f"Received packet too small: {len(raw_packet)} bytes")
            continue

        ip = IP(raw_packet)
        icmp = ICMP(ip.payload)

        if icmp.type == 11:  # Time Exceeded
            try:
                inner_ip = IP(icmp.original_data)
                inner_icmp = ICMP(inner_ip.payload)
                payload_len = len(icmp.original_data)

                if len(inner_icmp.original_data) >= 4:
                    identifier, seq = struct.unpack("!HH", inner_icmp.original_data[:4])
                    print(f"Received ICMP Time Exceeded at {recv_time} from {ip.src}, type: {icmp.type}, code: {icmp.code}, seq: {seq}, payload length: {payload_len}")
                else:
                    print(f"Received ICMP Time Exceeded at {recv_time} from {ip.src}, type: {icmp.type}, code: {icmp.code}, packet too small to extract seq, payload length: {payload_len}")
            except Exception as e:
                print(f"Error parsing inner packet: {e}")
        elif icmp.type == 0:  # Echo Reply
            payload_len = len(icmp.original_data)
            if len(icmp.original_data) >= 4:
                identifier, seq = struct.unpack("!HH", icmp.original_data[:4])
                payload = icmp.original_data[4:]  # Get the payload (should be "ubiquitous" repeated 4 times)
                print(f"Received ICMP Echo Reply at {recv_time} from {ip.src}, seq: {seq}, payload: {payload[:20]}..., payload length: {payload_len}")
            else:
                print(f"Received ICMP Echo Reply at {recv_time} from {ip.src}, packet too small to extract seq, payload length: {payload_len}")
        else:
            payload_len = len(icmp.original_data)
            print(f"Received ICMP packet at {recv_time} from {ip.src}, type: {icmp.type}, code: {icmp.code}, payload length: {payload_len}")


async def main(job_payload):
    raw_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
    raw_socket.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
    raw_socket.setblocking(False)

    icmp_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
    icmp_socket.setblocking(False)

    sender_task = sender_worker(job_payload, raw_socket)
    receiver_task = receiver_worker(icmp_socket)

    await gather(sender_task, receiver_task)


if __name__ == "__main__":
    job = JobPayload(
        dst_ip="8.8.8.8",
        icmp_requests=[
            IcmpRequest(ttl=5, seq=1),
            IcmpRequest(ttl=5, seq=2),
            IcmpRequest(ttl=5, seq=3),
            IcmpRequest(ttl=6, seq=4),
            IcmpRequest(ttl=6, seq=5),
            IcmpRequest(ttl=6, seq=6),
            IcmpRequest(ttl=7, seq=7),
            IcmpRequest(ttl=7, seq=8),
            IcmpRequest(ttl=7, seq=9),
        ],
    )
    run(main(job))
