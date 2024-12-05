import asyncio
import socket
from controller import Controller
from scapy.all import IP, UDP, ICMP
import os
import sys
from constants import BASE_PORT, TracerouteResult, TracerouteConf
import logging
from datetime import datetime


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger()


def build_udp_packet(destination_ip, ttl, sequence, source_port, base_port):
    dst_port = base_port + sequence
    logger.debug(
        f"Building UDP packet: destination_ip={destination_ip}, ttl={ttl}, sequence={sequence}, "
        f"source_port={source_port}, destination_port={dst_port}"
    )
    packet = IP(dst=destination_ip, ttl=ttl) / UDP(sport=source_port, dport=dst_port)
    return bytes(packet)


def resolve_hostname(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except socket.herror:
        return ip


class TracerouteController(Controller):
    def __init__(self, server_addresses):
        super().__init__(server_addresses)
        self.sender_host = None
        self.destination_host = None
        self.destination_ip = None
        self.tr_conf = TracerouteConf(
            probe_num=3,
            max_ttl=20,
            timeout=5
        )
        self.tr_results = [
            TracerouteResult(
                seq=i,
                t1=None,
                t2=None,
                receiver=None,
                gateway=None,
                timeout=True,
                final_dst=False
            ) for i in range(self.tr_conf.probe_num * self.tr_conf.max_ttl)
        ]
        self.waiting_ttls = len(self.tr_results)

    def print_results(self):
        print(f"Traceroute to {self.destination_host} ({self.destination_ip}) from {self.sender_host}, {self.tr_conf.probe_num} probes, {self.tr_conf.max_ttl} hops max")
        for seq in range(0, len(self.tr_results), self.tr_conf.probe_num):
            ttl = seq // self.tr_conf.probe_num
            print(f"{ttl + 1}", end="")

            same_gateway = len(set(self.tr_results[seq + i].gateway for i in range(self.tr_conf.probe_num))) == 1
            for i in range(self.tr_conf.probe_num):
                result = self.tr_results[seq + i]
                if result.timeout:
                    print("  *", end="")
                    continue

                gateway = result.gateway if not same_gateway or i == 0 else None
                if gateway:
                    print(f"  {resolve_hostname(gateway)} ({gateway})", end="")
                t1 = datetime.fromisoformat(result.t1)
                t2 = datetime.fromisoformat(result.t2)
                delta_ms = (t2 - t1).total_seconds() * 1000
                print(f"  {delta_ms:.3f} ms", end="")
            print("")
            if any(self.tr_results[seq + i].final_dst for i in range(self.tr_conf.probe_num)):
                break
        logger.debug(self.tr_results)
        exit()

    def handle_reply(self, response):
        raw_reply = response.raw_reply
        edge = response.host
        receive_time = response.receive_time

        logger.debug(f"Received raw reply: {raw_reply}")
        logger.debug(f"Edge: {edge}, Receive time: {receive_time}")

        ip = IP(raw_reply[14:])
        icmp = ip[ICMP]
        udp = IP(raw_reply[42:])[UDP]

        ip_src = ip.src

        logger.debug(f"IP src: {ip_src}, ICMP type: {icmp.type}, UDP sport: {udp.sport}, UDP dport: {udp.dport}")

        icmp_type = icmp.type
        # icmp_code = icmp.code
        src_port = udp.sport
        dst_port = udp.dport

        if src_port != os.getpid() % 65535:
            logger.debug(f"Source port {src_port} does not match process ID {os.getpid()}")
            return

        seq = dst_port - BASE_PORT
        if seq < 0 or seq >= len(self.tr_results):
            logger.debug(f"Sequence number {seq} is out of range")
            return
        if not self.tr_results[seq].t1 or self.tr_results[seq].t2:
            logger.error(f"Duplicate result for sequence {seq} (t1={self.tr_results[seq].t1}, t2={self.tr_results[seq].t2})")
            return

        result = self.tr_results[seq]
        result.t2 = receive_time
        result.receiver = edge
        result.gateway = ip_src
        result.timeout = False
        result.final_dst = (icmp_type == 3)
        self.waiting_ttls -= 1

        logger.debug(f"Updated traceroute result for sequence {seq}: {result}")
        logger.debug(f"Waiting TTLs: {self.waiting_ttls}")

        if self.waiting_ttls == 0:
            self.print_results()

    async def run(self, /, sender_host, destination_host):
        try:
            self.sender_host = sender_host
            self.destination_host = destination_host
            self.destination_ip = socket.gethostbyname(destination_host)
            logger.debug(f"Traceroute from {self.sender_host} to {self.destination_host} ({self.destination_ip})")
        except socket.gaierror:
            logger.error("Invalid destination host")
            return

        logger.debug("Starting receiver agents")
        self.run_receiver_agents(hmac=b"123456", filter="icmp")
        logger.debug("Receiver agents started")
        logger.debug("Sending packets")
        source_port = os.getpid() % 65535
        for index, result in enumerate(self.tr_results):
            ttl = (index // self.tr_conf.probe_num) + 1
            probe_num = (index % self.tr_conf.probe_num) + 1
            sequence = (ttl - 1) * self.tr_conf.probe_num + (probe_num - 1)

            packet = build_udp_packet(
                destination_ip=self.destination_ip,
                ttl=ttl,
                sequence=sequence,
                source_port=source_port,
                base_port=BASE_PORT,
            )

            response = await self.send_packet(sender_host, packet)
            if response.code == 200:
                result.t1 = response.sent_time
            else:
                logger.error(f"Error sending packet: {response.code}")
        logger.debug("Packets sent")
        await asyncio.sleep(self.tr_conf.timeout)
        await self.stop_receiver_agents()
        self.print_results()


async def main():
    server_addresses = ["127.0.0.1:50051"]
    client = TracerouteController(server_addresses=server_addresses)
    await client.run(sender_host="127.0.0.1:50051", destination_host="www.google.com")

if __name__ == "__main__":
    asyncio.run(main())
