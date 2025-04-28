"""
controller/program.py

An abstract class for a program that can be run by the controller.

Author: David Song <davsong@cs.washington.edu>
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from voltadomar.anycast.anycast_pb2 import DonePayload, ReplyPayload


@dataclass
class ProgramConf:
    """
    Configuration for a program. Purposefully empty for now.
    """
    pass


class Program(ABC):
    """
    Abstract class for a program that can be run by the controller.
    """

    def __init__(self, controller, conf: ProgramConf) -> None:
        self.controller = controller
        self.conf = conf

    @abstractmethod
    async def run(self) -> None:
        """
        Run the program.
        """
        raise NotImplementedError

    @abstractmethod
    def handle_done(self, ack_payload: DonePayload) -> None:
        """
        Handle a DONE packet.
        """
        raise NotImplementedError

    @abstractmethod
    def handle_reply(self, reply_payload: ReplyPayload, worker_id: str) -> bool:
        """
        Handle a REPLY packet. Returns True if the reply was handled.
        """
        raise NotImplementedError
