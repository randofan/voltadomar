package controller

import (
	"testing"

	pb "github.com/randofan/voltadomar/proto/anycast"
)

func TestNewController(t *testing.T) {
	controller, err := NewController(50051, 1000, 2000, 100)
	if err != nil {
		t.Fatalf("unexpected error creating controller: %v", err)
	}

	if controller.port != 50051 {
		t.Errorf("expected port 50051, got %d", controller.port)
	}

	if controller.startID != 1000 {
		t.Errorf("expected startID 1000, got %d", controller.startID)
	}

	if controller.endID != 2000 {
		t.Errorf("expected endID 2000, got %d", controller.endID)
	}

	if controller.blockSize != 100 {
		t.Errorf("expected blockSize 100, got %d", controller.blockSize)
	}

	if controller.nextSessionID != 1000 {
		t.Errorf("expected nextSessionID 1000, got %d", controller.nextSessionID)
	}
}

func TestNewControllerValidation(t *testing.T) {
	tests := []struct {
		name      string
		port      int
		startID   int32
		endID     int32
		blockSize int32
		wantError bool
	}{
		{"valid parameters", 50051, 1000, 2000, 100, false},
		{"invalid port - zero", 0, 1000, 2000, 100, true},
		{"invalid port - negative", -1, 1000, 2000, 100, true},
		{"invalid port - too large", 70000, 1000, 2000, 100, true},
		{"invalid startID - negative", 50051, -1, 2000, 100, true},
		{"invalid endID - less than startID", 50051, 2000, 1000, 100, true},
		{"invalid endID - equal to startID", 50051, 1000, 1000, 100, true},
		{"invalid blockSize - zero", 50051, 1000, 2000, 0, true},
		{"invalid blockSize - negative", 50051, 1000, 2000, -1, true},
		{"invalid blockSize - larger than range", 50051, 1000, 1050, 100, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			controller, err := NewController(tt.port, tt.startID, tt.endID, tt.blockSize)

			if tt.wantError {
				if err == nil {
					t.Errorf("expected error but got none")
				}
				if controller != nil {
					t.Errorf("expected nil controller on error")
				}
			} else {
				if err != nil {
					t.Errorf("unexpected error: %v", err)
				}
				if controller == nil {
					t.Errorf("expected non-nil controller")
				}
			}
		})
	}
}

func TestAllocateSessionID(t *testing.T) {
	controller, err := NewController(50051, 1000, 1300, 100)
	if err != nil {
		t.Fatalf("unexpected error creating controller: %v", err)
	}

	// Test first allocation
	sessionID1, err := controller.AllocateSessionID()
	if err != nil {
		t.Errorf("unexpected error: %v", err)
	}
	if sessionID1 != 1000 {
		t.Errorf("expected first session ID 1000, got %d", sessionID1)
	}

	// Test second allocation
	sessionID2, err := controller.AllocateSessionID()
	if err != nil {
		t.Errorf("unexpected error: %v", err)
	}
	if sessionID2 != 1100 {
		t.Errorf("expected second session ID 1100, got %d", sessionID2)
	}

	// Test third allocation
	sessionID3, err := controller.AllocateSessionID()
	if err != nil {
		t.Errorf("unexpected error: %v", err)
	}
	if sessionID3 != 1200 {
		t.Errorf("expected third session ID 1200, got %d", sessionID3)
	}

	// Test fourth allocation (should wrap around or fail)
	sessionID4, err := controller.AllocateSessionID()
	if err == nil {
		// If it succeeds, it should wrap around to 1000 (but 1000 is in use)
		// So it should fail or find another slot
		t.Logf("Fourth allocation returned %d", sessionID4)
	} else {
		// Expected to fail since all blocks are in use
		t.Logf("Fourth allocation failed as expected: %v", err)
	}
}

func TestReleaseSessionID(t *testing.T) {
	controller, err := NewController(50051, 1000, 1300, 100)
	if err != nil {
		t.Fatalf("unexpected error creating controller: %v", err)
	}

	// Allocate a session ID
	sessionID, err := controller.AllocateSessionID()
	if err != nil {
		t.Errorf("unexpected error: %v", err)
	}

	// Release it
	controller.ReleaseSessionID(sessionID)

	// Should be able to allocate another ID (may not be the same one immediately)
	sessionID2, err := controller.AllocateSessionID()
	if err != nil {
		t.Errorf("unexpected error after release: %v", err)
	}

	// The new session ID should be valid (either reused or next available)
	if sessionID2 < controller.startID || sessionID2 >= controller.endID {
		t.Errorf("allocated session ID %d is outside valid range %d-%d", sessionID2, controller.startID, controller.endID)
	}
}

func TestSendJobNoAgent(t *testing.T) {
	controller, err := NewController(50051, 1000, 2000, 100)
	if err != nil {
		t.Fatalf("unexpected error creating controller: %v", err)
	}

	jobPayload := &pb.Job{
		SessionId: 1000,
		DstIp:     "8.8.8.8",
		MaxTtl:    20,
		ProbeNum:  3,
		BasePort:  1000,
	}

	sendErr := controller.SendJob("nonexistent-agent", jobPayload)
	if sendErr == nil {
		t.Errorf("expected error when sending job to nonexistent agent")
	}
}

