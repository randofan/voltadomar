// Package controller implements the Program interface and related functionality
package controller

import (
	pb "github.com/randofan/voltadomar/proto/anycast"
)

// ProgramConf represents configuration for a program
type ProgramConf struct {
	// Base configuration - can be extended by specific program types
}

// Program defines the interface for any measurement program
type Program interface {
	Run() (string, error)
	HandleDone(payload *pb.Done)
	HandleReply(payload *pb.Reply, agentID string) bool
}

// Controller interface for programs to interact with the controller
type ControllerInterface interface {
	SendJob(agentID string, jobPayload *pb.Job) error
}
