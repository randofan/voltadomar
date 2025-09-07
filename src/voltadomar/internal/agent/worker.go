// Package agent implements worker pool functionality
package agent

import (
	"context"
	"fmt"
	"log"
	"net"
	"sync"
	"time"

	"google.golang.org/protobuf/types/known/anypb"

	"github.com/randofan/voltadomar/internal/constants"
	"github.com/randofan/voltadomar/pkg/packets"
	pb "github.com/randofan/voltadomar/proto/anycast"
)

// WorkerPool manages a pool of goroutines processing jobs from a channel
type WorkerPool struct {
	workerCount int
	jobChan     chan interface{}
	workerFunc  func(interface{}) error
	ctx         context.Context
	cancel      context.CancelFunc
	wg          sync.WaitGroup
}

// NewWorkerPool creates a new worker pool
func NewWorkerPool(workerCount int, workerFunc func(interface{}) error) *WorkerPool {
	ctx, cancel := context.WithCancel(context.Background())
	return &WorkerPool{
		workerCount: workerCount,
		jobChan:     make(chan interface{}, constants.WorkerJobChannelSize),
		workerFunc:  workerFunc,
		ctx:         ctx,
		cancel:      cancel,
	}
}

// Start starts the worker pool
func (wp *WorkerPool) Start() {
	for i := 0; i < wp.workerCount; i++ {
		wp.wg.Add(1)
		go wp.worker(i)
	}
	log.Printf("Started %d workers", wp.workerCount)
}

// Stop stops the worker pool
func (wp *WorkerPool) Stop() {
	wp.cancel()
	close(wp.jobChan)
	wp.wg.Wait()
	log.Printf("Stopped %d workers", wp.workerCount)
}

// AddJob adds a job to the worker pool
func (wp *WorkerPool) AddJob(job interface{}) error {
	select {
	case wp.jobChan <- job:
		return nil
	case <-wp.ctx.Done():
		return wp.ctx.Err()
	default:
		return fmt.Errorf("job queue is full")
	}
}

// worker is the main worker loop
func (wp *WorkerPool) worker(id int) {
	defer wp.wg.Done()

	for {
		select {
		case <-wp.ctx.Done():
			return
		case job, ok := <-wp.jobChan:
			if !ok {
				return
			}

			if err := wp.workerFunc(job); err != nil {
				log.Printf("Worker %d error processing job: %v", id, err)
			}
		}
	}
}

// senderWorker processes job payloads by sending UDP probes
func (a *Agent) senderWorker(job interface{}) error {
	jobPayload, ok := job.(*pb.Job)
	if !ok {
		return fmt.Errorf("invalid job type for sender worker")
	}

	log.Printf("Processing job: session_id=%d, dst_ip=%s, max_ttl=%d, probe_num=%d",
		jobPayload.SessionId, jobPayload.DstIp, jobPayload.MaxTtl, jobPayload.ProbeNum)

	// Create UDP socket
	udpConn, err := net.Dial("udp", jobPayload.DstIp+":0")
	if err != nil {
		return fmt.Errorf("failed to create UDP socket: %w", err)
	}
	defer udpConn.Close()

	var udpAcks []*pb.UdpAck

	// Send probes for each TTL
	for ttl := 1; ttl <= int(jobPayload.MaxTtl); ttl++ {
		for probe := 0; probe < int(jobPayload.ProbeNum); probe++ {
			seq := (ttl-1)*int(jobPayload.ProbeNum) + probe
			port := uint16(jobPayload.BasePort) + uint16(seq)

			// Build UDP probe (for now, we'll use a simple approach)
			_, err := packets.BuildUDPProbe(
				jobPayload.DstIp,
				uint8(ttl),
				port,
				port,
			)
			if err != nil {
				log.Printf("Failed to build UDP probe: %v", err)
				continue
			}

			// Send probe
			sentTime := time.Now()

			// Create raw socket for sending with custom TTL
			rawConn, err := net.Dial("ip4:udp", jobPayload.DstIp)
			if err != nil {
				log.Printf("Failed to create raw socket: %v", err)
				continue
			}

			// Set TTL (this is platform-specific and may require additional setup)
			// Note: Setting TTL on raw sockets requires platform-specific code
			// For now, we'll use the standard UDP socket approach
			rawConn.Close()

			// Use standard UDP socket (TTL will be default)
			_, err = udpConn.Write([]byte("probe"))
			if err != nil {
				log.Printf("Failed to send UDP probe: %v", err)
				continue
			}

			// Record the UDP acknowledgment
			udpAck := &pb.UdpAck{
				Seq:      int32(seq),
				SentTime: sentTime.Format(time.RFC3339Nano),
			}
			udpAcks = append(udpAcks, udpAck)

			// Small delay between probes
			time.Sleep(constants.ProbeDelay)
		}
	}

	// Send DONE message to controller
	donePayload := &pb.Done{
		SessionId: jobPayload.SessionId,
		UdpAcks:   udpAcks,
	}

	anyPayload, err := anypb.New(donePayload)
	if err != nil {
		return fmt.Errorf("failed to marshal Done: %w", err)
	}

	message := &pb.Message{
		Payload: anyPayload,
	}

	select {
	case a.outgoingMessages <- message:
		log.Printf("DONE message queued for session %d", jobPayload.SessionId)
	case <-a.ctx.Done():
		return a.ctx.Err()
	}

	return nil
}

// listenerWorker processes incoming ICMP packets
func (a *Agent) listenerWorker(job interface{}) error {
	packetData, ok := job.(*PacketData)
	if !ok {
		return fmt.Errorf("invalid job type for listener worker")
	}

	// Parse the ICMP packet
	parsedPacket, err := packets.ParseICMPReply(packetData.RawPacket, packetData.Timestamp)
	if err != nil {
		// Not all packets will be valid ICMP replies, so we can ignore parse errors
		return nil
	}

	// Check if this is an ICMP error message (destination unreachable or time exceeded)
	if !parsedPacket.IsICMPError() {
		return nil // Not an error message we're interested in
	}

	log.Printf("Received ICMP error: type=%d, code=%d, from=%s",
		parsedPacket.GetICMPType(), parsedPacket.GetICMPCode(), parsedPacket.GetSourceIP())

	// Create reply payload
	replyPayload := &pb.Reply{
		RawPacket: packetData.RawPacket,
		Time:      packetData.Timestamp.Format(time.RFC3339Nano),
	}

	anyPayload, err := anypb.New(replyPayload)
	if err != nil {
		return fmt.Errorf("failed to marshal Reply: %w", err)
	}

	message := &pb.Message{
		Payload: anyPayload,
	}

	select {
	case a.outgoingMessages <- message:
		log.Printf("REPLY message queued from %s", parsedPacket.GetSourceIP())
	case <-a.ctx.Done():
		return a.ctx.Err()
	}

	return nil
}
