"""
agent/agent.py

Anycast agent for Voltadomar. This agent is run on each anycast
node and processes jobs sent by the controller. It sends UDP probes
to the destination and listens for ICMP replies.

Author: David Song <davsong@cs.washington.edu>
"""

import asyncio
import logging
import socket
import time
from datetime import datetime
from typing import Tuple, Dict, AsyncIterator, Any as TypingAny

import grpc.aio
from google.protobuf.any_pb2 import Any

from anycast.anycast_pb2 import (Message, JobPayload, ErrorPayload,
                                 RegisterPayload, ReplyPayload, UdpAck,
                                 DonePayload)
from anycast.anycast_pb2_grpc import AnycastServiceStub

from voltadomar.agent.worker import WorkerManager

from utils import build_udp_probe
from constants import (MSG_TYPE_JOB, MSG_TYPE_REPLY, MSG_TYPE_DONE,
                       MSG_TYPE_ERROR, MSG_TYPE_REGISTER)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Constants
SOCKET_UDP = "udp"
SOCKET_ICMP = "icmp"


class Agent:
    """
    Represents an agent responsible for sending probes and listening for replies
    under the direction of a central controller.
    """

    def __init__(self, agent_id: str, controller_address: str) -> None:
        """
        Initializes the Agent.

        Args:
            agent_id: The unique identifier for this agent.
            controller_address: The address (host:port) of the controller service.
        """
        self.agent_id = agent_id
        self.controller_address = controller_address

        # Create asynchronous worker pools to handle incoming jobs and sniff packets.
        # Each worker is a task that processes jobs from a queue. By using a pool, it
        # allows for controls over the number of concurrent tasks.
        self.listener_workers = WorkerManager(worker_num=3, worker_func=self.listener_worker)
        self.sender_workers = WorkerManager(worker_num=3, worker_func=self.sender_worker)

        self.sockets: Dict[str, socket.socket] = {}
        self.sockets[SOCKET_UDP] = self._create_raw_socket(socket.IPPROTO_RAW, ip_hdrincl=True),
        self.sockets[SOCKET_ICMP] = self._create_raw_socket(socket.IPPROTO_ICMP)

        # self.sockets[SOCKET_UDP].bind(("10.10.10.10", 0))
        # self.sockets[SOCKET_ICMP].bind(("10.10.10.10", 0))

    def _create_raw_socket(self, protocol: int, ip_hdrincl: bool = False) -> socket.socket:
        """Creates and configures a raw socket."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, protocol)
            if ip_hdrincl:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            sock.setblocking(False)
            logger.info(f"Successfully created raw socket protocol {protocol}.")
            return sock
        except PermissionError as e:
            logger.error(f"Permission denied for raw socket protocol {protocol}:\n{e}")
            raise
        except OSError as e:
            logger.error(f"Failed to create raw socket protocol {protocol}:\n{e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error creating raw socket protocol {protocol}:\n{e}")
            raise

    async def listener_worker(self, sniffed_packet: Tuple[bytes, str]) -> Message:
        """
        Processes a sniffed packet and formats it as a REPLY message.

        Args:
            sniffed_packet: A tuple containing the raw packet bytes and the ISO timestamp of reception.

        Returns:
            A protobuf Message of type REPLY.
        """
        packet, recv_time = sniffed_packet
        packed_payload = Any()
        packed_payload.Pack(ReplyPayload(raw_packet=packet, time=recv_time))
        return Message(type=MSG_TYPE_REPLY, payload=packed_payload)

    async def sender_worker(self, payload: TypingAny) -> Message:
        """
        Processes a job payload to send UDP probes or handles an error payload.

        Args:
            payload: Either a JobPayload containing probing instructions or an ErrorPayload.

        Returns:
            A protobuf Message of type DONE upon successful job completion,
            or type ERROR if an error occurred or the input was an ErrorPayload.
        """
        loop = asyncio.get_running_loop()

        if isinstance(payload, ErrorPayload):
            logger.warning(f"Sender worker received an error payload: {payload.message}")
            packed_payload = Any()
            packed_payload.Pack(payload)
            return Message(type=MSG_TYPE_ERROR, payload=packed_payload)

        if not isinstance(payload, JobPayload):
            err_msg = f"Sender worker received unexpected payload type: {type(payload)}"
            logger.error(err_msg)
            packed_payload = Any()
            packed_payload.Pack(ErrorPayload(code=400, message=err_msg))
            return Message(type=MSG_TYPE_ERROR, payload=packed_payload)

        session_id = payload.session_id
        dst_ip = payload.dst_ip
        max_ttl = payload.max_ttl
        base_port = payload.base_port
        probe_num = payload.probe_num
        hmac = "hmac"

        logger.info(f"Starting job {session_id}: Probing {dst_ip} up to TTL {max_ttl}")
        udp_acks = []
        seq = base_port
        try:
            for ttl in range(1, max_ttl + 1):
                for _ in range(probe_num):
                    # TODO: add ICMP echo request packet
                    packet = build_udp_probe(
                        destination_ip=dst_ip,
                        ttl=ttl,
                        source_port=seq,
                        dst_port=hmac,
                    )
                    await loop.sock_sendto(self.sockets[SOCKET_UDP], packet, (dst_ip, 0))
                    exact_time = time.time_ns() / 1e9
                    sent_time = datetime.fromtimestamp(exact_time).isoformat()
                    udp_acks.append(UdpAck(seq=seq, sent_time=sent_time))
                    seq += 1

            logger.info(f"Finished sending probes for job {session_id}.")
            done_payload = Any()
            done_payload.Pack(DonePayload(session_id=session_id, udp_acks=udp_acks))
            return Message(type=MSG_TYPE_DONE, payload=done_payload)

        except socket.error as e:
            err_msg = f"Socket error during sending for job {session_id}: {e}"
            logger.error(err_msg)
            packed_payload = Any()
            packed_payload.Pack(ErrorPayload(code=500, message=err_msg))
            return Message(type=MSG_TYPE_ERROR, payload=packed_payload)
        except Exception as e:
            err_msg = f"Unexpected error during sending for job {session_id}: {e}"
            logger.exception(err_msg)
            packed_payload = Any()
            packed_payload.Pack(ErrorPayload(code=500, message=err_msg))
            return Message(type=MSG_TYPE_ERROR, payload=packed_payload)

    async def handle_controller(self, context: grpc.aio.StreamStreamCall) -> None:
        """
        Receives messages from the controller and dispatches jobs to sender workers.

        Args:
            context: The gRPC stream context for receiving messages.
        """
        logger.info("Listening for commands from controller...")
        try:
            async for message in context:
                try:
                    if message.type == MSG_TYPE_JOB:
                        logger.debug(f"Received {MSG_TYPE_JOB} command")
                        job_payload = JobPayload()
                        if message.payload.Unpack(job_payload):
                            await self.sender_workers.add_input(job_payload)
                        else:
                            logger.error("Failed to unpack JobPayload")
                    else:
                        logger.warning(f"Received unknown message type from controller: {message.type}")

                except KeyboardInterrupt:
                    logger.info("Keyboard interrupt received in handle_controller.")
                    break
                except Exception as e:
                    logger.exception(f"Error processing message from controller: {e}")
                    error_payload = ErrorPayload(code=500, message=f"Error processing controller message: {e}")
                    await self.sender_workers.add_input(error_payload)
        except grpc.aio.AioRpcError as e:
            logger.error(f"gRPC error receiving from controller: {e.details()} (code: {e.code()})")
        except Exception as e:
            logger.exception(f"Unexpected error in handle_controller: {e}")
        finally:
            logger.info("Controller handler finished.")

    async def handle_sniffer(self) -> None:
        """
        Continuously listens for ICMP packets on the raw socket and passes them to listener workers.
        """
        loop = asyncio.get_running_loop()
        icmp_socket = self.sockets[SOCKET_ICMP]
        buffer_size = 65535
        logger.info("Starting ICMP sniffer...")
        while True:
            try:
                packet, addr = await loop.sock_recvfrom(icmp_socket, buffer_size)
                exact_time = time.time_ns() / 1e9
                recv_time = datetime.fromtimestamp(exact_time).isoformat()
                logger.debug(f"Received ICMP packet from {addr[0]} size {len(packet)}")
                await self.listener_workers.add_input((packet, recv_time))
            except KeyboardInterrupt:
                logger.info("ICMP sniffer interrupted by user.")
                break
            except BlockingIOError:
                await asyncio.sleep(0.01)
            except socket.error as e:
                logger.error(f"Socket error receiving ICMP packet: {e}")
                await asyncio.sleep(1)
            except Exception as e:
                logger.exception(f"Unexpected error in handle_sniffer: {e}")
                await asyncio.sleep(1)

    async def handle_output(self) -> AsyncIterator[Message]:
        """
        Acts as an async generator, yielding messages (replies, errors, done signals)
        to be sent back to the controller. Handles initial registration.
        """
        register_payload = Any()
        register_payload.Pack(RegisterPayload(agent_id=self.agent_id))
        yield Message(type=MSG_TYPE_REGISTER, payload=register_payload)
        logger.info(f"Sent {MSG_TYPE_REGISTER} to controller for agent {self.agent_id}")

        sender_task = asyncio.create_task(self.sender_workers.get_output())
        listener_task = asyncio.create_task(self.listener_workers.get_output())
        pending = {sender_task, listener_task}

        # Continuously poll from the sender and listener tasks. Once one of them
        # returns a message, yield it to the controller, and re-create the task to
        # keep polling new messages.
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    message: Message = task.result()
                    yield message
                    logger.debug(f"Yielded message of type {message.type} to controller")

                    if task == sender_task:
                        sender_task = asyncio.create_task(self.sender_workers.get_output())
                        pending.add(sender_task)
                    elif task == listener_task:
                        listener_task = asyncio.create_task(self.listener_workers.get_output())
                        pending.add(listener_task)

                except Exception as e:
                    logger.exception(f"Error retrieving output from worker task: {e}")
                    error_payload = Any()
                    error_payload.Pack(ErrorPayload(code=500, message=f"Internal agent error processing worker output: {e}"))
                    yield Message(type=MSG_TYPE_ERROR, payload=error_payload)
        logger.info("Output handler finished.")

    async def run(self) -> None:
        """
        Starts the agent's main processes: worker managers, gRPC connection, and sniffer.
        """
        logger.info(f"Starting agent {self.agent_id}...")
        self.listener_workers.start()
        self.sender_workers.start()
        logger.info("Worker managers started.")

        try:
            async with grpc.aio.insecure_channel(self.controller_address) as channel:
                logger.info(f"Attempting to connect to controller at {self.controller_address}...")
                stub = AnycastServiceStub(channel)
                # The ControlStream handles both sending (via handle_output) and receiving (via handle_controller)
                # handle_output is passed as an async iterator to send messages upstream
                # handle_controller processes messages coming downstream within the stream context
                context = stub.ControlStream(self.handle_output())
                logger.info("gRPC stream established with controller.")
                await asyncio.gather(
                    self.handle_controller(context),
                    self.handle_sniffer()
                )
        except grpc.aio.AioRpcError as e:
            logger.error(f"gRPC connection error: {e.details()} (code: {e.code()}). Retrying in 5 seconds...")
        except Exception as e:
            logger.exception(f"Unexpected error in main run loop: {e}. Retrying in 5 seconds...")
