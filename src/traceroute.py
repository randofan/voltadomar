import argparse
import logging
from asyncio import Event, wait_for, TimeoutError
from abc import abstractmethod
from datetime import datetime
from scapy.all import IP, ICMP, UDP
from constants import TracerouteConf, TracerouteResult, BASE_PORT
from utils import resolve_ip, build_udp_packet, resolve_hostname

logger = logging.getLogger()


class Program:
    """Abstract class for a program that can be run by the controller."""

    def __init__(self, controller, session_id):
        self.settings = {"hmac": None, "filter": "icmp"}  # universal settings for all agents
        self.controller = controller
        self.session_id = session_id

    @abstractmethod
    async def run(self, command):
        raise NotImplementedError

    @abstractmethod
    async def handle_ack(self, ack_payload):
        raise NotImplementedError

    @abstractmethod
    async def handle_reply(self, reply_payload, worker_id):
        raise NotImplementedError


class Traceroute(Program):
    def __init__(self, controller, session_id):
        super().__init__(controller, session_id)
        self._finished = Event()
        self.source_port = session_id

        self.sender_host = None
        self.destination_host = None
        self.destination_ip = None
        self.tr_conf = TracerouteConf(
            probe_num=3,
            max_ttl=20,
            timeout=5
        )
        self.waiting_tr = self.tr_conf.probe_num * self.tr_conf.max_ttl
        self.tr_results = [
            TracerouteResult(
                seq=i,
                t1=None,
                t2=None,
                receiver=None,
                gateway=None,
                timeout=True,
                final_dst=False
            ) for i in range(self.waiting_tr)
        ]

    async def run(self, command):
        parser = argparse.ArgumentParser()
        parser.add_argument('source', type=str)
        parser.add_argument('destination', type=str)
        parser.add_argument('-m', '--max-hops', type=int, default=30)
        parser.add_argument('-t', '--timeout', type=int, default=5)

        args = parser.parse_args(command.split()[1:])  # exclude 'volta' prefix

        self.sender_host = args.source
        self.destination_host = args.destination
        self.tr_conf.max_ttl = args.max_hops
        self.tr_conf.timeout = args.timeout

        self.destination_ip = resolve_ip(self.destination_host)

        logger.info(
            f"Traceroute to {self.destination_host} ({self.destination_ip}) "
            f"from {self.sender_host}, {self.tr_conf.probe_num} probes, "
            f"{self.tr_conf.max_ttl} hops max"
        )

        for index, result in enumerate(self.tr_results):
            ttl = (index // self.tr_conf.probe_num) + 1

            result['seq'] = index

            packet = build_udp_packet(
                destination_ip=self.destination_ip,
                ttl=ttl,
                sequence=index,
                source_port=self.source_port,
                base_port=BASE_PORT,
            )
            await self.controller.send_packet(self.sender_host, packet, index)

        logger.debug("Finished sending packets")

        try:
            await wait_for(self._finished.wait(), timeout=self.tr_conf.timeout)
        except TimeoutError:
            # Timed out, so print what we have so far
            pass
        return self._print_results()

    async def handle_ack(self, ack_payload):
        seq = ack_payload.seq
        time = ack_payload.time  # TODO: check formatting

        if seq < 0 or seq >= len(self.tr_results):
            logger.error(f"ACK sequence number {seq} is out of range")
            return

        result = self.tr_results[seq]
        if result.t1:
            logger.error(f"ACK duplicate result for sequence {seq} (t1={self.tr_results[seq].t1}, t2={self.tr_results[seq].t2})")
            return
        result.t1 = time

    async def handle_reply(self, reply_payload, worker_id):
        raw_reply = reply_payload.raw_packet
        receive_time = reply_payload.time  # TODO check formatting
        edge = worker_id

        ip = IP(raw_reply[14:])
        icmp = ip[ICMP]
        udp = IP(raw_reply[42:])[UDP]

        ip_src = ip.src
        icmp_type = icmp.type
        src_port = udp.sport
        dst_port = udp.dport

        logger.debug(f"Received reply from {edge} with receive time: {receive_time}"
                     f" (IP src: {ip_src}, ICMP type: {icmp_type}, UDP sport: {src_port}, UDP dport: {dst_port})")

        if src_port != self.source_port:
            logger.error(f"REPLY source port {src_port} does not match session ID {self.source_port}")
            return
        seq = dst_port - BASE_PORT
        if seq < 0 or seq >= len(self.tr_results):
            logger.error(f"REPLY sequence number {seq} is out of range")
            return
        if self.tr_results[seq].t2:
            logger.error(f"REPLY duplicate result for sequence {seq} (t1={self.tr_results[seq].t1}, t2={self.tr_results[seq].t2})")
            return

        result = self.tr_results[seq]
        result.t2 = receive_time
        result.receiver = edge
        result.gateway = ip_src
        result.timeout = False
        result.final_dst = (icmp_type == 3)
        self.waiting_tr -= 1

        logger.debug(f"Updated traceroute result for sequence {seq}: {result}"
                     f" (Waiting TTLs: {self.waiting_tr})")

        if self.waiting_tr == 0:
            self._finished.set()

    def _print_results(self):
        output = []
        output.append(
            f"Traceroute to {self.destination_host} ({self.destination_ip}) "
            f"from {self.sender_host}, {self.tr_conf.probe_num} probes, {self.tr_conf.max_ttl} hops max"
        )

        # TODO this format doesn't exactly match the original traceroute.
        #
        # In traceroute, for a given row/TTL, it doesn't print any repetitive
        # gateways. Currently, the code below only omits repetitive gateways
        # if all the gateways are the same. For example, in traceroute:
        # 12  142.251.50.175 (142.251.50.175)  14.856 ms  14.959 ms sea30s10-in-f4.1e100.net (142.251.33.100)  14.779 ms
        #                                                 ^ same gateway as previous, despite third being different
        for seq in range(0, len(self.tr_results), self.tr_conf.probe_num):
            ttl = seq // self.tr_conf.probe_num
            line = f"{ttl + 1}"
            same_gateway = (
                len({self.tr_results[seq + i].gateway for i in range(self.tr_conf.probe_num)}) == 1
            )
            for i in range(self.tr_conf.probe_num):
                result = self.tr_results[seq + i]
                if result.timeout:
                    line += "  *"
                    continue

                gateway = result.gateway if not same_gateway or i == 0 else None
                if gateway:
                    line += f"  {resolve_hostname(gateway)} ({gateway})"
                t1 = datetime.fromisoformat(result.t1)
                t2 = datetime.fromisoformat(result.t2)
                delta_ms = (t2 - t1).total_seconds() * 1000
                line += f"  {delta_ms:.3f} ms"

            output.append(line)

            if any(self.tr_results[seq + i].final_dst for i in range(self.tr_conf.probe_num)):
                # Only return TTLs up to the final destination.
                break

        logger.debug(self.tr_results)
        return "\n".join(output)
