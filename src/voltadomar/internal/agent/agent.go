// Package agent implements the Voltadomar agent functionality
package agent

import (
	"context"
	"fmt"
	"log"
	"net"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/protobuf/types/known/anypb"

	"github.com/randofan/voltadomar/internal/constants"
	pb "github.com/randofan/voltadomar/proto/anycast"
)

// PacketData represents packet data with metadata
type PacketData struct {
	RawPacket []byte
	Timestamp time.Time
	SourceIP  string
}

// Agent represents an agent responsible for sending probes and listening for replies
type Agent struct {
	agentID           string
	controllerAddress string

	// gRPC client
	conn   *grpc.ClientConn
	client pb.AnycastServiceClient
	stream pb.AnycastService_ControlStreamClient

	// Worker management
	senderWorkers   *WorkerPool
	listenerWorkers *WorkerPool

	// Packet sniffer
	icmpConn *net.IPConn

	// Channels for communication
	outgoingMessages chan *pb.Message

	// Context for cancellation
	ctx    context.Context
	cancel context.CancelFunc

	// Wait group for graceful shutdown
	wg sync.WaitGroup
}

// NewAgent creates a new agent instance with input validation
func NewAgent(agentID, controllerAddress string) (*Agent, error) {
	// Validate input parameters
	if agentID == "" {
		return nil, fmt.Errorf("agentID cannot be empty")
	}
	if controllerAddress == "" {
		return nil, fmt.Errorf("controllerAddress cannot be empty")
	}

	ctx, cancel := context.WithCancel(context.Background())

	return &Agent{
		agentID:           agentID,
		controllerAddress: controllerAddress,
		ctx:               ctx,
		cancel:            cancel,
		outgoingMessages:  make(chan *pb.Message, constants.WorkerJobChannelSize),
	}, nil
}

// Run starts the agent's main processes
func (a *Agent) Run() error {
	log.Printf("Starting agent %s...", a.agentID)

	// Connect to controller
	if err := a.connectToController(); err != nil {
		return fmt.Errorf("failed to connect to controller: %w", err)
	}
	defer a.conn.Close()

	// Set up ICMP socket for packet sniffing (optional for testing)
	hasICMPSocket := false
	if err := a.setupICMPSocket(); err != nil {
		log.Printf("Warning: Failed to setup ICMP socket: %v", err)
		log.Printf("Continuing without packet sniffing capability...")
		log.Printf("Note: Raw socket operations require root privileges")
	} else {
		hasICMPSocket = true
		defer a.icmpConn.Close()
	}

	// Initialize worker pools
	a.senderWorkers = NewWorkerPool(constants.DefaultSenderWorkers, a.senderWorker)
	a.listenerWorkers = NewWorkerPool(constants.DefaultListenerWorkers, a.listenerWorker)

	// Start worker pools
	a.senderWorkers.Start()
	a.listenerWorkers.Start()
	log.Println("Worker pools started")

	// Register with controller
	if err := a.register(); err != nil {
		return fmt.Errorf("failed to register with controller: %w", err)
	}

	// Start goroutines based on available capabilities
	if hasICMPSocket {
		a.wg.Add(3)
		go a.handleController()
		go a.handleSniffer()
		go a.handleOutgoingMessages()
		log.Println("Started with full packet sniffing capability")
	} else {
		a.wg.Add(2)
		go a.handleController()
		go a.handleOutgoingMessages()
		log.Println("Started without packet sniffing (limited functionality)")
	}

	log.Println("Agent started successfully")

	// Wait for all goroutines to finish
	a.wg.Wait()

	// Stop worker pools
	a.senderWorkers.Stop()
	a.listenerWorkers.Stop()

	log.Println("Agent stopped")
	return nil
}

// Stop gracefully stops the agent
func (a *Agent) Stop() {
	log.Println("Stopping agent...")
	a.cancel()
}

// connectToController establishes gRPC connection to the controller
func (a *Agent) connectToController() error {
	log.Printf("Connecting to controller at %s...", a.controllerAddress)

	conn, err := grpc.NewClient(a.controllerAddress, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return err
	}

	a.conn = conn
	a.client = pb.NewAnycastServiceClient(conn)

	stream, err := a.client.ControlStream(a.ctx)
	if err != nil {
		return err
	}

	a.stream = stream
	log.Println("gRPC stream established")
	return nil
}

