// Package controller implements the Voltadomar controller functionality
package controller

import (
	"context"
	"fmt"
	"log"
	"net"
	"sync"

	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/anypb"

	"github.com/randofan/voltadomar/internal/constants"
	pb "github.com/randofan/voltadomar/proto/anycast"
)

// Controller manages agent connections, session allocation, and program execution
type Controller struct {
	pb.UnimplementedAnycastServiceServer

	port      int
	startID   int32
	endID     int32
	blockSize int32

	// Session management
	nextSessionID int32
	inUseBlocks   map[int32]bool

	// Agent and program management
	agentStreams map[string]pb.AnycastService_ControlStreamServer
	programs     map[int32]Program

	// Synchronization
	mu sync.RWMutex

	// gRPC server
	server *grpc.Server
}

// NewController creates a new Controller instance with input validation
func NewController(port int, startID, endID, blockSize int32) (*Controller, error) {
	// Validate input parameters
	if port <= 0 || port > 65535 {
		return nil, fmt.Errorf("invalid port %d: must be between 1 and 65535", port)
	}
	if startID < 0 {
		return nil, fmt.Errorf("invalid startID %d: must be non-negative", startID)
	}
	if endID <= startID {
		return nil, fmt.Errorf("invalid endID %d: must be greater than startID %d", endID, startID)
	}
	if blockSize <= 0 {
		return nil, fmt.Errorf("invalid blockSize %d: must be positive", blockSize)
	}
	if blockSize > (endID - startID) {
		return nil, fmt.Errorf("blockSize %d is larger than available range %d", blockSize, endID-startID)
	}

	return &Controller{
		port:          port,
		startID:       startID,
		endID:         endID,
		blockSize:     blockSize,
		nextSessionID: startID,
		inUseBlocks:   make(map[int32]bool),
		agentStreams:  make(map[string]pb.AnycastService_ControlStreamServer),
		programs:      make(map[int32]Program),
	}, nil
}

// AllocateSessionID allocates a new session ID block using a sliding window approach
func (c *Controller) AllocateSessionID() (int32, error) {
	c.mu.Lock()
	defer c.mu.Unlock()

	// Calculate total number of possible blocks
	totalRange := c.endID - c.startID
	maxBlocks := totalRange / c.blockSize
	if maxBlocks == 0 {
		return 0, fmt.Errorf("block size %d is larger than available range %d", c.blockSize, totalRange)
	}

	startSearch := c.nextSessionID
	currentID := startSearch
	blocksChecked := int32(0)

	// Search for available block with bounded loop
	for blocksChecked < maxBlocks {
		// Ensure currentID is within bounds and aligned to block boundaries
		if currentID < c.startID || currentID+c.blockSize > c.endID {
			currentID = c.startID
		}

		if !c.inUseBlocks[currentID] {
			c.inUseBlocks[currentID] = true
			c.nextSessionID = currentID + c.blockSize
			if c.nextSessionID >= c.endID {
				c.nextSessionID = c.startID
			}
			log.Printf("Allocated session ID block starting at %d", currentID)
			return currentID, nil
		}

		currentID += c.blockSize
		blocksChecked++
	}

	return 0, fmt.Errorf("no available session ID blocks (checked %d blocks)", blocksChecked)
}

// ReleaseSessionID releases a session ID block
func (c *Controller) ReleaseSessionID(sessionID int32) {
	c.mu.Lock()
	defer c.mu.Unlock()

	delete(c.inUseBlocks, sessionID)
	log.Printf("Released session ID block starting at %d", sessionID)
}

// SendJob sends a job payload to a specific agent
func (c *Controller) SendJob(agentID string, jobPayload *pb.Job) error {
	c.mu.RLock()
	stream, exists := c.agentStreams[agentID]
	c.mu.RUnlock()

	if !exists {
		return fmt.Errorf("agent %s not connected", agentID)
	}

	// Pack the job payload
	anyPayload, err := anypb.New(jobPayload)
	if err != nil {
		return fmt.Errorf("failed to pack job payload: %w", err)
	}

	message := &pb.Message{
		Payload: anyPayload,
	}

	if err := stream.Send(message); err != nil {
		return fmt.Errorf("failed to send job to agent %s: %w", agentID, err)
	}

	log.Printf("Successfully sent job to agent %s", agentID)
	return nil
}

// ControlStream handles bidirectional streaming with agents
func (c *Controller) ControlStream(stream pb.AnycastService_ControlStreamServer) error {
	var agentID string

	defer func() {
		if agentID != "" {
			c.mu.Lock()
			delete(c.agentStreams, agentID)
			c.mu.Unlock()
			log.Printf("Agent %s disconnected", agentID)
		}
	}()

	for {
		message, err := stream.Recv()
		if err != nil {
			log.Printf("Error receiving message from agent %s: %v", agentID, err)
			return err
		}

		if err := c.processAgentMessage(message, &agentID, stream); err != nil {
			log.Printf("Error processing message from agent %s: %v", agentID, err)
			return err
		}
	}
}

