// Package main implements the Voltadomar controller command-line interface
package main

import (
	"flag"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"

	"gopkg.in/yaml.v3"

	"github.com/randofan/voltadomar/internal/controller"
)

type ControllerConfig struct {
	Port         int    `yaml:"port"`
	SessionRange string `yaml:"session_range"`
	BlockSize    int    `yaml:"block_size"`
	LogLevel     string `yaml:"log_level"`
}

func loadControllerConfig(path string, defaults ControllerConfig) ControllerConfig {
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
		port      = flag.Int("port", 50051, "Port to run the server on")
		rangeFlag = flag.String("range", "", "Controller session ID allocation range (e.g., 1000-2000)")
		blockSize = flag.Int("block", 0, "Session ID block size per program")
		logLevel  = flag.String("log-level", "info", "Log level (debug, info, warn, error)")
		config    = flag.String("config", "/etc/voltadomar/controller.yaml", "Path to YAML config file")
		help      = flag.Bool("h", false, "Show help message")
	)

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: %s [options]\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "Voltadomar Controller - Distributed anycast network measurement controller\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nExamples:\n")
		fmt.Fprintf(os.Stderr, "  %s --config /etc/voltadomar/controller.yaml\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "  %s --port 50051 --range 10000-20000 --block 100\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "The controller manages session ID allocation and coordinates measurement\n")
		fmt.Fprintf(os.Stderr, "tasks between user clients and distributed agents.\n")
	}

	flag.Parse()

	if *help {
		flag.Usage()
		os.Exit(0)
	}

	// Defaults per plan
	defaults := ControllerConfig{Port: 50051, SessionRange: "10000-20000", BlockSize: 100, LogLevel: "info"}
	cfg := loadControllerConfig(*config, defaults)

	// Track which flags were explicitly set to enforce precedence: CLI > config > defaults
	setFlags := map[string]bool{}
	flag.Visit(func(f *flag.Flag) { setFlags[f.Name] = true })
	if setFlags["port"] {
		cfg.Port = *port
	}
	if setFlags["range"] {
		cfg.SessionRange = *rangeFlag
	}
	if setFlags["block"] {
		cfg.BlockSize = *blockSize
	}
	if setFlags["log-level"] {
		cfg.LogLevel = *logLevel
	}

	// Parse and validate session range
	rangeParts := strings.Split(cfg.SessionRange, "-")
	if len(rangeParts) != 2 {
		log.Fatal("Invalid range format. Use format: START-END (e.g., 1000-2000)")
	}
	startID, err := strconv.Atoi(rangeParts[0])
	if err != nil {
		log.Fatalf("Invalid start ID in range: %v", err)
	}
	endID, err := strconv.Atoi(rangeParts[1])
	if err != nil {
		log.Fatalf("Invalid end ID in range: %v", err)
	}
	if startID < 0 {
		log.Fatal("Start ID must be non-negative")
	}
	if startID >= endID {
		log.Fatal("Start ID must be less than end ID")
	}
	if cfg.BlockSize <= 0 {
		log.Fatal("Block size must be positive")
	}

	// Check if block size is reasonable for the range
	rangeSize := endID - startID
	if cfg.BlockSize > rangeSize {
		log.Printf("Warning: Block size %d is larger than the available range %d. Only one program can run concurrently.", cfg.BlockSize, rangeSize)
	}
	if rangeSize < cfg.BlockSize {
		log.Printf("Warning: The range %s is smaller than the block size %d.", cfg.SessionRange, cfg.BlockSize)
	}

	log.Printf("Starting Voltadomar Controller")
	log.Printf("Port: %d", cfg.Port)
	log.Printf("Session ID Range: %d-%d", startID, endID)
	log.Printf("Block Size: %d", cfg.BlockSize)
	log.Printf("Log Level: %s", cfg.LogLevel)

	// Create controller
	controllerInstance, err := controller.NewController(cfg.Port, int32(startID), int32(endID), int32(cfg.BlockSize))
	if err != nil {
		log.Fatalf("Failed to create controller: %v", err)
	}

	// Set up signal handling for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start controller in a goroutine
	errChan := make(chan error, 1)
	go func() {
		errChan <- controllerInstance.Run()
	}()

	// Wait for either an error or a signal
	select {
	case err := <-errChan:
		if err != nil {
			log.Fatalf("Controller error: %v", err)
		}
		log.Println("Controller finished successfully")
	case sig := <-sigChan:
		log.Printf("Received signal %v, shutting down gracefully...", sig)
		controllerInstance.Stop()

		// Wait for controller to finish
		if err := <-errChan; err != nil {
			log.Printf("Controller shutdown error: %v", err)
		}
		log.Println("Controller stopped")
	}
}
