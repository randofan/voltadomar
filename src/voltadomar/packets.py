"""
packets.py

Class representations of IP, UDP, and ICMP packets.

Author: David Song <davsong@cs.washington.edu>
"""

import struct
from typing import Optional

from exceptions import PacketParseError


class IP:
    """Represents an IP packet."""

    def __init__(
        self,
        raw: Optional[bytes] = None,
        dst: str = "0.0.0.0",
        src: str = "0.0.0.0",
        ttl: int = 64,
        proto: int = 17,
        ecn: bool = False,
    ):
        self.raw = raw
        self.version = 4
        self.ihl = 5
        self.tos = 0x03 if ecn else 0x00  # 0x03 (11) for ECN, 0x00 for no ECN
        self.length = 0
        self.id = 0
        self.flags_offset = 0
        self.ttl = ttl
        self.proto = proto
        self.checksum = 0
        self.src = src
        self.dst = dst
        self.payload = b""

        if raw:
            self._parse(raw)

    def _parse(self, raw: bytes) -> None:
        """Parses a raw IP packet."""
        if len(raw) < 20:
            raise PacketParseError(
                f"Packet too short: {len(raw)} bytes (expected at least 20)"
            )

        try:
            header = struct.unpack("!BBHHHBBH4s4s", raw[:20])
            self.version = header[0] >> 4
            self.ihl = header[0] & 0xF
            if self.ihl < 5:
                raise PacketParseError(f"Invalid IHL: {self.ihl} (must be at least 5)")

            header_length = self.ihl * 4
            if len(raw) < header_length:
                raise PacketParseError(
                    f"Packet too short for IHL: {len(raw)} bytes (expected {header_length})"
                )

            self.tos = header[1]
            self.length = header[2]
            self.id = header[3]
            self.flags_offset = header[4]
            self.ttl = header[5]
            self.proto = header[6]
            self.checksum = header[7]
            self.src = self._ip_to_str(header[8])
            self.dst = self._ip_to_str(header[9])
            self.payload = raw[header_length:]
        except struct.error as e:
            raise PacketParseError(f"Malformed IP packet: {e}") from e

    def _ip_to_str(self, ip_bytes: bytes) -> str:
        """Converts an IP address from bytes to string format."""
        return ".".join(map(str, ip_bytes))

    def __bytes__(self) -> bytes:
        """Serializes the IP packet into bytes."""
        self.length = 20 + len(self.payload)  # 20 bytes IP header + payload

        src_ip = struct.pack("!4B", *map(int, self.src.split(".")))
        dst_ip = struct.pack("!4B", *map(int, self.dst.split(".")))
        header = struct.pack(
            "!BBHHHBBH4s4s",
            (self.version << 4) + self.ihl,
            self.tos,
            self.length,
            self.id,
            self.flags_offset,
            self.ttl,
            self.proto,
            self.checksum,
            src_ip,
            dst_ip,
        )
        return header + self.payload

    def __repr__(self) -> str:
        return f"IP(src={self.src}, dst={self.dst}, ttl={self.ttl}, proto={self.proto})"

    @property
    def src(self) -> str:
        """Source IP address."""
        return self._src

    @src.setter
    def src(self, value: str) -> None:
        self._src = value

    @property
    def dst(self) -> str:
        """Destination IP address."""
        return self._dst

    @dst.setter
    def dst(self, value: str) -> None:
        self._dst = value

    @property
    def payload(self) -> bytes:
        """Packet payload."""
        return self._payload

    @payload.setter
    def payload(self, value: bytes) -> None:
        self._payload = value

    @property
    def ecn(self) -> int:
        """Returns the ECN bits."""
        return self.tos & 0x03

    @ecn.setter
    def ecn(self, value: bool) -> None:
        """Sets the ECN bits based on boolean flag."""
        self.tos = (self.tos & 0xFC) | (0x03 if value else 0x00)


