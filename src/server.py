import grpc
from queue import Queue, Empty
from threading import Thread
from concurrent import futures
import anycast_pb2
import anycast_pb2_grpc
from scapy.all import sendp, sniff, Ether
import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


class AnycastServiceServicer(anycast_pb2_grpc.AnycastServiceServicer):
    def __init__(self):
        """Store internal state for the worker agent.

        Fields:
            hmac (bytes): authenticate incoming packets to prevent abuse.
            host (int): ID of the worker agent assigned by the controller.
            queue (Queue): stores packets captured by the sniffer.

        In the future, we aim to replace the HMAC and filter option with an
        kernel eBFP filter for better performance.
        """
        self.hmac = None
        self.host = None
        self.queue = Queue()

    def sniffer(self, filter):
        """Capture packets and put them in a queue.

        Because the sniff function is synchronous, it is run in a separate
        thread to avoid blocking the gRPC server.

        Args:
            filter (string): Set a filter on sniff to only capture desired
            packets.
        """
        sniff(prn=lambda packet: self.queue.put((packet, datetime.now())), filter=filter, store=False)

    def ReceiverAgent(self, request, context):
        """Initialize worker agent to forward packets.

        Args:
            request (InitRequest): gRPC request object. It sets state at
            the worker agent and starts a sniffer thread to capture packets.
            - HMAC
            - Host ID
            - Filter

        Yields:
            ForwardPacket: gRPC response stream object.
            - Raw packet
            - Host ID
            - Receive timestamp (ISO format)
        """
        self.hmac = request.hmac
        self.host = request.host
        sniffer_thread = Thread(target=self.sniffer, args=(request.filter,))
        sniffer_thread.start()
        while context.is_active():
            try:
                packet, timestamp = self.queue.get(timeout=1)
                yield anycast_pb2.ForwardPacket(raw_reply=packet, host=self.host, receive_time=timestamp.isoformat())
            except Empty:
                logger.info("No packets received")
                continue
        sniffer_thread.join()
        # TODO: anything else to clean up + safely exit.

    def SendPacket(self, request, context):
        """Send a raw packet from the worker agent.

        Args:
            request (SendRequest): gRPC request object.
            - Raw packet

        Returns:
            CommandResponse: gRPC response object.
            - Status code indicating if the packet was sent
            - Sent timestamp (ISO format)
        """
        try:
            logger.info("Sending packet")
            sent_time = datetime.now().isoformat()
            sendp(Ether(request.raw_request), iface="ens3")
            return anycast_pb2.CommandResponse(code=200, sent_time=sent_time)
        except Exception:
            return anycast_pb2.CommandResponse(code=500)


def serve(port):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    anycast_pb2_grpc.add_AnycastServiceServicer_to_server(AnycastServiceServicer(), server)
    server.add_insecure_port(f'0.0.0.0:{port}')
    server.start()
    logger.info(f"Server started on port {port}")
    server.wait_for_termination()


if __name__ == '__main__':
    serve(port=50051)
