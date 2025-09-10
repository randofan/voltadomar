// Package main implements the Voltadomar agent command-line interface
package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"

	"gopkg.in/yaml.v3"

	"github.com/randofan/voltadomar/internal/agent"
)

type AgentConfig struct {
	AgentID           string `yaml:"agent_id"`
	ControllerAddress string `yaml:"controller_address"`
	LogLevel          string `yaml:"log_level"`
}

func loadAgentConfig(path string, defaults AgentConfig) AgentConfig {
	cfg := defaults
	if path == "" {
		return cfg
	}
	b, err := os.ReadFile(path)
	if err != nil {
		// If the file doesn't exist, just use defaults
		return cfg
	}
	if err := yaml.Unmarshal(b, &cfg); err != nil {
		log.Printf("Warning: failed to parse config %s: %v (using defaults)", path, err)
		return defaults
	}
	return cfg
}

func main() {
	// Define command-line flags
	var (
		agentID           = flag.String("i", "", "The unique ID for this agent (defaults to hostname)")
		controllerAddress = flag.String("c", "127.0.0.1:50051", "The address (host:port) of the controller gRPC service")
		logLevel          = flag.String("log-level", "info", "Log level (debug, info, warn, error)")
		config            = flag.String("config", "/etc/voltadomar/agent.yaml", "Path to YAML config file")
		help              = flag.Bool("h", false, "Show help message")
	)

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: %s [options]\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "Voltadomar Agent - Distributed anycast network measurement agent\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nExamples:\n")
		fmt.Fprintf(os.Stderr, "  %s --config /etc/voltadomar/agent.yaml\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s -i agent1 -c 127.0.0.1:50051\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "Note: This program requires root privileges for raw socket operations.\n")
	}

	flag.Parse()

	if *help {
		flag.Usage()
		os.Exit(0)
	}

	// Defaults per plan
	defaults := AgentConfig{AgentID: "", ControllerAddress: "127.0.0.1:50051", LogLevel: "info"}
	cfg := loadAgentConfig(*config, defaults)

	// Track which flags were explicitly set to enforce precedence: CLI > config > defaults
	setFlags := map[string]bool{}
	flag.Visit(func(f *flag.Flag) { setFlags[f.Name] = true })
	if setFlags["i"] {
		cfg.AgentID = *agentID
	}
	if setFlags["c"] {
		cfg.ControllerAddress = *controllerAddress
	}
	if setFlags["log-level"] {
		cfg.LogLevel = *logLevel
	}

	// Set default agent ID to hostname if not provided (after config merge)
	if cfg.AgentID == "" {
		hostname, err := os.Hostname()
		if err != nil {
			log.Fatalf("Failed to get hostname and no agent ID provided: %v", err)
		}
		cfg.AgentID = hostname
	}

	// Validate required parameters
	if cfg.ControllerAddress == "" {
		log.Fatal("Controller address is required")
	}

	log.Printf("Starting Voltadomar Agent")
	log.Printf("Agent ID: %s", cfg.AgentID)
	log.Printf("Controller Address: %s", cfg.ControllerAddress)
	log.Printf("Log Level: %s", cfg.LogLevel)

	// Check if running as root (required for raw sockets)
	if os.Geteuid() != 0 {
		log.Println("Warning: Not running as root. Raw socket operations may fail.")
		log.Println("Consider running with sudo for full functionality.")
	}

	// Create agent
	agentInstance, err := agent.NewAgent(cfg.AgentID, cfg.ControllerAddress)
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
