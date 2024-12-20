import grpc
import logging
from asyncio import run
from threading import Thread, Event
from datetime import datetime
from google.protobuf.any_pb2 import Any
from anycast_pb2 import Message, AckPayload, StartPayload, SendPayload, ErrorPayload, ReplyPayload, StopPayload
from anycast_pb2_grpc import AnycastServiceStub
from sockets import send
from scapy.all import sniff

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='worker.log',
    filemode='w'
)
logger = logging.getLogger(__name__)


class Worker:

    def __init__(self, worker_id, controller_address):
        self.worker_id = worker_id
        self.controller_address = controller_address
        self.agents = {}  # session_id -> agent (thread, stop_event)

    def listener_agent(self, session_id, context, stop_event, hmac, filter):
        # TODO decrease coupling with scapy.sniff to use receive() from sockets.py
        async def forward_reply(packet):
            # TODO does async work here?
            packed = Any()
            packed.Pack(ReplyPayload(session_id=session_id, raw_packet=bytes(packet), time=datetime.fromtimestamp(packet.time).isoformat()))
            message = Message(type="REPLY", payload=packed)
            await context.write(message)
        sniff(prn=forward_reply, stop_filter=lambda _: stop_event.is_set(), filter=filter, store=False)

    async def control_stream(self):
        async with grpc.aio.insecure_channel(self.controller_address) as channel:
            stub = AnycastServiceStub(channel)
            async with stub.ControlStream(iter([Message(worker_id=self.worker_id, type="REGISTER")])) as context:
                async for message in context:
                    try:
                        if message.type == "START":
                            start_payload = StartPayload()
                            message.payload.Unpack(start_payload)
                            session_id = start_payload.session_id
                            hmac = start_payload.hmac
                            filter = start_payload.filter
                            logger.info(f"[Worker {self.worker_id}] Received START: sesison {session_id}, filter {filter}, hmac {hmac}")

                            stop_event = Event()
                            thread = Thread(target=self.listener_agent, args=(session_id, context, stop_event, hmac, filter))
                            self.agents[session_id] = (thread, stop_event)
                            thread.start()

                        elif message.type == "STOP":
                            stop_payload = StopPayload()
                            message.payload.Unpack(stop_payload)
                            session_id = stop_payload.session_id
                            logger.info(f"[Worker {self.worker_id}] Received STOP command")
                            if session_id in self.agents:
                                self.agents[session_id][1].set()
                                self.agents[session_id][0].join()
                                del self.agents[session_id]
                            else:
                                logger.error(f"[Worker {self.worker_id}] Received STOP for unknown session ID {session_id}")

                        elif message.type == "SEND":
                            send_payload = SendPayload()
                            message.payload.Unpack(send_payload)
                            raw_packet = send_payload.raw_packet
                            seq = send_payload.seq
                            logger.debug(f"[Worker {self.worker_id}] Received SEND command")
                            sent_time = send(raw_packet)

                            packed_payload = Any()
                            packed_payload.Pack(AckPayload(seq=seq, time=sent_time))
                            logger.debug(f"[Worker {self.worker_id}] Sending ACK for sequence {seq}")
                            await context.write(Message(type="ACK", worker_id=self.worker_id, payload=packed_payload))

                        else:
                            logger.error(f"[Worker {self.worker_id}] Unknown message type {message.type}")
                            raise ValueError(f"Unknown message type {message.type}")

                    except Exception as e:
                        logger.error(f"[Worker {self.worker_id}] Error sending packet: {e}")
                        error_payload = Any()
                        error_payload.Pack(ErrorPayload(code=500, message=str(e)))
                        await context.write(Message(type="ERROR", worker_id=self.worker_id, payload=error_payload))
                    finally:
                        for session_id, (thread, stop_event) in self.agents.items():
                            stop_event.set()
                            thread.join()


if __name__ == "__main__":
    worker = Worker(worker_id=1, controller_address="localhost:50051")
    run(worker.control_stream())
