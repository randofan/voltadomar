// Package controller implements the Traceroute program
package controller

import (
	"fmt"
	"log"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/google/gopacket"
	"github.com/google/gopacket/layers"

	"github.com/randofan/voltadomar/internal/constants"
	"github.com/randofan/voltadomar/pkg/packets"
	pb "github.com/randofan/voltadomar/proto/anycast"
)

// TracerouteConf holds configuration for a traceroute program
type TracerouteConf struct {
	ProgramConf
	SourceHost      string
	DestinationHost string
	MaxTTL          int
	ProbeNum        int
	Timeout         int
	TOS             int
	StartID         int32
}

// TracerouteResult represents a single traceroute probe result
type TracerouteResult struct {
	Seq      int
	T1       string // Send time
	T2       string // Receive time
	Receiver string // Receiver IP
	Gateway  string // Gateway IP
	Timeout  bool
	FinalDst bool
}

// Traceroute implements the Program interface for traceroute measurements
type Traceroute struct {
	controller     ControllerInterface
	conf           *TracerouteConf
	sessionID      int32
	destinationIP  string
	results        []TracerouteResult
	receivedDone   bool
	waitingResults int
	finished       chan struct{}
	mu             sync.RWMutex
}

// NewTraceroute creates a new Traceroute program instance
func NewTraceroute(controller ControllerInterface, conf *TracerouteConf) (*Traceroute, error) {
	// Resolve destination IP
	destinationIP, err := packets.ResolveIP(conf.DestinationHost)
	if err != nil {
		return nil, fmt.Errorf("failed to resolve destination hostname '%s': %w", conf.DestinationHost, err)
	}

	totalProbes := conf.MaxTTL * conf.ProbeNum
	results := make([]TracerouteResult, totalProbes)

	// Initialize all results as timeouts
	for i := 0; i < totalProbes; i++ {
		results[i] = TracerouteResult{
			Seq:     i,
			Timeout: true,
		}
	}

	return &Traceroute{
		controller:     controller,
		conf:           conf,
		sessionID:      conf.StartID,
		destinationIP:  destinationIP,
		results:        results,
		waitingResults: totalProbes,
		finished:       make(chan struct{}),
	}, nil
}

// Run executes the traceroute program
func (tr *Traceroute) Run() (string, error) {
	log.Printf("Traceroute to %s (%s) from %s, %d probes, %d hops max, timeout %d seconds",
		tr.conf.DestinationHost, tr.destinationIP, tr.conf.SourceHost,
		tr.conf.ProbeNum, tr.conf.MaxTTL, tr.conf.Timeout)

	// Create job payload
	jobPayload := &pb.Job{
		SessionId: tr.sessionID,
		DstIp:     tr.destinationIP,
		MaxTtl:    int32(tr.conf.MaxTTL),
		ProbeNum:  int32(tr.conf.ProbeNum),
		BasePort:  tr.seqToPort(0),
	}

	// Send job to agent
	if err := tr.controller.SendJob(tr.conf.SourceHost, jobPayload); err != nil {
		return "", fmt.Errorf("failed to send job to agent %s: %w", tr.conf.SourceHost, err)
	}

	log.Println("Job sent to agent, waiting for results...")

	// Wait for completion or timeout
	timeout := time.Duration(tr.conf.Timeout) * time.Second
	select {
	case <-tr.finished:
		log.Println("Traceroute completed")
	case <-time.After(timeout):
		log.Println("Traceroute timed out")
	}

	return tr.formatResults(), nil
}

// HandleDone processes a DONE message from an agent
func (tr *Traceroute) HandleDone(payload *pb.Done) {
	tr.mu.Lock()
	defer tr.mu.Unlock()

	if payload.SessionId != tr.sessionID {
		return // Not for this session
	}

	log.Printf("Received DONE for session %d with %d UDP acks", payload.SessionId, len(payload.UdpAcks))

	// Process UDP acknowledgments to set send times
	for _, udpAck := range payload.UdpAcks {
		seq := int(udpAck.Seq)
		if seq >= 0 && seq < len(tr.results) {
			tr.results[seq].T1 = udpAck.SentTime
		}
	}

	tr.receivedDone = true
	tr.checkDone()
}

// HandleReply processes a REPLY message from an agent
func (tr *Traceroute) HandleReply(payload *pb.Reply, agentID string) bool {
	tr.mu.Lock()
	defer tr.mu.Unlock()

	// Parse the ICMP packet
	parsedPacket, err := packets.ParseICMPReply(payload.RawPacket, time.Now())
	if err != nil {
		return false // Not a valid ICMP packet for us
	}

	// Check if this is an ICMP error message
	if !parsedPacket.IsICMPError() {
		return false
	}

	// Extract information from the packet
	icmpType := parsedPacket.GetICMPType()
	sourceIP := parsedPacket.GetSourceIP()
	receiveTime := payload.Time

	// Try to extract the original UDP port from the inner packet
	seq, ok := tr.extractSequenceFromPacket(payload.RawPacket)
	if !ok {
		return false
	}

	// Validate sequence number
	if seq < 0 || seq >= len(tr.results) {
		return false
	}

	log.Printf("Processing ICMP reply: type=%d, seq=%d, from=%s", icmpType, seq, sourceIP)

	// Update the result
	result := &tr.results[seq]
	result.T2 = receiveTime
	result.Receiver = agentID
	result.Gateway = sourceIP
	result.Timeout = false
	result.FinalDst = (icmpType == int(layers.ICMPv4TypeDestinationUnreachable))

	tr.waitingResults--
	log.Printf("Updated traceroute result for sequence %d (waiting: %d)", seq, tr.waitingResults)

	tr.checkDone()
	return true
}