// processAgentMessage processes a single message from an agent
func (c *Controller) processAgentMessage(message *pb.Message, agentID *string, stream pb.AnycastService_ControlStreamServer) error {
	if message.Payload == nil {
		return fmt.Errorf("received message with nil payload")
	}

	switch message.Payload.TypeUrl {
	case constants.MsgTypeRegister:
		registerPayload := &pb.Register{}
		if err := message.Payload.UnmarshalTo(registerPayload); err != nil {
			return fmt.Errorf("failed to unmarshal Register: %w", err)
		}

		*agentID = registerPayload.AgentId
		c.mu.Lock()
		c.agentStreams[*agentID] = stream
		c.mu.Unlock()

		log.Printf("Agent %s registered", *agentID)

	case constants.MsgTypeDone:
		donePayload := &pb.Done{}
		if err := message.Payload.UnmarshalTo(donePayload); err != nil {
			return fmt.Errorf("failed to unmarshal Done: %w", err)
		}

		c.mu.RLock()
		program, exists := c.programs[donePayload.SessionId]
		c.mu.RUnlock()

		if exists {
			program.HandleDone(donePayload)
		}

	case constants.MsgTypeReply:
		replyPayload := &pb.Reply{}
		if err := message.Payload.UnmarshalTo(replyPayload); err != nil {
			return fmt.Errorf("failed to unmarshal Reply: %w", err)
		}

		// Try to find a program that can handle this reply
		c.mu.RLock()
		for _, program := range c.programs {
			if program.HandleReply(replyPayload, *agentID) {
				break
			}
		}
		c.mu.RUnlock()

	case constants.MsgTypeError:
		errorPayload := &pb.Error{}
		if err := message.Payload.UnmarshalTo(errorPayload); err != nil {
			return fmt.Errorf("failed to unmarshal Error: %w", err)
		}

		log.Printf("Error from agent %s: %d - %s", *agentID, errorPayload.Code, errorPayload.Message)

	default:
		messageType := constants.GetMessageTypeFromURL(message.Payload.TypeUrl)
		log.Printf("Unknown message type from agent %s: %s", *agentID, messageType)
	}

	return nil
}

// UserRequest handles user requests to run programs
func (c *Controller) UserRequest(ctx context.Context, request *pb.Request) (*pb.Response, error) {
	log.Printf("Received user request: %s", request.Command)

	// Allocate session ID
	sessionStartID, err := c.AllocateSessionID()
	if err != nil {
		return &pb.Response{
			Code:   500,
			Output: fmt.Sprintf("Failed to allocate session ID: %v", err),
		}, nil
	}

	defer c.ReleaseSessionID(sessionStartID)

	// Parse traceroute command
	conf, err := ParseTracerouteArgs(request.Command)
	if err != nil {
		return &pb.Response{
			Code:   400,
			Output: fmt.Sprintf("Invalid command: %v", err),
		}, nil
	}

	conf.StartID = sessionStartID

	// Create and run traceroute program
	traceroute, err := NewTraceroute(c, conf)
	if err != nil {
		return &pb.Response{
			Code:   500,
			Output: fmt.Sprintf("Failed to create traceroute: %v", err),
		}, nil
	}

	// Register the program
	c.mu.Lock()
	c.programs[sessionStartID] = traceroute
	c.mu.Unlock()

	defer func() {
		c.mu.Lock()
		delete(c.programs, sessionStartID)
		c.mu.Unlock()
	}()

	// Run the program
	output, err := traceroute.Run()
	if err != nil {
		return &pb.Response{
			Code:   500,
			Output: fmt.Sprintf("Program execution failed: %v", err),
		}, nil
	}

	return &pb.Response{
		Code:   200,
		Output: output,
	}, nil
}

// Run starts the gRPC server and waits for termination
func (c *Controller) Run() error {
	lis, err := net.Listen("tcp", fmt.Sprintf(":%d", c.port))
	if err != nil {
		return fmt.Errorf("failed to listen on port %d: %w", c.port, err)
	}

	c.server = grpc.NewServer()
	pb.RegisterAnycastServiceServer(c.server, c)

	log.Printf("Controller starting on port %d", c.port)
	log.Printf("Session ID range: %d-%d, block size: %d", c.startID, c.endID, c.blockSize)

	if err := c.server.Serve(lis); err != nil {
		return fmt.Errorf("failed to serve: %w", err)
	}

	return nil
}

// Stop gracefully stops the controller
func (c *Controller) Stop() {
	if c.server != nil {
		log.Println("Stopping controller...")
		c.server.GracefulStop()
		log.Println("Controller stopped")
	}
}
