// Package main implements the Voltadomar agent command-line interface
package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/randofan/voltadomar/internal/agent"
)

func main() {
	// Define command-line flags
	var (
		agentID           = flag.String("i", "", "The unique ID for this agent (defaults to hostname)")
		controllerAddress = flag.String("c", "127.0.0.1:50051", "The address (host:port) of the controller gRPC service")
		help              = flag.Bool("h", false, "Show help message")
	)

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: %s [options]\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "Voltadomar Agent - Distributed anycast network measurement agent\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nExample:\n")
		fmt.Fprintf(os.Stderr, "  %s -i agent1 -c 127.0.0.1:50051\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "Note: This program requires root privileges for raw socket operations.\n")
	}

	flag.Parse()

	if *help {
		flag.Usage()
		os.Exit(0)
	}

	// Set default agent ID to hostname if not provided
	if *agentID == "" {
		hostname, err := os.Hostname()
		if err != nil {
			log.Fatalf("Failed to get hostname and no agent ID provided: %v", err)
		}
		*agentID = hostname
	}

	// Validate required parameters
	if *controllerAddress == "" {
		log.Fatal("Controller address is required")
	}

	log.Printf("Starting Voltadomar Agent")
	log.Printf("Agent ID: %s", *agentID)
	log.Printf("Controller Address: %s", *controllerAddress)

	// Check if running as root (required for raw sockets)
	if os.Geteuid() != 0 {
		log.Println("Warning: Not running as root. Raw socket operations may fail.")
		log.Println("Consider running with sudo for full functionality.")
	}

	// Create agent
	agentInstance, err := agent.NewAgent(*agentID, *controllerAddress)
	if err != nil {
		log.Fatalf("Failed to create agent: %v", err)
	}

	// Set up signal handling for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start agent in a goroutine
	errChan := make(chan error, 1)
	go func() {
		errChan <- agentInstance.Run()
	}()

	// Wait for either an error or a signal
	select {
	case err := <-errChan:
		if err != nil {
			log.Fatalf("Agent error: %v", err)
		}
		log.Println("Agent finished successfully")
	case sig := <-sigChan:
		log.Printf("Received signal %v, shutting down gracefully...", sig)
		agentInstance.Stop()

		// Wait for agent to finish
		if err := <-errChan; err != nil {
			log.Printf("Agent shutdown error: %v", err)
		}
		log.Println("Agent stopped")
	}
}
