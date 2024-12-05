import asyncio
import grpc
import anycast_pb2
import anycast_pb2_grpc
import logging
from abc import abstractmethod

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='traceroute.log',
    filemode='w'
)
logger = logging.getLogger(__name__)


class Controller:
    """Abstract class for the controller."""

    def __init__(self, server_addresses):
        """Store internal state for the controller.

        Args:
            server_addresses (list[str]): Worker IP + port to connect to.

        Fields:
            server_addresses (list[str]): Workers - we use the IP + port as a
            uuid for each worker.
            stubs (dict): worker -> gRPC stubs.
            background_tasks (dict): worker -> coroutine task.
        """
        self.server_addresses = server_addresses
        self.stubs = {address: anycast_pb2_grpc.AnycastServiceStub(grpc.aio.insecure_channel(address)) for address in self.server_addresses}
        self.background_tasks = {address: None for address in self.server_addresses}

    @abstractmethod
    def handle_reply(self, response):
        """Callback function to handle replies from the workers.

        Args:
            response (ForwardPacket): gRPC response from the worker.

        Raises:
            NotImplementedError: Each implementation of the controller
            must implement this method.
        """
        raise NotImplementedError("Implement this method")

    def run_receiver_agents(self, /, hmac, filter):
        """Initiates each worker receiver agent.

        Creates a coroutine task for each worker to handle streaming
        responses. Whenever a response is received, it invokes the
        handle_reply callback function to process the response.

        All tasks are stored in the controller's state background_tasks.

        Args:
            hmac (str): HMAC to initialize each worker with.
            filter (str): The filter criteria to initialize each worker with.
        """
        async def handle_stream(address):
            try:
                logger.info(f"Connecting to {address} for ReceiverAgent")
                async for response in self.stubs[address].ReceiverAgent(anycast_pb2.InitRequest(hmac=hmac, filter=filter, host=address)):
                    logger.info(f"Received response from {address}")
                    self.handle_reply(response)
            except grpc.aio.AioRpcError as e:
                logger.error(f"Error from {address}: {e}")

        for address in self.server_addresses:
            task = asyncio.create_task(handle_stream(address))
            self.background_tasks[address] = task

    async def stop_receiver_agents(self):
        """Stop all the receiver agents.

        Cancel the tasks. This closes the gRPC stream and causes
        the receiver agents to exit.
        """
        for task in self.background_tasks.values():
            task.cancel()
        await asyncio.gather(*self.background_tasks.values(), return_exceptions=True)

    async def send_packet(self, address, raw_request):
        """Sends a packet to the specified address.

        Args:
            address (str): The worker to forward the packet from.
            raw_request (bytes): The L3 raw packet to be sent.

        Returns:
            None: if there is an error.
            CommandResponse: gRPC response object.
            - Status code indicating if the packet was sent
            - Timestamp (ISO format) of when the packet was sent
              from the worker.
        """
        if address not in self.stubs:
            logger.error(f"Address {address} is not in the list of servers.")
            return

        try:
            logger.info(f"Sending packet to {address}")
            response = await self.stubs[address].SendPacket(anycast_pb2.SendRequest(raw_request=raw_request))
            return response
        except grpc.aio.AioRpcError as e:
            logger.error(f"Error sending packet to {address}: {e}")
