import argparse
import logging
from asyncio import Event, wait_for, TimeoutError, Lock
from abc import abstractmethod
from datetime import datetime
from scapy.all import IP, ICMP, UDP
from constants import TracerouteConf, TracerouteResult, BASE_PORT
from utils import resolve_ip, resolve_hostname

logger = logging.getLogger()


class Program:
    """Abstract class for a program that can be run by the controller."""

    def __init__(self, controller, session_id):
        self.controller = controller
        self.session_id = session_id

    @abstractmethod
    async def run(self, command):
        """Run the program with the given command."""
        raise NotImplementedError

    @abstractmethod
    async def handle_done(self, ack_payload):
        """Handle an DONE packet."""
        raise NotImplementedError

    @abstractmethod
    async def handle_reply(self, reply_payload, worker_id):
        """Handle a REPLY packet."""
        raise NotImplementedError

    @abstractmethod
    def filter_packets(self, packet):
        """Only accept packets that match the program session ID."""
        raise NotImplementedError


class Traceroute(Program):
    def __init__(self, controller, session_id):
        super().__init__(controller, session_id)
        self._finished = Event()
        self._tr_lock = Lock()  # TODO make this an array
        self.source_port = session_id

        self.sender_host = None
        self.destination_host = None
        self.destination_ip = None
        self.tr_conf = TracerouteConf()
        self.received_done = False
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
        parser.add_argument('-m', '--max-hops', type=int, default=20)
        parser.add_argument('-t', '--timeout', type=int, default=5)
        parser.add_argument('-n', '--probe-num', type=int, default=3)

        args = parser.parse_args(command.split()[1:])  # exclude 'volta' prefix

        self.sender_host = args.source
        self.destination_host = args.destination
        self.tr_conf.max_ttl = args.max_hops
        self.tr_conf.timeout = args.timeout
        self.tr_conf.probe_num = args.probe_num

        self.destination_ip = resolve_ip(self.destination_host)

        logger.info(
            f"Traceroute to {self.destination_host} ({self.destination_ip}) "
            f"from {self.sender_host}, {self.tr_conf.probe_num} probes, "
            f"{self.tr_conf.max_ttl} hops max"
        )

        udp_requests = []
        seq = 0
        for ttl in range(1, self.tr_conf.max_ttl + 1):
            for _ in range(self.tr_conf.probe_num):
                udp_requests.append((ttl, seq + BASE_PORT))
                seq += 1
        self.controller.send_job(self.session_id, self.destination_ip, udp_requests)

        logger.debug("Finished sending packets")

        try:
            await wait_for(self._finished.wait(), timeout=self.tr_conf.timeout)
        except TimeoutError:
            # Timed out, so print what we have so far
            pass

        return self._print_results()

    def filter_packets(self, packet):
        if len(packet) < 36:
            return False
        extracted = int.from_bytes(packet[28:30], byteorder='big')
        return extracted == self.source_port

    async def handle_done(self, done_payload):
        udp_acks = done_payload.udp_acks
        for udp_ack in udp_acks:
            seq = udp_ack.seq - BASE_PORT
            time = udp_ack.sent_time
            if seq < 0 or seq >= len(self.tr_results):
                logger.error(f"ACK sequence number {seq} is out of range")
                continue

            result = self.tr_results[seq]
            if result.t1:
                logger.error(f"ACK duplicate result for sequence {seq} (t1={result.t1}, t2={result.t2})")
                continue
            result.t1 = time

        self.received_done = True
        if self.received_done and self.waiting_tr == 0:
            self._finished.set()

    async def handle_reply(self, reply_payload, worker_id):
        raw_reply = reply_payload.raw_packet
        receive_time = reply_payload.time
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

        if self.received_done and self.waiting_tr == 0:
            self._finished.set()

    def _print_results(self):
        output = []
        output.append(
            f"Traceroute to {self.destination_host} ({self.destination_ip}) "
            f"from {self.sender_host}, {self.tr_conf.probe_num} probes, {self.tr_conf.max_ttl} hops max"
        )

        prev_gateway = None
        for ttl in range(1, self.tr_conf.max_ttl + 1):
            line_parts = [str(ttl)]
            start_seq = self.tr_conf.probe_num * (ttl - 1)
            end_seq = start_seq + self.tr_conf.probe_num
            found_final_dst = False

            for seq in range(start_seq, end_seq):
                current = self.tr_results[seq]

                if current.final_dst:
                    found_final_dst = True

                if current.timeout:
                    line_parts.append("*")
                    continue

                if current.gateway != prev_gateway:
                    line_parts.append(f"{resolve_hostname(current.gateway)} ({current.gateway})")
                    prev_gateway = current.gateway

                t1 = datetime.fromisoformat(current.t1)
                t2 = datetime.fromisoformat(current.t2)
                delta_ms = (t2 - t1).total_seconds() * 1000
                line_parts.append(f"{delta_ms:.3f} ms")

            output.append("  ".join(line_parts))
            if found_final_dst:
                break

        logger.debug(self.tr_results)
        return "\n".join(output)