// Mock implementation for testing
type mockControllerInterface struct {
	sentJobs []mockJob
}

type mockJob struct {
	agentID    string
	jobPayload *pb.Job
}

func (m *mockControllerInterface) SendJob(agentID string, jobPayload *pb.Job) error {
	m.sentJobs = append(m.sentJobs, mockJob{
		agentID:    agentID,
		jobPayload: jobPayload,
	})
	return nil
}

func TestTracerouteCreation(t *testing.T) {
	mockController := &mockControllerInterface{}

	conf := &TracerouteConf{
		SourceHost:      "agent1",
		DestinationHost: "localhost", // Should resolve to 127.0.0.1
		MaxTTL:          5,
		ProbeNum:        2,
		Timeout:         10,
		StartID:         1000,
	}

	traceroute, err := NewTraceroute(mockController, conf)
	if err != nil {
		t.Errorf("unexpected error creating traceroute: %v", err)
	}

	if traceroute.sessionID != 1000 {
		t.Errorf("expected session ID 1000, got %d", traceroute.sessionID)
	}

	if traceroute.destinationIP != "127.0.0.1" {
		t.Errorf("expected destination IP 127.0.0.1, got %s", traceroute.destinationIP)
	}

	expectedResults := conf.MaxTTL * conf.ProbeNum
	if len(traceroute.results) != expectedResults {
		t.Errorf("expected %d results, got %d", expectedResults, len(traceroute.results))
	}

	// Check that all results are initialized as timeouts
	for i, result := range traceroute.results {
		if !result.Timeout {
			t.Errorf("expected result %d to be timeout, but it wasn't", i)
		}
		if result.Seq != i {
			t.Errorf("expected result %d to have seq %d, got %d", i, i, result.Seq)
		}
	}
}

func TestParseTracerouteArgs(t *testing.T) {
	tests := []struct {
		name        string
		command     string
		expectError bool
		expected    *TracerouteConf
	}{
		{
			name:        "basic command",
			command:     "volta agent1 8.8.8.8",
			expectError: false,
			expected: &TracerouteConf{
				SourceHost:      "agent1",
				DestinationHost: "8.8.8.8",
				MaxTTL:          20,
				ProbeNum:        3,
				Timeout:         5,
				TOS:             1,
			},
		},
		{
			name:        "command with options",
			command:     "volta agent1 8.8.8.8 -m 10 -q 5 -w 3",
			expectError: false,
			expected: &TracerouteConf{
				SourceHost:      "agent1",
				DestinationHost: "8.8.8.8",
				MaxTTL:          10,
				ProbeNum:        5,
				Timeout:         3,
				TOS:             1,
			},
		},
		{
			name:        "insufficient arguments",
			command:     "volta agent1",
			expectError: true,
		},
		{
			name:        "empty command",
			command:     "",
			expectError: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			conf, err := ParseTracerouteArgs(tt.command)

			if tt.expectError {
				if err == nil {
					t.Errorf("expected error but got none")
				}
				return
			}

			if err != nil {
				t.Errorf("unexpected error: %v", err)
				return
			}

			if conf.SourceHost != tt.expected.SourceHost {
				t.Errorf("expected source host %s, got %s", tt.expected.SourceHost, conf.SourceHost)
			}

			if conf.DestinationHost != tt.expected.DestinationHost {
				t.Errorf("expected destination host %s, got %s", tt.expected.DestinationHost, conf.DestinationHost)
			}

			if conf.MaxTTL != tt.expected.MaxTTL {
				t.Errorf("expected max TTL %d, got %d", tt.expected.MaxTTL, conf.MaxTTL)
			}

			if conf.ProbeNum != tt.expected.ProbeNum {
				t.Errorf("expected probe num %d, got %d", tt.expected.ProbeNum, conf.ProbeNum)
			}

			if conf.Timeout != tt.expected.Timeout {
				t.Errorf("expected timeout %d, got %d", tt.expected.Timeout, conf.Timeout)
			}
		})
	}
}

func TestTracerouteSeqToPort(t *testing.T) {
	mockController := &mockControllerInterface{}

	conf := &TracerouteConf{
		SourceHost:      "agent1",
		DestinationHost: "localhost",
		StartID:         1000,
	}

	traceroute, err := NewTraceroute(mockController, conf)
	if err != nil {
		t.Errorf("unexpected error creating traceroute: %v", err)
	}

	tests := []struct {
		seq      int
		expected int32
	}{
		{0, 1000},
		{1, 1001},
		{10, 1010},
		{100, 1100},
	}

	for _, tt := range tests {
		result := traceroute.seqToPort(tt.seq)
		if result != tt.expected {
			t.Errorf("seqToPort(%d) = %d, expected %d", tt.seq, result, tt.expected)
		}
	}
}
