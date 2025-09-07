package packets

import (
	"net"
	"testing"
	"time"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"
)

func TestBuildUDPProbe(t *testing.T) {
	tests := []struct {
		name        string
		destIP      string
		ttl         uint8
		sourcePort  uint16
		destPort    uint16
		expectError bool
	}{
		{
			name:        "valid IPv4 address",
			destIP:      "8.8.8.8",
			ttl:         64,
			sourcePort:  12345,
			destPort:    53,
			expectError: false,
		},
		{
			name:        "invalid IP address",
			destIP:      "invalid-ip",
			ttl:         64,
			sourcePort:  12345,
			destPort:    53,
			expectError: true,
		},
		{
			name:        "zero TTL",
			destIP:      "1.1.1.1",
			ttl:         0,
			sourcePort:  12345,
			destPort:    53,
			expectError: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			packet, err := BuildUDPProbe(tt.destIP, tt.ttl, tt.sourcePort, tt.destPort)
			
			if tt.expectError {
				if err == nil {
					t.Errorf("expected error but got none")
				}
				return
			}
			
			if err != nil {
				t.Errorf("unexpected error: %v", err)
				return
			}
			
			if len(packet) == 0 {
				t.Errorf("expected non-empty packet")
			}
			
			// Parse the packet to verify structure
			parsedPacket := gopacket.NewPacket(packet, layers.LayerTypeIPv4, gopacket.Default)
			
			// Check IP layer
			ipLayer := parsedPacket.Layer(layers.LayerTypeIPv4)
			if ipLayer == nil {
				t.Errorf("expected IPv4 layer")
				return
			}
			
			ip, ok := ipLayer.(*layers.IPv4)
			if !ok {
				t.Errorf("failed to cast to IPv4 layer")
				return
			}
			
			if ip.TTL != tt.ttl {
				t.Errorf("expected TTL %d, got %d", tt.ttl, ip.TTL)
			}
			
			if ip.Protocol != layers.IPProtocolUDP {
				t.Errorf("expected UDP protocol, got %v", ip.Protocol)
			}
			
			expectedIP := net.ParseIP(tt.destIP).To4()
			if !ip.DstIP.Equal(expectedIP) {
				t.Errorf("expected destination IP %v, got %v", expectedIP, ip.DstIP)
			}
			
			// Check UDP layer
			udpLayer := parsedPacket.Layer(layers.LayerTypeUDP)
			if udpLayer == nil {
				t.Errorf("expected UDP layer")
				return
			}
			
			udp, ok := udpLayer.(*layers.UDP)
			if !ok {
				t.Errorf("failed to cast to UDP layer")
				return
			}
			
			if uint16(udp.SrcPort) != tt.sourcePort {
				t.Errorf("expected source port %d, got %d", tt.sourcePort, udp.SrcPort)
			}
			
			if uint16(udp.DstPort) != tt.destPort {
				t.Errorf("expected destination port %d, got %d", tt.destPort, udp.DstPort)
			}
		})
	}
}

func TestBuildICMPProbe(t *testing.T) {
	tests := []struct {
		name        string
		destIP      string
		ttl         uint8
		seq         uint16
		identifier  uint16
		expectError bool
	}{
		{
			name:        "valid ICMP probe",
			destIP:      "8.8.8.8",
			ttl:         64,
			seq:         1,
			identifier:  12345,
			expectError: false,
		},
		{
			name:        "invalid IP address",
			destIP:      "invalid-ip",
			ttl:         64,
			seq:         1,
			identifier:  12345,
			expectError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			packet, err := BuildICMPProbe(tt.destIP, tt.ttl, tt.seq, tt.identifier)
			
			if tt.expectError {
				if err == nil {
					t.Errorf("expected error but got none")
				}
				return
			}
			
			if err != nil {
				t.Errorf("unexpected error: %v", err)
				return
			}
			
			if len(packet) == 0 {
				t.Errorf("expected non-empty packet")
			}
			
			// Parse the packet to verify structure
			parsedPacket := gopacket.NewPacket(packet, layers.LayerTypeIPv4, gopacket.Default)
			
			// Check IP layer
			ipLayer := parsedPacket.Layer(layers.LayerTypeIPv4)
			if ipLayer == nil {
				t.Errorf("expected IPv4 layer")
				return
			}
			
			ip, ok := ipLayer.(*layers.IPv4)
			if !ok {
				t.Errorf("failed to cast to IPv4 layer")
				return
			}
			
			if ip.TTL != tt.ttl {
				t.Errorf("expected TTL %d, got %d", tt.ttl, ip.TTL)
			}
			
			if ip.Protocol != layers.IPProtocolICMPv4 {
				t.Errorf("expected ICMP protocol, got %v", ip.Protocol)
			}
			
			// Check ICMP layer
			icmpLayer := parsedPacket.Layer(layers.LayerTypeICMPv4)
			if icmpLayer == nil {
				t.Errorf("expected ICMPv4 layer")
				return
			}
			
			icmp, ok := icmpLayer.(*layers.ICMPv4)
			if !ok {
				t.Errorf("failed to cast to ICMPv4 layer")
				return
			}
			
			if icmp.TypeCode.Type() != layers.ICMPv4TypeEchoRequest {
				t.Errorf("expected ICMP echo request, got %v", icmp.TypeCode.Type())
			}
			
			if icmp.Id != tt.identifier {
				t.Errorf("expected identifier %d, got %d", tt.identifier, icmp.Id)
			}
			
			if icmp.Seq != tt.seq {
				t.Errorf("expected sequence %d, got %d", tt.seq, icmp.Seq)
			}
		})
	}
}

