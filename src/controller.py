import os
import grpc
import ast
import logging
from concurrent import futures
import anycast_pb2_grpc
from anycast_pb2 import ReplyPayload, AckPayload, SendPayload, Message, StartPayload, ErrorPayload, RegisterPayload, StopPayload, Response
from google.protobuf.any_pb2 import Any
from traceroute import Traceroute

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='controller.log',
    filemode='w'
)
logger = logging.getLogger(__name__)


# TODO gRPC only supports int32, but the session_id and sequence numbers should both be uint16

class Controller(anycast_pb2_grpc.AnycastServiceServicer):
    """Base class for the controller."""

    def __init__(self):
        self.next_session_id = os.getpid() % 65535
        self.programs = {}  # session_id -> Program
        self.worker_streams = {}  # worker_id -> context

    async def WorkerStream(self, request_iterator, context):
        worker_id = None
        try:
            async for message in request_iterator:
                if message.type == "REGISTER":
                    register_payload = RegisterPayload()
                    message.payload.Unpack(register_payload)
                    worker_id = register_payload.worker_id

                    self.worker_streams[worker_id] = context
                    logger.info(f"Worker {worker_id} registered")

                elif message.type == "ACK":
                    if not worker_id:
                        logger.error("Received ACK without preceding REGISTER")
                        continue
                    logger.debug(f"Ack from {worker_id}")
                    ack_payload = AckPayload()
                    message.payload.Unpack(ack_payload)
                    session_id = ack_payload.session_id
                    if session_id in self.programs:
                        self.programs[session_id].handle_ack(ack_payload)
                    else:
                        logger.error(f"Received ACK for unknown session ID {session_id}")

                elif message.type == "ERROR":
                    error_payload = ErrorPayload()
                    message.payload.Unpack(error_payload)
                    logger.error(f"Error from {worker_id} code: {error_payload.code} message: {error_payload.message}")

                elif message.type == "REPLY":
                    if not worker_id:
                        logger.error("Received REPLY without preceding REGISTER")
                        continue
                    logger.debug(f"Reply from {worker_id}")
                    reply_payload = ReplyPayload()
                    message.payload.Unpack(reply_payload)
                    session_id = reply_payload.session_id
                    if session_id in self.programs:
                        self.programs[session_id].handle_reply(reply_payload, worker_id)
                    else:
                        logger.error(f"Received REPLY for unknown session ID {session_id}")

                else:
                    logger.error(f"Unknown message type: {message.type}")
                    continue

        except grpc.aio.AioRpcError as e:
            logger.info(f"Worker {worker_id} disconnected: {e}")
        finally:
            if worker_id:
                self.worker_streams.pop(worker_id, None)

    async def start_agents(self, settings, session_id):
        for worker_id, context in self.worker_streams.items():
            packed = Any()
            packed.Pack(StartPayload(session_id=session_id, **settings))
            message = Message(type="START", payload=packed)
            await context.write(message)
            logger.info(f"Sent START to worker {worker_id} with settings: {self.settings}")

    async def stop_agents(self, session_id):
        for worker_id, context in self.worker_streams.values():
            packed = Any()
            packed.Pack(StopPayload(session_id=session_id))
            message = Message(type="STOP", payload=packed)
            await context.write(message)
            logger.info(f"Sent STOP to worker {worker_id}")

    async def send_packet(self, worker_id, packet, packet_id):
        if worker_id not in self.worker_streams:
            logger.error(f"Worker {worker_id} not found")
            return

        send_payload = SendPayload(raw_packet=packet, seq=packet_id)
        packed = Any()
        packed.Pack(send_payload)

        message = Message(type="SEND", payload=packed)
        context = self.worker_streams[worker_id]
        await context.write(message)

    async def UserRequest(self, request, context):
        try:
            command = request.command
            settings = ast.literal_eval(request.settings)
            session_id = self.next_session_id  # this should be thread-safe
            settings["filter"] = f"icmp and icmp[28:2] = {session_id:#04x}"
            self.next_session_id += 1
            # TODO extend this to support multiple programs, not just traceroute
            # TODO handle errors better
            self.programs[session_id] = Traceroute(self, session_id)
            await self.start_agents(session_id, settings)
            output = await self.programs[session_id].run(command)
            await self.stop_agents(session_id)
            del self.programs[session_id]
            return Response(code=200, output=output)
        except Exception as e:
            logger.error(f"Error processing user request: {e}")
            return Response(code=500, output=str(e))
        finally:
            self.programs.pop(session_id, None)


def serve(port):
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    anycast_pb2_grpc.add_AnycastServiceServicer_to_server(Controller(), server)
    server.add_insecure_port(f'0.0.0.0:{port}')
    server.start()
    logger.info(f"Server started on port {port}")
    server.wait_for_termination()


if __name__ == '__main__':
    serve(port=50051)
