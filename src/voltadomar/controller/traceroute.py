"""
controller/traceroute.py

Traceroute program to handle traceroute requests.

Author: David Song <davsong@cs.washington.edu>
"""

import asyncio
import argparse
import logging
from datetime import datetime
from dataclasses import dataclass
from anycast.anycast_pb2 import JobPayload

from packets import IP, ICMP, UDP
from utils import resolve_ip, resolve_hostname
from voltadomar.controller.program import Program, ProgramConf

logger = logging.getLogger()


def parse_traceroute_args(command: str) -> tuple:
    """
    Parse the arguments for the traceroute program string.
    Usage: volta <source> <destination> [-m <max hops>] [-t <timeout>] [-n <probe num>]
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=str)
    parser.add_argument("destination", type=str)
    parser.add_argument("-m", "--max-hops", type=int, default=20)
    parser.add_argument("-t", "--timeout", type=int, default=10)
    parser.add_argument("-n", "--probe-num", type=int, default=3)

    args = parser.parse_args(command.split()[1:])  # exclude "volta" prefix
    return (args.source, args.destination, args.max_hops,
            args.timeout, args.probe_num)


@dataclass
class TracerouteResult:
    """
    Represents the result of a traceroute probe.

    Attributes:
        seq (int): The sequence number of the probe.
        t1 (float): The time when the probe was sent.
        t2 (float): The time when the probe was received.
        receiver (str): The anycast node receiver of the probe.
        gateway (str): The gateway where the probe timed out.
        timeout (bool): Indicates if the probe timed out.
        final_dst (bool): Indicates if the probe reached the final destination.
    """
    seq: int
    t1: float  # Probe sent
    t2: float  # Probe received
    receiver: str
    gateway: str
    timeout: bool
    final_dst: bool


@dataclass
class TracerouteConf(ProgramConf):
    """
    Represents the configuration for a traceroute operation.

    Attributes:
        probe_num (int): The number of probes to send per TTL.
        max_ttl (int): The maximum TTL to reach.
        timeout (int): The timeout for the program.
    """
    source_host: str
    destination_host: str
    start_id: int
    probe_num: int = 3
    max_ttl: int = 30
    timeout: int = 5


class Traceroute(Program):
    def __init__(self, controller, conf):
        super().__init__(controller, conf)
        self._finished = asyncio.Event()

    def _check_done(self):
        """
        Update the state of the program.
        """
        if self.received_done and self.waiting_tr == 0:
            logger.debug("Traceroute finished")
            self._finished.set()
        else:
            logger.debug("Traceroute still waiting for results")
            pass

    async def run(self):
        """
        Run the traceroute program.
        """
        self.received_done = False
        self.waiting_tr = self.conf.probe_num * self.conf.max_ttl
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

        self.session_id = self.conf.start_id
        self.sender_host = self.conf.sender_host
        self.destination_host = self.conf.destination_host
        self.destination_ip = resolve_ip(self.destination_host)

        logger.info(
            f"Traceroute to {self.destination_host} ({self.destination_ip}) "
            f"from {self.sender_host}, {self.conf.probe_num} probes, "
            f"{self.conf.max_ttl} hops max, timeout {self.conf.timeout} seconds"
        )

        job_payload = JobPayload(session_id=self.session_id, dst_ip=self.destination_ip,
                                 max_ttl=self.conf.max_ttl, probe_num=self.conf.probe_num,
                                 base_port=self._seq_to_port(0))
        await self.controller.send_job(self.sender_host, job_payload)
        logger.debug("Finished sending JOB")

        try:
            await asyncio.wait_for(self._finished.wait(), timeout=self.conf.timeout)
            logger.debug("Finished waiting for results")
        except asyncio.TimeoutError:
            # Timed out, so print what we have so far
            logger.debug("Timed out waiting for results")
            pass

        return self._print_results()

    def _seq_to_port(self, seq):
        """
        Convert a sequence number to a port number.
        """
        return seq + self.session_id

    def _port_to_seq(self, port):
        """
        Convert a port number to a sequence number.
        """
        return port - self.session_id

    def handle_done(self, done_payload):
        """
        Handles a DONE packet from an agent.
        """
        udp_acks = done_payload.udp_acks
        for udp_ack in udp_acks:
            seq = self._port_to_seq(udp_ack.seq)
            time = udp_ack.sent_time
            if seq < 0 or seq >= len(self.tr_results):
                logger.error(f"ACK sequence number {seq} is out of range")
                continue

            result = self.tr_results[seq]
            if result.t1:
                logger.error(f"ACK duplicate result for sequence {seq} (t1={result.t1}, t2={result.t2})")
                continue
            result.t1 = time
            logger.debug(f"Updated traceroute result for sequence {seq}: {result}")

        self.received_done = True
        self._check_done()

    def handle_reply(self, reply_payload, agent_id):
        """
        Handles a reply packet from an agent.
        """
        raw_packet = reply_payload.raw_packet
        receive_time = reply_payload.time
        edge = agent_id

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

        if src_port != self.session_id:
            logger.debug(f"REPLY source port {src_port} does not match session ID {self.session_id}")
            return False

        logger.debug(f"Received reply from {edge} with receive time: {receive_time}"
                     f" (IP src: {ip_src}, ICMP type: {icmp_type}, UDP sport: {src_port}, UDP dport: {dst_port})")

        seq = self._port_to_seq(src_port)
        if seq < 0 or seq >= len(self.tr_results):
            logger.error(f"REPLY sequence number {seq} is out of range")
            return True
        if self.tr_results[seq].t2:
            logger.error(f"REPLY duplicate result for sequence {seq} (t1={self.tr_results[seq].t1}, t2={self.tr_results[seq].t2})")
            return True

        result = self.tr_results[seq]
        result.t2 = receive_time
        result.receiver = edge
        result.gateway = ip_src
        result.timeout = False
        result.final_dst = (icmp_type == 3)
        self.waiting_tr -= 1

        logger.debug(f"Updated traceroute result for sequence {seq}: {result}"
                     f" (Waiting TTLs: {self.waiting_tr})")

        self._check_done()
        return True

    def _print_results(self):
        """
        Formats the traceroute results in a human-readable string.
        """
        output = []
        output.append(
            f"Traceroute to {self.destination_host} ({self.destination_ip}) "
            f"from {self.sender_host}, {self.conf.probe_num} probes, {self.conf.max_ttl} hops max"
        )

        for ttl in range(1, self.conf.max_ttl + 1):
            line_parts = [str(ttl)]
            start_seq = self.conf.probe_num * (ttl - 1)
            found_final_dst = False

            prev_gateway = None
            prev_receiver = None
            for seq in range(start_seq, start_seq + self.conf.probe_num):
                current = self.tr_results[seq]

                if current.timeout:
                    line_parts.append("*")
                    continue

                if current.final_dst:
                    found_final_dst = True

                if current.gateway != prev_gateway or current.receiver != prev_receiver:
                    line_parts.append(f"{resolve_hostname(current.gateway)} ({current.gateway}) {current.receiver}")
                    prev_gateway = current.gateway
                    prev_receiver = current.receiver

                t1 = datetime.fromisoformat(current.t1)
                t2 = datetime.fromisoformat(current.t2)
                delta_ms = (t2 - t1).total_seconds() * 1000
                line_parts.append(f"{delta_ms:.3f} ms")

            output.append("  ".join(line_parts))
            if found_final_dst:
                break

        logger.debug(self.tr_results)
        return "\n".join(output)
