from dataclasses import dataclass


BASE_PORT = 33434


@dataclass
class TracerouteResult:
    '''
    Represents the result of a traceroute probe.

    Attributes:
        seq (int): The sequence number of the probe.
        t1 (float): The time when the probe was sent.
        t2 (float): The time when the probe was received.
        receiver (str): The anycast node receiver of the probe.
        gateway (str): The gateway where the probe timed out.
        timeout (bool): Indicates if the probe timed out.
        final_dst (bool): Indicates if the probe reached the final destination.
    '''
    seq: int
    t1: float  # Probe sent
    t2: float  # Probe received
    receiver: str
    gateway: str
    timeout: bool
    final_dst: bool


@dataclass
class TracerouteConf:
    '''
    Represents the configuration for a traceroute operation.

    Attributes:
        probe_num (int): The number of probes to send per TTL.
        max_ttl (int): The maximum TTL to reach.
        timeout (int): The timeout for the program.
    '''
    probe_num: int = 3
    max_ttl: int = 30
    timeout: int = 5
