import time
from datetime import datetime
from scapy.all import conf, IP, sniff


def send(packet):
    """Send a packet and return the time it was sent."""

    def timed_send(self, pkt):
        original_send(self, pkt)
        send_time = time.time()
        t = datetime.fromtimestamp(send_time).isoformat()
        return t
    reconstructed_packet = IP(packet)
    original_send = conf.L3socket.send
    conf.L3socket.send = timed_send
    return conf.L3socket().send(reconstructed_packet)


def receive(hmac, filter):
    """Capture packets and return (bytes(packet), receive_time) tuple as a generator."""

    while True:
        packets = sniff(count=1, filter=filter, store=False, timeout=1)
        if packets:
            pkt = packets[0]
            yield bytes(pkt), datetime.fromtimestamp(pkt.time).isoformat()
        else:
            yield None, None