// seqToPort converts a sequence number to a port number
func (tr *Traceroute) seqToPort(seq int) int32 {
	return int32(seq) + tr.sessionID
}

// extractSequenceFromPacket extracts the sequence number from an ICMP error packet
func (tr *Traceroute) extractSequenceFromPacket(rawPacket []byte) (int, bool) {
	packet := gopacket.NewPacket(rawPacket, layers.LayerTypeIPv4, gopacket.Default)

	// Look for UDP layer in the inner packet (ICMP error contains original packet)
	if udpLayer := packet.Layer(layers.LayerTypeUDP); udpLayer != nil {
		if udp, ok := udpLayer.(*layers.UDP); ok {
			port := int(udp.DstPort)
			seq := port - int(tr.sessionID)
			if seq >= 0 && seq < len(tr.results) {
				return seq, true
			}
		}
	}

	return 0, false
}

// checkDone checks if the traceroute is complete
func (tr *Traceroute) checkDone() {
	if tr.receivedDone && tr.waitingResults == 0 {
		log.Println("Traceroute finished")
		select {
		case tr.finished <- struct{}{}:
		default:
		}
	}
}

// formatResults formats the traceroute results into a human-readable string
func (tr *Traceroute) formatResults() string {
	tr.mu.RLock()
	defer tr.mu.RUnlock()

	var output []string
	output = append(output, fmt.Sprintf("Traceroute to %s (%s) from %s, %d probes, %d hops max",
		tr.conf.DestinationHost, tr.destinationIP, tr.conf.SourceHost,
		tr.conf.ProbeNum, tr.conf.MaxTTL))

	for ttl := 1; ttl <= tr.conf.MaxTTL; ttl++ {
		lineParts := []string{strconv.Itoa(ttl)}
		startSeq := tr.conf.ProbeNum * (ttl - 1)
		foundFinalDst := false

		var prevGateway, prevReceiver string
		for seq := startSeq; seq < startSeq+tr.conf.ProbeNum; seq++ {
			if seq >= len(tr.results) {
				break
			}

			current := tr.results[seq]

			if current.Timeout {
				lineParts = append(lineParts, "*")
				continue
			}

			if current.FinalDst {
				foundFinalDst = true
			}

			if current.Gateway != prevGateway || current.Receiver != prevReceiver {
				hostname := packets.ResolveHostname(current.Gateway)
				lineParts = append(lineParts, fmt.Sprintf("%s (%s) %s", hostname, current.Gateway, current.Receiver))
				prevGateway = current.Gateway
				prevReceiver = current.Receiver
			}

			// Calculate timing if both timestamps are available
			if current.T1 != "" && current.T2 != "" {
				t1, err1 := time.Parse(time.RFC3339Nano, current.T1)
				t2, err2 := time.Parse(time.RFC3339Nano, current.T2)
				if err1 == nil && err2 == nil {
					deltaMs := t2.Sub(t1).Seconds() * 1000
					lineParts = append(lineParts, fmt.Sprintf("%.3f ms", deltaMs))
				}
			}
		}

		output = append(output, strings.Join(lineParts, "  "))
		if foundFinalDst {
			break
		}
	}

	return strings.Join(output, "\n")
}

// ParseTracerouteArgs parses command line arguments for traceroute
func ParseTracerouteArgs(command string) (*TracerouteConf, error) {
	parts := strings.Fields(command)
	if len(parts) < 3 {
		return nil, fmt.Errorf("usage: volta <source> <destination> [-m <max-ttls>] [-w <waittime>] [-q <nqueries>]")
	}

	conf := &TracerouteConf{
		SourceHost:      parts[1],
		DestinationHost: parts[2],
		MaxTTL:          constants.DefaultMaxTTL,
		ProbeNum:        constants.DefaultProbeNum,
		Timeout:         constants.DefaultTimeout,
		TOS:             constants.DefaultTOS,
	}

	// Parse optional arguments
	for i := 3; i < len(parts)-1; i++ {
		switch parts[i] {
		case "-m", "--max-ttls":
			if i+1 < len(parts) {
				if val, err := strconv.Atoi(parts[i+1]); err == nil {
					conf.MaxTTL = val
					i++
				}
			}
		case "-w", "--waittime":
			if i+1 < len(parts) {
				if val, err := strconv.Atoi(parts[i+1]); err == nil {
					conf.Timeout = val
					i++
				}
			}
		case "-q", "--nqueries":
			if i+1 < len(parts) {
				if val, err := strconv.Atoi(parts[i+1]); err == nil {
					conf.ProbeNum = val
					i++
				}
			}
		case "-t", "--tos":
			if i+1 < len(parts) {
				if val, err := strconv.Atoi(parts[i+1]); err == nil {
					conf.TOS = val
					i++
				}
			}
		}
	}

	return conf, nil
}
