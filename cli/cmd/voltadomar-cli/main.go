// Package main implements the Voltadomar CLI client
package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"os"
	"strconv"
	"strings"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"

	pb "github.com/randofan/voltadomar-cli/proto/anycast"
)

// Config holds the configuration for the CLI
type Config struct {
	Source      string
	Destination string
	Runs        int
	Controller  string
}

// printUsage prints the usage information
func printUsage() {
	fmt.Fprintf(os.Stderr, "Voltadomar Traceroute CLI Client\n\n")
	fmt.Fprintf(os.Stderr, "Usage:\n")
	fmt.Fprintf(os.Stderr, "  %s <source> <destination> [runs] [options]\n\n", os.Args[0])
	fmt.Fprintf(os.Stderr, "Arguments:\n")
	fmt.Fprintf(os.Stderr, "  source      The anycast source node (agent ID)\n")
	fmt.Fprintf(os.Stderr, "  destination The destination address to traceroute to\n")
	fmt.Fprintf(os.Stderr, "  runs        Number of traceroute runs to perform (default: 1)\n\n")
	fmt.Fprintf(os.Stderr, "Options:\n")
	fmt.Fprintf(os.Stderr, "  -c, --controller string   Controller address (default: localhost:50051)\n")
	fmt.Fprintf(os.Stderr, "  -h, --help               Show this help message\n")
	fmt.Fprintf(os.Stderr, "\nExample:\n")
	fmt.Fprintf(os.Stderr, "  %s agent1 8.8.8.8 3 -c controller.example.com:50051\n", os.Args[0])
}

// parseArgs parses command-line arguments and returns a Config
func parseArgs() (*Config, error) {
	var config Config

	// Initialize with defaults
	config.Controller = "localhost:50051"

	// Manual argument parsing to handle flags anywhere in the command line
	// This matches the Python argparse behavior
	var args []string
	var i int

	for i = 1; i < len(os.Args); i++ {
		arg := os.Args[i]
		if arg == "-c" || arg == "--controller" {
			if i+1 >= len(os.Args) {
				return nil, fmt.Errorf("flag %s requires a value", arg)
			}
			config.Controller = os.Args[i+1]
			i++ // skip the value
		} else if arg == "-h" || arg == "--help" {
			printUsage()
			os.Exit(0)
		} else {
			args = append(args, arg)
		}
	}

	// Parse positional arguments
	if len(args) < 2 {
		printUsage()
		return nil, fmt.Errorf("insufficient arguments: source and destination are required")
	}

	config.Source = args[0]
	config.Destination = args[1]
	config.Runs = 1 // default

	// Parse optional runs argument
	if len(args) >= 3 {
		runs, err := strconv.Atoi(args[2])
		if err != nil {
			return nil, fmt.Errorf("invalid runs value '%s': must be a positive integer", args[2])
		}
		if runs <= 0 {
			return nil, fmt.Errorf("runs must be a positive integer, got %d", runs)
		}
		config.Runs = runs
	}

	// Validate arguments
	if config.Source == "" {
		return nil, fmt.Errorf("source cannot be empty")
	}
	if config.Destination == "" {
		return nil, fmt.Errorf("destination cannot be empty")
	}
	if config.Controller == "" {
		return nil, fmt.Errorf("controller address cannot be empty")
	}

	// Validate controller address format
	if err := validateControllerAddress(config.Controller); err != nil {
		return nil, fmt.Errorf("invalid controller address: %v", err)
	}

	return &config, nil
}

// validateControllerAddress validates the controller address format
func validateControllerAddress(address string) error {
	if !strings.Contains(address, ":") {
		return fmt.Errorf("address must be in format host:port")
	}

	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return fmt.Errorf("invalid address format: %v", err)
	}

	if host == "" {
		return fmt.Errorf("host cannot be empty")
	}

	if port == "" {
		return fmt.Errorf("port cannot be empty")
	}

	// Try to parse port as integer
	if portNum, err := strconv.Atoi(port); err != nil {
		return fmt.Errorf("invalid port number: %v", err)
	} else if portNum <= 0 || portNum > 65535 {
		return fmt.Errorf("port number must be between 1 and 65535, got %d", portNum)
	}

	return nil
}

// runTraceroute performs a single traceroute request
func runTraceroute(client pb.AnycastServiceClient, source, destination string) error {
	// Create the request with the same format as the Python client
	command := fmt.Sprintf("volta %s %s", source, destination)
	request := &pb.Request{
		Command: command,
	}

	// Set a shorter timeout for individual requests to match Python client behavior
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Send the request
	response, err := client.UserRequest(ctx, request)
	if err != nil {
		// Handle gRPC errors with more detail, similar to Python client
		if st, ok := status.FromError(err); ok {
			return fmt.Errorf("gRPC error: %s - %s", st.Code(), st.Message())
		}
		return fmt.Errorf("gRPC error: %v", err)
	}

	// Handle the response
	if response.Code == 200 {
		fmt.Println("Traceroute completed successfully:")
		fmt.Println(response.Output)
	} else {
		fmt.Printf("Error (code %d):\n", response.Code)
		fmt.Println(response.Output)
	}

	return nil
}

// run executes the traceroute measurements
func run(config *Config) error {
	fmt.Printf("Connecting to Voltadomar controller at %s...\n", config.Controller)

	// Create gRPC connection without blocking - let individual requests handle connection errors
	conn, err := grpc.NewClient(config.Controller, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return fmt.Errorf("failed to create gRPC client: %v", err)
	}
	defer conn.Close()

	// Create gRPC client
	client := pb.NewAnycastServiceClient(conn)

	// Execute the specified number of runs
	for i := 0; i < config.Runs; i++ {
		fmt.Printf("\n--- Traceroute %d/%d ---\n", i+1, config.Runs)
		fmt.Printf("Running: volta %s %s\n", config.Source, config.Destination)

		if err := runTraceroute(client, config.Source, config.Destination); err != nil {
			fmt.Printf("%v\n", err)
			// Continue with remaining runs even if one fails, like Python client
		}
	}

	return nil
}

func main() {
	// Parse command-line arguments
	config, err := parseArgs()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}

	// Print configuration
	fmt.Println("Voltadomar Traceroute Client")
	fmt.Printf("Source: %s\n", config.Source)
	fmt.Printf("Destination: %s\n", config.Destination)
	fmt.Printf("Runs: %d\n", config.Runs)
	fmt.Printf("Controller: %s\n", config.Controller)

	// Run the traceroute measurements
	if err := run(config); err != nil {
		log.Fatalf("Failed to run traceroute: %v", err)
	}
}
