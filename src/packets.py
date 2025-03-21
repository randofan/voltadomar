import struct

from exceptions import PacketParseError


class IP:
    """
    Represents an IP packet.
    """

    def __init__(self, raw=None, dst="0.0.0.0", src="0.0.0.0", ttl=64, proto=17):
        self._raw = raw
        self._version = 4
        self._ihl = 5
        self._tos = 0
        self._length = 0
        self._id = 0
        self._flags_offset = 0
        self._ttl = ttl
        self._proto = proto
        self._checksum = 0
        self._src = src
        self._dst = dst
        self._payload = b""

        if raw:
            self._parse(raw)

    def _parse(self, raw):
        """
        Parses a raw IP packet.
        """
        if len(raw) < 20:
            raise PacketParseError(
                f"Packet too short: {len(raw)} bytes (expected at least 20)"
            )

        try:
            header = struct.unpack("!BBHHHBBH4s4s", raw[:20])
            self._version = header[0] >> 4
            self._ihl = header[0] & 0xF
            if self._ihl < 5:
                raise PacketParseError(f"Invalid IHL: {self._ihl} (must be at least 5)")

            header_length = self._ihl * 4
            if len(raw) < header_length:
                raise PacketParseError(
                    f"Packet too short for IHL: {len(raw)} bytes (expected {header_length})"
                )

            self._tos = header[1]
            self._length = header[2]
            self._id = header[3]
            self._flags_offset = header[4]
            self._ttl = header[5]
            self._proto = header[6]
            self._checksum = header[7]
            self._src = self._ip_to_str(header[8])
            self._dst = self._ip_to_str(header[9])
            self._payload = raw[header_length:]
        except struct.error as e:
            raise PacketParseError(f"Malformed IP packet: {e}") from e

    def _ip_to_str(self, ip_bytes):
        """
        Converts an IP address from bytes to string format.
        """
        return ".".join(map(str, ip_bytes))

    def __bytes__(self):
        """
        Serializes the IP packet into bytes.
        """
        self._length = 20 + len(self._payload)  # 20 bytes IP header + payload

        src_ip = struct.pack("!4B", *map(int, self._src.split(".")))
        dst_ip = struct.pack("!4B", *map(int, self._dst.split(".")))
        header = struct.pack(
            "!BBHHHBBH4s4s",
            (self._version << 4) + self._ihl,
            self._tos,
            self._length,
            self._id,
            self._flags_offset,
            self._ttl,
            self._proto,
            self._checksum,
            src_ip,
            dst_ip,
        )
        return header + self._payload

    def __repr__(self):
        return f"IP(src={self._src}, dst={self._dst}, ttl={self._ttl}, proto={self._proto})"

    @property
    def src(self):
        """
        Returns the source IP address.
        """
        return self._src

    @property
    def dst(self):
        """
        Returns the destination IP address.
        """
        return self._dst

    @property
    def payload(self):
        """
        Returns the payload of the IP packet.
        """
        return self._payload


class UDP:
    """
    Represents a UDP packet.
    """

    def __init__(self, raw=None, sport=0, dport=0, payload=b"", checksum=0, length=8):
        self._raw = raw
        self._sport = sport
        self._dport = dport
        self._length = length
        self._checksum = checksum
        self._payload = payload

        if raw:
            self._parse(raw)

    def _parse(self, raw):
        """
        Parses a raw UDP packet.
        """
        try:
            header = struct.unpack("!HHHH", raw[:8])
            self._sport = header[0]
            self._dport = header[1]
            self._length = header[2]
            self._checksum = header[3]
            self._payload = raw[8:]
        except struct.error as e:
            raise PacketParseError("Malformed UDP packet") from e

    def __bytes__(self):
        """
        Serializes the UDP packet into bytes.
        """
        return (
            struct.pack("!HHHH", self._sport, self._dport, self._length, self._checksum) + self._payload
        )

    def __repr__(self):
        return f"UDP(sport={self._sport}, dport={self._dport}, length={self._length})"

    @property
    def sport(self):
        """
        Returns the source port.
        """
        return self._sport

    @property
    def dport(self):
        """
        Returns the destination port.
        """
        return self._dport

    @property
    def payload(self):
        """
        Returns the payload of the UDP packet.
        """
        return self._payload


class ICMP:
    """
    Represents an ICMP packet.
    """

    def __init__(self, raw=None, type=8, code=0):
        self._raw = raw
        self._type = type
        self._code = code
        self._checksum = 0
        self._original_data = b"\x00" * 4
        self._inner_data = None  # Add field for inner ICMP data

        if raw:
            self._parse(raw)

    def _parse(self, raw):
        """
        Parses a raw ICMP packet.
        """
        try:
            self._raw = raw
            header = struct.unpack("!BBH", raw[:4])
            self._type = header[0]
            self._code = header[1]
            self._checksum = header[2]

            if self._type == 11:  # Time Exceeded
                # Skip 4 bytes of ICMP header and 4 bytes of unused data
                self._original_data = raw[8:]

                # If we have enough data, extract the inner ICMP packet
                if len(self._original_data) >= 28:  # 20 (IP) + 8 (min ICMP)
                    # Skip the inner IP header (20 bytes) to get to inner ICMP
                    self._inner_data = self._original_data[20:]
            else:
                self._original_data = raw[4:]
                self._inner_data = None

        except struct.error as e:
            raise PacketParseError("Malformed ICMP packet") from e

    def get_inner_icmp_data(self):
        """
        Returns the data portion of the inner ICMP packet if this is a Time Exceeded message.
        """
        if self._type == 11 and self._inner_data and len(self._inner_data) >= 8:
            # Skip the inner ICMP header (4 bytes) to get to the actual data
            return self._inner_data[4:]
        return None

    def _calculate_checksum(self, data):
        """
        Calculates ICMP checksum.
        """
        if len(data) % 2 == 1:
            data += b"\0"

        words = struct.unpack("!%dH" % (len(data) // 2), data)
        checksum = sum(words)

        while checksum >> 16:
            checksum = (checksum & 0xFFFF) + (checksum >> 16)

        return ~checksum & 0xFFFF

    def __bytes__(self):
        """
        Serializes the ICMP packet into bytes.
        """
        packet = struct.pack("!BBH", self._type, self._code, 0) + self._original_data
        self._checksum = self._calculate_checksum(packet)
        return (
            struct.pack("!BBH", self._type, self._code, self._checksum) + self._original_data
        )

    def __repr__(self):
        return f"ICMP(type={self._type}, code={self._code})"

    @property
    def type(self):
        """
        Returns the ICMP type field.
        """
        return self._type

    @property
    def code(self):
        """
        Returns the ICMP code field.
        """
        return self._code

    @property
    def original_data(self):
        """
        Returns the original data of the ICMP packet.
        """
        return self._original_data