// setupICMPSocket creates an ICMP socket for packet sniffing
func (a *Agent) setupICMPSocket() error {
	conn, err := net.ListenIP("ip4:icmp", nil)
	if err != nil {
		return fmt.Errorf("failed to create ICMP socket (requires root privileges): %w", err)
	}

	a.icmpConn = conn
	log.Println("ICMP socket created")
	return nil
}

// register sends a registration message to the controller
func (a *Agent) register() error {
	registerPayload := &pb.Register{
		AgentId: a.agentID,
	}

	anyPayload, err := anypb.New(registerPayload)
	if err != nil {
		return err
	}

	message := &pb.Message{
		Payload: anyPayload,
	}

	select {
	case a.outgoingMessages <- message:
		log.Println("Registration message queued")
		return nil
	case <-a.ctx.Done():
		return a.ctx.Err()
	}
}

// handleController processes incoming messages from the controller
func (a *Agent) handleController() {
	defer a.wg.Done()

	log.Println("Listening for commands from controller...")

	for {
		select {
		case <-a.ctx.Done():
			return
		default:
			message, err := a.stream.Recv()
			if err != nil {
				log.Printf("Error receiving message from controller: %v", err)
				return
			}

			if err := a.processControllerMessage(message); err != nil {
				log.Printf("Error processing controller message: %v", err)
			}
		}
	}
}

// processControllerMessage processes a single message from the controller
func (a *Agent) processControllerMessage(message *pb.Message) error {
	if message.Payload == nil {
		return fmt.Errorf("received message with nil payload")
	}

	switch message.Payload.TypeUrl {
	case constants.MsgTypeJob:
		log.Println("Received JOB command")
		jobPayload := &pb.Job{}
		if err := message.Payload.UnmarshalTo(jobPayload); err != nil {
			return fmt.Errorf("failed to unmarshal Job: %w", err)
		}

		// Add job to sender worker pool
		if err := a.senderWorkers.AddJob(jobPayload); err != nil {
			return fmt.Errorf("failed to add job to sender workers: %w", err)
		}

	default:
		messageType := constants.GetMessageTypeFromURL(message.Payload.TypeUrl)
		log.Printf("Received unknown message type from controller: %s", messageType)
	}

	return nil
}

// handleSniffer listens for ICMP packets and processes them
func (a *Agent) handleSniffer() {
	defer a.wg.Done()

	if a.icmpConn == nil {
		log.Println("No ICMP socket available, skipping packet sniffer")
		return
	}

	log.Println("Starting packet sniffer...")

	buffer := make([]byte, constants.MaxPacketSize)

	for {
		select {
		case <-a.ctx.Done():
			return
		default:
			// Set read timeout to allow periodic context checking
			a.icmpConn.SetReadDeadline(time.Now().Add(constants.SocketReadTimeout))

			n, addr, err := a.icmpConn.ReadFromIP(buffer)
			if err != nil {
				if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
					continue // Timeout is expected, continue loop
				}
				log.Printf("Error reading ICMP packet: %v", err)
				continue
			}

			// Create packet data with timestamp
			packetData := &PacketData{
				RawPacket: make([]byte, n),
				Timestamp: time.Now(),
				SourceIP:  addr.IP.String(),
			}
			copy(packetData.RawPacket, buffer[:n])

			// Add packet to listener worker pool
			if err := a.listenerWorkers.AddJob(packetData); err != nil {
				log.Printf("Failed to add packet to listener workers: %v", err)
			}
		}
	}
}

// handleOutgoingMessages sends messages to the controller
func (a *Agent) handleOutgoingMessages() {
	defer a.wg.Done()

	for {
		select {
		case <-a.ctx.Done():
			return
		case message := <-a.outgoingMessages:
			if err := a.stream.Send(message); err != nil {
				log.Printf("Error sending message to controller: %v", err)
			}
		}
	}
}