func TestParseICMPReply(t *testing.T) {
	// Create a simple ICMP packet for testing
	buffer := gopacket.NewSerializeBuffer()
	options := gopacket.SerializeOptions{
		FixLengths:       true,
		ComputeChecksums: true,
	}
	
	ipLayer := &layers.IPv4{
		Version:  4,
		IHL:      5,
		TTL:      64,
		Protocol: layers.IPProtocolICMPv4,
		SrcIP:    net.IPv4(192, 168, 1, 1),
		DstIP:    net.IPv4(192, 168, 1, 2),
	}
	
	icmpLayer := &layers.ICMPv4{
		TypeCode: layers.CreateICMPv4TypeCode(layers.ICMPv4TypeTimeExceeded, 0),
		Id:       12345,
		Seq:      1,
	}
	
	err := gopacket.SerializeLayers(buffer, options, ipLayer, icmpLayer)
	if err != nil {
		t.Fatalf("failed to serialize test packet: %v", err)
	}
	
	testPacket := buffer.Bytes()
	testTime := time.Now()
	
	parsed, err := ParseICMPReply(testPacket, testTime)
	if err != nil {
		t.Errorf("unexpected error parsing ICMP reply: %v", err)
		return
	}
	
	if parsed.Timestamp != testTime {
		t.Errorf("expected timestamp %v, got %v", testTime, parsed.Timestamp)
	}
	
	if parsed.IPv4 == nil {
		t.Errorf("expected IPv4 layer to be parsed")
		return
	}
	
	if parsed.ICMPv4 == nil {
		t.Errorf("expected ICMPv4 layer to be parsed")
		return
	}
	
	if !parsed.IsICMPError() {
		t.Errorf("expected packet to be identified as ICMP error")
	}
	
	if parsed.GetSourceIP() != "192.168.1.1" {
		t.Errorf("expected source IP 192.168.1.1, got %s", parsed.GetSourceIP())
	}
	
	if parsed.GetICMPType() != int(layers.ICMPv4TypeTimeExceeded) {
		t.Errorf("expected ICMP type %d, got %d", layers.ICMPv4TypeTimeExceeded, parsed.GetICMPType())
	}
}

func TestResolveHostname(t *testing.T) {
	// Test with localhost IP
	result := ResolveHostname("127.0.0.1")
	// Should return either the hostname or the IP itself
	if result == "" {
		t.Errorf("expected non-empty result for localhost resolution")
	}
	
	// Test with invalid IP
	result = ResolveHostname("invalid-ip")
	if result != "invalid-ip" {
		t.Errorf("expected invalid IP to be returned as-is, got %s", result)
	}
}

func TestResolveIP(t *testing.T) {
	// Test with localhost
	ip, err := ResolveIP("localhost")
	if err != nil {
		t.Errorf("unexpected error resolving localhost: %v", err)
	}
	if ip != "127.0.0.1" {
		t.Errorf("expected localhost to resolve to 127.0.0.1, got %s", ip)
	}
	
	// Test with invalid hostname
	_, err = ResolveIP("invalid-hostname-that-should-not-exist")
	if err == nil {
		t.Errorf("expected error for invalid hostname")
	}
}
