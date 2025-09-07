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

	"github.com/randofan/voltadomar/internal/controller"
)

func main() {
	// Define command-line flags
	var (
		port      = flag.Int("port", 50051, "Port to run the server on")
		rangeFlag = flag.String("range", "", "Controller session ID allocation range (e.g., 1000-2000)")
		blockSize = flag.Int("block", 0, "Session ID block size per program")
		help      = flag.Bool("h", false, "Show help message")
	)

	flag.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: %s [options]\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "Voltadomar Controller - Distributed anycast network measurement controller\n\n")
		fmt.Fprintf(os.Stderr, "Options:\n")
		flag.PrintDefaults()
		fmt.Fprintf(os.Stderr, "\nExample:\n")
		fmt.Fprintf(os.Stderr, "  %s --port 50051 --range 10000-20000 --block 100\n\n", os.Args[0])
		fmt.Fprintf(os.Stderr, "The controller manages session ID allocation and coordinates measurement\n")
		fmt.Fprintf(os.Stderr, "tasks between user clients and distributed agents.\n")
	}

	flag.Parse()

	if *help {
		flag.Usage()
		os.Exit(0)
	}

	// Validate required parameters
	if *rangeFlag == "" {
		log.Fatal("Range parameter is required (e.g., --range 1000-2000)")
	}

	if *blockSize <= 0 {
		log.Fatal("Block size parameter is required and must be positive (e.g., --block 100)")
	}

	// Parse range parameter
	rangeParts := strings.Split(*rangeFlag, "-")
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

	// Validate range
	if startID < 0 {
		log.Fatal("Start ID must be non-negative")
	}

	if startID >= endID {
		log.Fatal("Start ID must be less than end ID")
	}

	if *blockSize <= 0 {
		log.Fatal("Block size must be positive")
	}

	// Check if block size is reasonable for the range
	rangeSize := endID - startID
	if *blockSize > rangeSize {
		log.Printf("Warning: Block size %d is larger than the available range %d. Only one program can run concurrently.", *blockSize, rangeSize)
	}

	if rangeSize < *blockSize {
		log.Printf("Warning: The range %s is smaller than the block size %d.", *rangeFlag, *blockSize)
	}

	log.Printf("Starting Voltadomar Controller")
	log.Printf("Port: %d", *port)
	log.Printf("Session ID Range: %d-%d", startID, endID)
	log.Printf("Block Size: %d", *blockSize)

	// Create controller
	controllerInstance, err := controller.NewController(*port, int32(startID), int32(endID), int32(*blockSize))
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
