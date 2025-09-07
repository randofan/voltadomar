// Package constants defines constants used throughout the application
package constants

import (
	"strings"
	"time"
)

// Message type URLs for gRPC communication (used with google.protobuf.Any)
const (
	MsgTypeReply    = "type.googleapis.com/Reply"
	MsgTypeError    = "type.googleapis.com/Error"
	MsgTypeJob      = "type.googleapis.com/Job"
	MsgTypeDone     = "type.googleapis.com/Done"
	MsgTypeRegister = "type.googleapis.com/Register"
	MsgTypeCancel   = "type.googleapis.com/Cancel"
)

// Socket types
const (
	SocketUDP  = "udp"
	SocketICMP = "icmp"
)

// Default configuration values
const (
	// Worker pool configuration
	DefaultSenderWorkers   = 3
	DefaultListenerWorkers = 3
	WorkerJobChannelSize   = 100

	// Network configuration
	DefaultControllerPort = 50051
	MaxPacketSize         = 1500 // Standard MTU
	ICMPPayloadSize       = 40   // Bytes

	// Timing configuration
	ProbeDelay        = 10 * time.Millisecond
	SocketReadTimeout = 1 * time.Second
	DefaultJobTimeout = 30 * time.Second

	// Traceroute defaults
	DefaultMaxTTL   = 20
	DefaultProbeNum = 3
	DefaultTimeout  = 5 // seconds
	DefaultTOS      = 1
)

// Network protocol numbers
const (
	ProtocolICMP = 1
	ProtocolUDP  = 17
)

// GetMessageTypeFromURL extracts the message type from a protobuf Any TypeUrl
// Example: "type.googleapis.com/Register" -> "Register"
func GetMessageTypeFromURL(typeURL string) string {
	parts := strings.Split(typeURL, "/")
	if len(parts) > 0 {
		return parts[len(parts)-1]
	}
	return typeURL
}
