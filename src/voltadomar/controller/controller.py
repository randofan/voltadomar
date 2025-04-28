"""
controller/controller.py

Controller manages state for agent connections, session information,
and program execution. Handles coordination between users and agents.

Author: David Song <davsong@cs.washington.edu>
"""

import asyncio
import logging
from typing import Dict, Any as AnyType, Optional, Set

import grpc.aio
from google.protobuf.any_pb2 import Any

import voltadomar.anycast.anycast_pb2_grpc as anycast_pb2_grpc
from voltadomar.anycast.anycast_pb2 import (
    ReplyPayload,
    DonePayload,
    Message,
    ErrorPayload,
    RegisterPayload,
    Response,
    JobPayload,
)

from voltadomar.controller.program import Program
from voltadomar.controller.traceroute import (
    TracerouteConf,
    Traceroute,
    parse_traceroute_args,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class Controller(anycast_pb2_grpc.AnycastServiceServicer):
    """
    Controller manages agent connections, session allocation, and
    program execution. Handles communication between users and agents.
    """

    def __init__(self, port: int, start_id: int, end_id: int, block_size: int):
        """
        Initialize a new Controller instance.

        This class manages traceroute sessions and agent streams, keeping track of session IDs
        and maintaining mappings between programs and their corresponding agents.

        Args:
            port (int): The port to run the server on
            start_id (int): The starting session ID number to use for new traceroute sessions
            end_id (int): The maximum session ID number that can be allocated
            block_size (int): The size of ID blocks to allocate for each agent
        """
        self.port = port
        self.start_id = start_id
        self.end_id = end_id
        self.block_size = block_size

        self.next_session_id = self.start_id
        self.programs: Dict[int, Program] = {}
        self.agent_streams: Dict[str, grpc.aio.ServicerContext] = {}
        self.in_use_blocks: Set[int] = set()

    def allocate_session_id(self) -> int:
        """
        Allocate a new session ID block using a sliding window approach.
        Returns the start ID of the allocated block.

        Raises:
            RuntimeError: If no free blocks are available.
        """
        current_id = self.next_session_id

        # Sweep through the entire ID range to find the next free block.
        for _ in range((self.end_id - self.start_id) // self.block_size):
            if current_id not in self.in_use_blocks:
                self.in_use_blocks.add(current_id)
                self.next_session_id = (current_id + self.block_size) % self.end_id
                if self.next_session_id < self.start_id:
                    # Handle wrap-around case.
                    self.next_session_id = self.start_id
                return current_id

            current_id = (current_id + self.block_size) % self.end_id
            if current_id < self.start_id:
                # Handle wrap-around case.
                current_id = self.start_id

        logger.error("No free session ID blocks available")
        # Error is propagated to the caller via try/catch.
        raise RuntimeError("No free session ID blocks available")

    def release_session_id(self, session_id: int) -> None:
        """
        Release a previously allocated session ID block.

        Args:
            session_id: The start ID of the block to release
        """
        if session_id in self.in_use_blocks:
            self.in_use_blocks.remove(session_id)
            logger.debug(f"Released session ID block starting at {session_id}")
        else:
            logger.warning(
                f"Attempted to release unallocated session ID block: {session_id}"
            )

    async def ControlStream(
        self, request_iterator: AnyType, context: grpc.aio.ServicerContext
    ) -> None:
        """
        Handle a stream of control messages from agents.

        Args:
            request_iterator: An async iterator of incoming messages from the agent.
            context: The gRPC context for the agent connection.
        """
        agent_id: Optional[str] = None
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
                        if agent_id is None:
                            logger.error("Received DONE without preceding REGISTER")
                            continue
                        done_payload = DonePayload()
                        message.payload.Unpack(done_payload)
                        session_id = done_payload.session_id
                        logger.debug(f"DONE from {agent_id} for session {session_id}")
                        if session_id in self.programs:
                            self.programs[session_id].handle_done(done_payload)
                        else:
                            logger.error(
                                f"Received DONE for unknown session ID {session_id}"
                            )

                    case "REPLY":
                        if agent_id is None:
                            logger.error("Received REPLY without preceding REGISTER")
                            continue
                        logger.debug(f"REPLY from {agent_id}")
                        reply_payload = ReplyPayload()
                        message.payload.Unpack(reply_payload)
                        # Unlike DONE, We don't know the session ID for REPLY messages, so we
                        # need to check all programs to see if any of them can handle the reply.
                        for program in self.programs.values():
                            if program.handle_reply(reply_payload, agent_id):
                                break
                        else:
                            logger.error("Received REPLY for unknown session ID")

                    case "ERROR":
                        error_payload = ErrorPayload()
                        message.payload.Unpack(error_payload)
                        logger.error(
                            f"Error from {agent_id} code: {error_payload.code} message: {error_payload.message}"
                        )

                    case _:
                        logger.error(f"Unknown message type: {message.type}")
                        continue

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Shutting down.")
            raise
        except grpc.aio.AioRpcError as e:
            logger.info(f"Agent {agent_id or 'unknown'} disconnected: {e}")
        except Exception as e:
            logger.exception(
                f"Error processing agent stream for {agent_id or 'unknown'}: {e}"
            )
        finally:
            self.agent_streams.pop(agent_id, None)

    async def UserRequest(
        self, request: AnyType, context: grpc.aio.ServicerContext
    ) -> Response:
        """
        Handle a user request to run a program (e.g., traceroute).

        Args:
            request: The user request containing the command to run.
            context: The gRPC context for the user connection.

        Returns:
            A Response object containing the result or an error message.
        """
        session_start_id: Optional[int] = None
        try:
            command = request.command
            args = parse_traceroute_args(command)
            source, destination, max_ttls, waittime, tos, nqueries = args
            if max_ttls * nqueries > self.block_size:
                return Response(
                    code=400,
                    output=f"Max hops * probe num ({max_ttls} * {nqueries}) exceeds block size ({self.block_size})",
                )
            session_start_id = self.allocate_session_id()

            conf = TracerouteConf(
                source_host=source,
                destination_host=destination,
                start_id=session_start_id,
                max_ttl=max_ttls,
                timeout=waittime,
                probe_num=nqueries,
                tos=tos,
            )

            self.programs[session_start_id] = Traceroute(self, conf)
            logger.info(f"Starting program {session_start_id} with command: {command}")
            output = await self.programs[session_start_id].run()
            return Response(code=200, output=output)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received during user request.")
            raise
        except ValueError as e:
            logger.warning(f"Invalid user request: {e}")
            return Response(code=400, output=str(e))
        except grpc.aio.AioRpcError as e:
            logger.info(f"User disconnected: {e}")
        except Exception as e:
            logger.exception(f"Error processing user request: {e}")
            return Response(code=500, output=f"Internal server error: {e}")
        finally:
            self.programs.pop(session_start_id, None)
            self.release_session_id(session_start_id)

    async def send_job(self, agent_id: str, job_payload: JobPayload) -> None:
        """
        Send a job payload to a specific agent.

        Args:
            agent_id: The ID of the target agent.
            job_payload: The job payload protobuf message.
        """
        logger.debug(f"Sending job to agent {agent_id}")
        context = self.agent_streams.get(agent_id)
        if not context:
            logger.error(
                f"Attempted to send job to unknown or disconnected agent {agent_id}"
            )
            return

        packed_payload = Any()
        packed_payload.Pack(job_payload)
        message = Message(type="JOB", payload=packed_payload)

        try:
            await context.write(message)
            logger.info(f"Successfully sent job to agent {agent_id}")
        except grpc.aio.AioRpcError as e:
            logger.error(f"Failed to send job to agent {agent_id}: {e}")

    async def run(self) -> None:
        """
        Start the gRPC server and wait for termination.
        """
        server = grpc.aio.server()
        anycast_pb2_grpc.add_AnycastServiceServicer_to_server(self, server)
        server.add_insecure_port(f"0.0.0.0:{self.port}")
        await server.start()
        logger.info(f"Server started on port {self.port}")

        try:
            await server.wait_for_termination()
        except asyncio.CancelledError:
            logger.info("Controller task was cancelled.")
            raise
        finally:
            await server.stop(0)
            logger.info("Controller shutdown complete.")
