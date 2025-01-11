import grpc.aio
import logging
import asyncio
import socket
from google.protobuf.any_pb2 import Any
from anycast_pb2 import Message, AckPayload, SendPayload, ErrorPayload, ReplyPayload
from anycast_pb2_grpc import AnycastServiceStub
from datetime import datetime

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='worker.log',
    filemode='w'
)
logger = logging.getLogger(__name__)


class Agent:

    def __init__(self, worker_id, controller_address):
        self.worker_id = worker_id
        self.controller_address = controller_address
        self.hmac = None
        self.filter = None

        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.set_blocking(False)

        self.icmp_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        self.icmp_socket.setblocking(False)

    async def listener_agent(self, context):
        await context.write(Message(worker_id=self.worker_id, type="REGISTER"))
        loop = asyncio.get_event_loop()
        while True:
            packet, _ = await loop.sock_recv(self.icmp_socket, 65535)
            packed_payload = Any()
            packed_payload.Pack(ReplyPayload(raw_packet=packet, time=datetime.now().isoformat()))
            await context.write(Message(type="REPLY", payload=packed_payload))

    async def sender_agent(self, context, udp_socket):
        async for message in context:
            try:
                if message.type == "SEND":
                    send_payload = SendPayload()
                    message.payload.Unpack(send_payload)
                    session_id = send_payload.session_id
                    raw_packet = send_payload.raw_packet
                    seq = send_payload.seq
                    logger.debug(f"[Worker {self.worker_id}] Received SEND command")

                    loop = asyncio.get_event_loop()
                    loop.sock_sendto(udp_socket, raw_packet)
                    sent_time = datetime.now().isoformat()

                    packed_payload = Any()
                    packed_payload.Pack(AckPayload(session_id=session_id, seq=seq, time=sent_time))
                    logger.debug(f"[Worker {self.worker_id}] Sending ACK for sequence {seq}")
                    await context.write(Message(type="ACK", payload=packed_payload))

                else:
                    logger.error(f"[Worker {self.worker_id}] Unknown message type {message.type}")
                    continue

            except Exception as e:
                logger.error(f"[Worker {self.worker_id}] Error sending packet: {e}")
                error_payload = Any()
                error_payload.Pack(ErrorPayload(code=500, message=str(e)))
                await context.write(Message(type="ERROR", worker_id=self.worker_id, payload=error_payload))

    async def control_stream(self):
        async with grpc.aio.insecure_channel(self.controller_address) as channel:
            stub = AnycastServiceStub(channel)
            context = stub.ControlStream(self.listener_agent())
            await asyncio.gather(
                self.sender_agent(context),
                self.listener_agent(context)
            )


if __name__ == "__main__":
    agent = Agent(worker_id=1, controller_address="localhost:50051")
    agent.control_stream()
