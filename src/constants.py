from dataclasses import dataclass


@dataclass
class TracerouteResult:
    seq: int
    t1: float  # Probe sent
    t2: float  # Probe received
    receiver: str
    gateway: str
    timeout: bool
    final_dst: bool


@dataclass
class TracerouteConf:
    probe_num: int = 3
    max_ttl: int = 30
    timeout: int = 5


BASE_PORT = 33434
ETHER_HEADER_OFFSET = 14
UDP_OFFSET = 42