class UDP:
    """Represents a UDP packet."""

    def __init__(
        self,
        raw: Optional[bytes] = None,
        sport: int = 0,
        dport: int = 0,
        payload: bytes = b"",
        checksum: int = 0,
        length: int = 8,
    ):
        self.raw = raw
        self.sport = sport
        self.dport = dport
        self.length = length
        self.checksum = checksum
        self.payload = payload

        if raw:
            self._parse(raw)

    def _parse(self, raw: bytes) -> None:
        """Parses a raw UDP packet."""
        try:
            header = struct.unpack("!HHHH", raw[:8])
            self.sport = header[0]
            self.dport = header[1]
            self.length = header[2]
            self.checksum = header[3]
            self.payload = raw[8:]
        except struct.error as e:
            raise PacketParseError("Malformed UDP packet") from e

    def __bytes__(self) -> bytes:
        """Serializes the UDP packet into bytes."""
        return (
            struct.pack("!HHHH", self.sport, self.dport, self.length, self.checksum) + self.payload
        )

    def __repr__(self) -> str:
        return f"UDP(sport={self.sport}, dport={self.dport}, length={self.length})"

    @property
    def sport(self) -> int:
        """Source port."""
        return self._sport

    @sport.setter
    def sport(self, value: int) -> None:
        self._sport = value

    @property
    def dport(self) -> int:
        """Destination port."""
        return self._dport

    @dport.setter
    def dport(self, value: int) -> None:
        self._dport = value

    @property
    def payload(self) -> bytes:
        """Packet payload."""
        return self._payload

    @payload.setter
    def payload(self, value: bytes) -> None:
        self._payload = value


class ICMP:
    """Represents an ICMP packet."""

    def __init__(
        self,
        raw: Optional[bytes] = None,
        type: int = 8,
        code: int = 0,
    ):
        self.raw = raw
        self.type = type
        self.code = code
        self.checksum = 0
        self.original_data = b"\x00" * 4
        self.inner_data = None  # Field for inner ICMP data

        if raw:
            self._parse(raw)

    def _parse(self, raw: bytes) -> None:
        """Parses a raw ICMP packet."""
        try:
            self.raw = raw
            header = struct.unpack("!BBH", raw[:4])
            self.type = header[0]
            self.code = header[1]
            self.checksum = header[2]

            if self.type == 11:  # Time Exceeded
                # Skip 4 bytes of ICMP header and 4 bytes of unused data
                self.original_data = raw[8:]

                if len(self.original_data) >= 28:
                    # Skip the inner IP header (20 bytes) to get to inner ICMP
                    self.inner_data = self.original_data[20:]
            else:
                self.original_data = raw[4:]
                self.inner_data = None

        except struct.error as e:
            raise PacketParseError("Malformed ICMP packet") from e

    def get_inner_icmp_data(self) -> Optional[bytes]:
        """Returns the data portion of the inner ICMP packet if this is a Time Exceeded message."""
        if self.type == 11 and self.inner_data and len(self.inner_data) >= 8:
            # Skip the inner ICMP header (4 bytes) to get to the actual data
            return self.inner_data[4:]
        return None

    def _calculate_checksum(self, data: bytes) -> int:
        """Calculates ICMP checksum."""
        if len(data) % 2 == 1:
            data += b"\0"

        words = struct.unpack("!%dH" % (len(data) // 2), data)
        checksum = sum(words)

        while checksum >> 16:
            checksum = (checksum & 0xFFFF) + (checksum >> 16)

        return ~checksum & 0xFFFF

    def __bytes__(self) -> bytes:
        """Serializes the ICMP packet into bytes."""
        packet = struct.pack("!BBH", self.type, self.code, 0) + self.original_data
        self.checksum = self._calculate_checksum(packet)
        return (
            struct.pack("!BBH", self.type, self.code, self.checksum) + self.original_data
        )

    def __repr__(self) -> str:
        return f"ICMP(type={self.type}, code={self.code})"

    @property
    def type(self) -> int:
        """ICMP packet type."""
        return self._type

    @type.setter
    def type(self, value: int) -> None:
        self._type = value

    @property
    def code(self) -> int:
        """ICMP code field."""
        return self._code

    @code.setter
    def code(self, value: int) -> None:
        self._code = value

    @property
    def original_data(self) -> bytes:
        """Original data of the ICMP packet."""
        return self._original_data

    @original_data.setter
    def original_data(self, value: bytes) -> None:
        self._original_data = value
