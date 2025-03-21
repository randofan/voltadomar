import logging
import argparse
from asyncio import run

import grpc.aio
from google.protobuf.any_pb2 import Any

import anycast.anycast_pb2_grpc as anycast_pb2_grpc
from anycast.anycast_pb2 import ReplyPayload, DonePayload, Message, ErrorPayload, RegisterPayload, Response

from controller.traceroute import TracerouteConf, Traceroute, parse_traceroute_args

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class Controller(anycast_pb2_grpc.AnycastServiceServicer):
    '''
    Controller for the Anycast service.
    '''

    def __init__(self, start_id, end_id):
        self.start_id = start_id
        self.end_id = end_id

        self.next_session_id = self.start_id
        self.programs = {}  # session_id (start_id) -> program instance (Traceroute)
        self.agent_streams = {}  # agent_id -> grpc context

    async def ControlStream(self, request_iterator, context):
        '''
        Handle a stream of control messages from agents. The controller
        creates a new coroutine for each agent that connects.
        '''
        agent_id = None
        try:
            async for message in request_iterator:
                match message.type:
                    case "REGISTER":
                        register_payload = RegisterPayload()
                        message.payload.Unpack(register_payload)
                        agent_id = register_payload.agent_id
                        logger.debug(f"REGISTER from {agent_id}")

                        self.agent_streams[agent_id] = context
                        logger.info(f"Agent {agent_id} registered")

                    case "DONE":
                        if not agent_id:
                            logger.error("Received DONE without preceding REGISTER")
                            continue
                        done_payload = DonePayload()
                        message.payload.Unpack(done_payload)
                        session_id = done_payload.session_id
                        logger.debug(f"DONE from {agent_id} for session {session_id}")
                        if session_id in self.programs:
                            self.programs[session_id].handle_done(done_payload)
                        else:
                            logger.error(f"Received DONE for unknown session ID {session_id}")

                    case "REPLY":
                        if not agent_id:
                            logger.error("Received REPLY without preceding REGISTER")
                            continue
                        logger.debug(f"REPLY from {agent_id}")
                        reply_payload = ReplyPayload()
                        message.payload.Unpack(reply_payload)
                        for program in self.programs.values():
                            if program.handle_reply(reply_payload, agent_id):
                                break
                        else:
                            logger.error("Received REPLY for unknown session ID")

                    case "ERROR":
                        error_payload = ErrorPayload()
                        message.payload.Unpack(error_payload)
                        logger.error(f"Error from {agent_id} code: {error_payload.code} message: {error_payload.message}")

                    case _:
                        logger.error(f"Unknown message type: {message.type}")
                        continue

        except grpc.aio.AioRpcError as e:
            logger.info(f"Agent {agent_id} disconnected: {e}")
        except KeyboardInterrupt as e:
            logger.info("Keyboard interrupt")
            raise e
        except Exception as e:
            logger.error(f"Error processing agent stream: {e}")
        finally:
            self.agent_streams.pop(agent_id, None)

    async def UserRequest(self, request, context):
        '''
        Handle a user request to run a program. The controller creates
        a new coroutine for each program that is run.
        '''
        try:
            session_start_id = self.next_session_id
            command = request.command
            source, destination, max_hop, timeout, probe_num = parse_traceroute_args(command)
            conf = TracerouteConf(
                sender_host=source,
                destination_host=destination,
                start_id=session_start_id,
                max_ttl=max_hop,
                timeout=timeout,
                probe_num=probe_num
            )
            session_end_id = (self.next_session_id + max_hop * probe_num) % self.end_id
            # TODO: avoid collisions between programs
            self.next_session_id = session_end_id + 1
            self.programs[session_start_id] = Traceroute(self, conf)
            logger.info(f"Starting program {session_start_id} with command: {command}")
            output = await self.programs[session_start_id].run(command)
            return Response(code=200, output=output)
        except grpc.aio.AioRpcError as e:
            logger.info(f"User disconnected: {e}")
        except KeyboardInterrupt as e:
            logger.info("Keyboard interrupt")
            raise e
        except Exception as e:
            logger.error(f"Error processing user request: {e}")
            return Response(code=500, output=str(e))
        finally:
            self.programs.pop(session_start_id, None)

    async def send_job(self, agent_id, job_payload):
        '''
        Send a packet through a agent.
        '''
        if agent_id not in self.agent_streams:
            logger.error(f"Agent {agent_id} not found")
            return

        packed = Any()
        packed.Pack(job_payload)

        message = Message(type="JOB", payload=packed)
        context = self.agent_streams[agent_id]
        try:
            await context.write(message)
            logger.info(f"Successfully sent job to agent {agent_id}")
        except grpc.aio.AioRpcError as e:
            logger.error(f"Error sending job to agent {agent_id}: {e}")


async def serve(port, start_id, end_id):
    server = grpc.aio.server()
    anycast_pb2_grpc.add_AnycastServiceServicer_to_server(Controller(start_id=start_id, end_id=end_id), server)
    server.add_insecure_port(f'0.0.0.0:{port}')
    await server.start()
    logger.info(f"Server started on port {port}")
    await server.wait_for_termination()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the Anycast gRPC server.')
    parser.add_argument('--port', type=int, default=50051, help='Port to run the server on')
    parser.add_argument('--range', type=str, required=True, help='Program range ex. 1000-2000')
    args = parser.parse_args()
    start, end = map(int, args.range.split('-'))
    if start >= end:
        raise ValueError("Start ID must be less than end ID")
    run(serve(port=args.port, start_id=start, end_id=end))
