// Package packets provides packet manipulation functionality using gopacket
package packets

import (
	"fmt"
	"net"
	"time"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
)

// PacketParseError represents an error during packet parsing
type PacketParseError struct {
	Message string
}

func (e *PacketParseError) Error() string {
	return e.Message
}

// BuildUDPProbe creates a UDP probe packet with the specified parameters.
// The packet includes an IPv4 header with the given TTL and a UDP header.
// The source IP is set to 0.0.0.0 and will be filled by the kernel.
// Returns the raw packet bytes ready for transmission.
func BuildUDPProbe(destinationIP string, ttl uint8, sourcePort, destPort uint16) ([]byte, error) {
	// Parse destination IP
	dstIP := net.ParseIP(destinationIP)
	if dstIP == nil {
		return nil, fmt.Errorf("invalid destination IP: %s", destinationIP)
	}

	// Create packet buffer
	buffer := gopacket.NewSerializeBuffer()
	options := gopacket.SerializeOptions{
		FixLengths:       true,
		ComputeChecksums: true,
	}

	// Create IP layer
	ipLayer := &layers.IPv4{
		Version:    4,
		IHL:        5,
		TOS:        0, // No ECN by default
		Length:     0, // Will be calculated
		Id:         0,
		Flags:      0,
		FragOffset: 0,
		TTL:        ttl,
		Protocol:   layers.IPProtocolUDP,
		Checksum:   0,                    // Will be calculated
		SrcIP:      net.IPv4(0, 0, 0, 0), // Will be set by kernel
		DstIP:      dstIP.To4(),
	}

	// Create UDP layer
	udpLayer := &layers.UDP{
		SrcPort:  layers.UDPPort(sourcePort),
		DstPort:  layers.UDPPort(destPort),
		Length:   0, // Will be calculated
		Checksum: 0, // Will be calculated
	}

	// Set network layer for checksum calculation
	udpLayer.SetNetworkLayerForChecksum(ipLayer)

	// Serialize the packet
	err := gopacket.SerializeLayers(buffer, options, ipLayer, udpLayer)
	if err != nil {
		return nil, fmt.Errorf("failed to serialize UDP probe: %w", err)
	}

	return buffer.Bytes(), nil
}

// BuildICMPProbe creates an ICMP echo request packet with the specified parameters.
// The packet includes an IPv4 header with the given TTL, an ICMP header, and a 40-byte payload.
// This is commonly used for traceroute measurements to generate ICMP time exceeded responses.
func BuildICMPProbe(destinationIP string, ttl uint8, seq, identifier uint16) ([]byte, error) {
	// Parse destination IP
	dstIP := net.ParseIP(destinationIP)
	if dstIP == nil {
		return nil, fmt.Errorf("invalid destination IP: %s", destinationIP)
	}

	// Create packet buffer
	buffer := gopacket.NewSerializeBuffer()
	options := gopacket.SerializeOptions{
		FixLengths:       true,
		ComputeChecksums: true,
	}

	// Create IP layer
	ipLayer := &layers.IPv4{
		Version:    4,
		IHL:        5,
		TOS:        0,
		Length:     0, // Will be calculated
		Id:         0,
		Flags:      0,
		FragOffset: 0,
		TTL:        ttl,
		Protocol:   layers.IPProtocolICMPv4,
		Checksum:   0,                    // Will be calculated
		SrcIP:      net.IPv4(0, 0, 0, 0), // Will be set by kernel
		DstIP:      dstIP.To4(),
	}

	// Create ICMP layer
	icmpLayer := &layers.ICMPv4{
		TypeCode: layers.CreateICMPv4TypeCode(layers.ICMPv4TypeEchoRequest, 0),
		Checksum: 0, // Will be calculated
		Id:       identifier,
		Seq:      seq,
	}

	// Create payload (40 bytes like Python version)
	payload := gopacket.Payload([]byte("ubiquitousubiquitousubiquitousubiquitou")) // 40 bytes

	// Serialize the packet
	err := gopacket.SerializeLayers(buffer, options, ipLayer, icmpLayer, payload)
	if err != nil {
		return nil, fmt.Errorf("failed to serialize ICMP probe: %w", err)
	}

	return buffer.Bytes(), nil
}

