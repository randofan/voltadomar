import os
import grpc.aio
from asyncio import run
import logging
import anycast_pb2_grpc
from anycast_pb2 import ReplyPayload, DonePayload, JobPayload, Message, ErrorPayload, RegisterPayload, Response
from google.protobuf.any_pb2 import Any
from traceroute import Traceroute

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='controller.log',
    filemode='w'
)
logger = logging.getLogger(__name__)


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

                elif message.type == "DONE":
                    if not worker_id:
                        logger.error("Received DONE without preceding REGISTER")
                        continue
                    logger.debug(f"DONE from {worker_id}")
                    done_payload = DonePayload()
                    message.payload.Unpack(done_payload)
                    session_id = done_payload.session_id
                    if session_id in self.programs:
                        self.programs[session_id].handle_done(done_payload)
                    else:
                        logger.error(f"Received DONE for unknown session ID {session_id}")

                elif message.type == "REPLY":
                    if not worker_id:
                        logger.error("Received REPLY without preceding REGISTER")
                        continue
                    logger.debug(f"REPLY from {worker_id}")
                    reply_payload = ReplyPayload()
                    message.payload.Unpack(reply_payload)
                    # TODO use worker groups here
                    for program in self.programs.values():
                        if program.filter_packets(reply_payload):
                            program.handle_reply(reply_payload)
                            break
                    else:
                        logger.error("Received REPLY for unknown packet")

                elif message.type == "ERROR":
                    # TODO improve error information
                    error_payload = ErrorPayload()
                    message.payload.Unpack(error_payload)
                    logger.error(f"Error from {worker_id} code: {error_payload.code} message: {error_payload.message}")

                else:
                    logger.error(f"Unknown message type: {message.type}")
                    continue

        except grpc.aio.AioRpcError as e:
            logger.info(f"Worker {worker_id} disconnected: {e}")
        except Exception as e:
            logger.error(f"Error processing worker stream: {e}")
        finally:
            self.worker_streams.pop(worker_id, None)

    async def send_job(self, session_id, worker_id, dst_ip, udp_requests):
        """Send a packet through a worker."""
        if worker_id not in self.worker_streams:
            logger.error(f"Worker {worker_id} not found")
            return

        job_payload = JobPayload(session_id=session_id, dst_ip=dst_ip,
                                 udp_requests=udp_requests)
        packed = Any()
        packed.Pack(job_payload)

        message = Message(type="JOB", payload=packed)
        context = self.worker_streams[worker_id]
        await context.write(message)
        logger.debug(f"Sent job session {session_id} to worker {worker_id}")

    async def UserRequest(self, request, context):
        """Handle a user request to run a program."""
        # TODO is using a job queue better because we'll still need to maintain
        # a coroutine per user request to track the grpc session?
        try:
            command = request.command
            session_id = self.next_session_id
            self.next_session_id = (self.next_session_id + 1) % 65535
            self.programs[session_id] = Traceroute(self, session_id)
            logger.info(f"Starting program {session_id} with command: {command}")
            output = await self.programs[session_id].run(command)
            return Response(code=200, output=output)
        except Exception as e:
            logger.error(f"Error processing user request: {e}")
            return Response(code=500, output=str(e))
        finally:
            self.programs.pop(session_id, None)


async def serve(port):
    server = grpc.aio.server()
    anycast_pb2_grpc.add_AnycastServiceServicer_to_server(Controller(), server)
    server.add_insecure_port(f'0.0.0.0:{port}')
    await server.start()
    logger.info(f"Server started on port {port}")
    await server.wait_for_termination()


if __name__ == '__main__':
    run(serve(port=50051))
