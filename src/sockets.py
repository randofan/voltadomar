import time
import asyncio
from datetime import datetime
from scapy.all import conf, IP, AsyncSniffer
from queue import Queue


def send(packet):
    """Send a packet and return the time it was sent.

    Args:
        packet (bytes): L3 raw packet to be sent.
    """
    def timed_send(self, pkt):
        original_send(self, pkt)
        send_time = time.time()
        t = datetime.fromtimestamp(send_time).isoformat()
        return t
    reconstructed_packet = IP(packet)
    original_send = conf.L3socket.send
    conf.L3socket.send = timed_send
    return conf.L3socket().send(reconstructed_packet)


async def receive(hmac, filter):
    # TODO rewrite this to be synchronous like scapy.sniff()
    """Capture packets and return them as a generator.

    Args:
        hmac (str): The HMAC key for packet authentication.
        filter (str): A pcap-filter string to capture only desired packets.

    Yields:
        tuple: A tuple containing the packet (bytes) and the time it was received (datetime in ISO 8601 format).
        If no packets have been captured, yields (None, None).
    """
    queue = Queue()
    sniffer = AsyncSniffer(prn=lambda p: queue.put(bytes(p), datetime.fromtimestamp(p.time)), filter=filter, store=False)
    sniffer.start()

    loop = asyncio.get_event_loop()
    try:
        while True:
            yield await loop.run_in_executor(None, queue.get)
    finally:
        sniffer.stop()
        loop.run_until_complete(sniffer.join())
