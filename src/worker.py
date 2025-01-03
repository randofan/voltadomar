import grpc.aio
import logging
from asyncio import Task, Event
from google.protobuf.any_pb2 import Any
from anycast_pb2 import Message, AckPayload, StartPayload, SendPayload, ErrorPayload, ReplyPayload, StopPayload
from anycast_pb2_grpc import AnycastServiceStub
from sockets import send, receive

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

    async def listener_agent(self, session_id, context, stop_event, hmac, filter):
        for packet, time in receive(hmac, filter):
            if stop_event.is_set():
                break
            if not packet:
                continue
            packed_payload = Any()
            packed_payload.Pack(ReplyPayload(session_id=session_id, raw_packet=packet, time=time))
            message = Message(type="REPLY", payload=packed_payload)
            await context.write(message)

    async def control_stream(self):
        with grpc.aio.insecure_channel(self.controller_address) as channel:
            stub = AnycastServiceStub(channel)
            async with stub.ControlStream(iter([Message(worker_id=self.worker_id, type="REGISTER")])) as context:
                for message in context:
                    try:
                        if message.type == "START":
                            start_payload = StartPayload()
                            message.payload.Unpack(start_payload)
                            session_id = start_payload.session_id
                            hmac = start_payload.hmac
                            filter = start_payload.filter
                            logger.info(f"[Worker {self.worker_id}] Received START for session {session_id}")

                            stop_event = Event()
                            thread = Thread(target=self.listener_agent, args=(session_id, context, stop_event, hmac, filter))
                            self.agents[session_id] = (thread, stop_event)
                            thread.start()
                            logger.debug(f"[Worker {self.worker_id}] Started agent for session {session_id}")

                        elif message.type == "STOP":
                            stop_payload = StopPayload()
                            message.payload.Unpack(stop_payload)
                            session_id = stop_payload.session_id
                            logger.info(f"[Worker {self.worker_id}] Received STOP command for session {session_id}")
                            if session_id in self.agents:
                                thread, stop_event = self.agents[session_id]
                                stop_event.set()
                                thread.join()
                                del self.agents[session_id]
                                logger.debug(f"[Worker {self.worker_id}] Stopped agent for session {session_id}")
                            else:
                                logger.error(f"[Worker {self.worker_id}] Received STOP for unknown session ID {session_id}")

                        elif message.type == "SEND":
                            send_payload = SendPayload()
                            message.payload.Unpack(send_payload)
                            session_id = send_payload.session_id
                            raw_packet = send_payload.raw_packet
                            seq = send_payload.seq
                            logger.debug(f"[Worker {self.worker_id}] Received SEND command")
                            sent_time = send(raw_packet)

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
                    finally:
                        for session_id, (thread, stop_event) in self.agents.items():
                            stop_event.set()
                            thread.join()


if __name__ == "__main__":
    worker = Worker(worker_id=1, controller_address="localhost:50051")
    worker.control_stream()
