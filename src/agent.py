import grpc.aio
import logging
from asyncio import get_event_loop, create_task, sleep, gather, run, wait, FIRST_COMPLETED
import socket
from google.protobuf.any_pb2 import Any
from anycast_pb2 import Message, JobPayload, ErrorPayload, ReplyPayload, RegisterPayload, DonePayload, UdpAck
from anycast_pb2_grpc import AnycastServiceStub
from datetime import datetime
from utils import build_udp_probe
from worker_manager import WorkerManager

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class Agent:

    def __init__(self, agent_id, controller_address):
        self.agent_id = agent_id
        self.controller_address = controller_address

        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
        self.udp_socket.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        self.udp_socket.setblocking(False)

        self.icmp_socket = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        self.icmp_socket.setblocking(False)

    async def listener_worker(self, sniffed_packet):
        packet, recv_time = sniffed_packet
        packed_payload = Any()
        packed_payload.Pack(ReplyPayload(raw_packet=packet, time=recv_time))
        return Message(type="REPLY", payload=packed_payload)

    async def sender_worker(self, job_payload):
        loop = get_event_loop()

        session_id = job_payload.session_id
        dst_ip = job_payload.dst_ip
        max_ttl = job_payload.max_ttl
        base_port = job_payload.base_port
        probe_num = job_payload.probe_num

        udp_acks = []
        seq = base_port
        for ttl in range(1, max_ttl + 1):
            for _ in range(probe_num):
                packet = build_udp_probe(
                    destination_ip=dst_ip,
                    ttl=ttl,
                    source_port=session_id,
                    dst_port=seq,
                )
                await loop.sock_sendto(self.udp_socket, packet, (job_payload.dst_ip, 0))
                sent_time = datetime.now().isoformat()
                udp_acks.append(UdpAck(seq=seq, sent_time=sent_time))
                seq += 1

        done_payload = Any()
        done_payload.Pack(DonePayload(session_id=session_id, udp_acks=udp_acks))
        return Message(type="DONE", payload=done_payload)

    async def handle_controller(self, context):
        async for message in context:
            try:
                if message.type == "JOB":
                    logger.debug("Received JOB command")
                    job_payload = JobPayload()
                    message.payload.Unpack(job_payload)
                    await self.sender_workers.add_input(job_payload)

                else:
                    logger.error(f"Unknown message type {message.type}")
                    continue

            except Exception as e:
                logger.error(f"Error sending packet: {e}")
                error_payload = Any()
                error_payload.Pack(ErrorPayload(code=500, message=str(e)))
                await self.sender_workers.add_output(error_payload)

    async def handle_sniffer(self):
        loop = get_event_loop()
        while True:
            try:
                packet = await loop.sock_recv(self.icmp_socket, 65535)
                recv_time = datetime.now().isoformat()
                await self.listener_workers.add_input((packet, recv_time))
            except BlockingIOError:
                await sleep(0.1)

    async def handle_output(self):
        register_payload = Any()
        register_payload.Pack(RegisterPayload(agent_id=self.agent_id))
        yield Message(type="REGISTER", payload=register_payload)
        logger.debug("Sent REGISTER to controller")
        sender_get = create_task(self.sender_workers.get_output())
        listener_get = create_task(self.listener_workers.get_output())
        while True:
            done, _ = await wait([sender_get, listener_get], return_when=FIRST_COMPLETED)
            for completed in done:
                try:
                    message = completed.result()
                    yield message
                    if completed == sender_get:
                        sender_get = create_task(self.sender_workers.get_output())
                    elif completed == listener_get:
                        listener_get = create_task(self.listener_workers.get_output())
                except Exception as e:
                    logger.error(f"Error processing output: {e}")
                    error_payload = Any()
                    error_payload.Pack(ErrorPayload(code=500, message=str(e)))
                    yield Message(type="ERROR", payload=error_payload)

    async def main(self):
        self.listener_workers = WorkerManager(worker_num=3, worker_func=self.listener_worker)
        self.sender_workers = WorkerManager(worker_num=3, worker_func=self.sender_worker)

        async with grpc.aio.insecure_channel(self.controller_address) as channel:
            stub = AnycastServiceStub(channel)
            try:
                context = stub.ControlStream(self.handle_output())
                await gather(self.handle_controller(context),
                             self.handle_sniffer())
            except grpc.aio.AioRpcError as e:
                logger.error(f"Error connecting to controller: {e}")


if __name__ == "__main__":
    agent = Agent(agent_id="1", controller_address="localhost:50051")
    run(agent.main())