// ParsedPacket represents a parsed network packet
type ParsedPacket struct {
	Timestamp time.Time
	IPv4      *layers.IPv4
	ICMPv4    *layers.ICMPv4
	UDP       *layers.UDP
	Payload   []byte
}

// ParseICMPReply parses an ICMP reply packet and extracts relevant information
func ParseICMPReply(rawPacket []byte, timestamp time.Time) (*ParsedPacket, error) {
	packet := gopacket.NewPacket(rawPacket, layers.LayerTypeIPv4, gopacket.Default)

	parsed := &ParsedPacket{
		Timestamp: timestamp,
	}

	// Extract IPv4 layer
	if ipLayer := packet.Layer(layers.LayerTypeIPv4); ipLayer != nil {
		if ipv4, ok := ipLayer.(*layers.IPv4); ok {
			parsed.IPv4 = ipv4
		}
	}

	// Extract ICMPv4 layer
	if icmpLayer := packet.Layer(layers.LayerTypeICMPv4); icmpLayer != nil {
		if icmpv4, ok := icmpLayer.(*layers.ICMPv4); ok {
			parsed.ICMPv4 = icmpv4
		}
	}

	// Extract UDP layer (for inner packets in ICMP errors)
	if udpLayer := packet.Layer(layers.LayerTypeUDP); udpLayer != nil {
		if udp, ok := udpLayer.(*layers.UDP); ok {
			parsed.UDP = udp
		}
	}

	// Extract payload
	if appLayer := packet.ApplicationLayer(); appLayer != nil {
		parsed.Payload = appLayer.Payload()
	}

	if parsed.IPv4 == nil {
		return nil, &PacketParseError{Message: "no IPv4 layer found in packet"}
	}

	return parsed, nil
}

// IsICMPError checks if the parsed packet is an ICMP error message
func (p *ParsedPacket) IsICMPError() bool {
	if p.ICMPv4 == nil {
		return false
	}

	// Check for Destination Unreachable (3) or Time Exceeded (11)
	return p.ICMPv4.TypeCode.Type() == layers.ICMPv4TypeDestinationUnreachable ||
		p.ICMPv4.TypeCode.Type() == layers.ICMPv4TypeTimeExceeded
}

// GetSourceIP returns the source IP address as a string
func (p *ParsedPacket) GetSourceIP() string {
	if p.IPv4 == nil {
		return ""
	}
	return p.IPv4.SrcIP.String()
}

// GetDestinationIP returns the destination IP address as a string
func (p *ParsedPacket) GetDestinationIP() string {
	if p.IPv4 == nil {
		return ""
	}
	return p.IPv4.DstIP.String()
}

// GetICMPType returns the ICMP type, or -1 if not an ICMP packet
func (p *ParsedPacket) GetICMPType() int {
	if p.ICMPv4 == nil {
		return -1
	}
	return int(p.ICMPv4.TypeCode.Type())
}

// GetICMPCode returns the ICMP code, or -1 if not an ICMP packet
func (p *ParsedPacket) GetICMPCode() int {
	if p.ICMPv4 == nil {
		return -1
	}
	return int(p.ICMPv4.TypeCode.Code())
}

// ResolveHostname resolves the hostname of a given IP address
func ResolveHostname(ip string) string {
	names, err := net.LookupAddr(ip)
	if err != nil || len(names) == 0 {
		return ip
	}
	return names[0]
}

// ResolveIP resolves the IP address of a given hostname
func ResolveIP(hostname string) (string, error) {
	ips, err := net.LookupIP(hostname)
	if err != nil {
		return "", err
	}

	for _, ip := range ips {
		if ipv4 := ip.To4(); ipv4 != nil {
			return ipv4.String(), nil
		}
	}

	return "", fmt.Errorf("no IPv4 address found for hostname: %s", hostname)
}
