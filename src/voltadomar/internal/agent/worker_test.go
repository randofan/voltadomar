package agent

import (
	"sync"
	"testing"
	"time"
)

func TestWorkerPool(t *testing.T) {
	// Test data
	var processedJobs []int
	var mu sync.Mutex

	// Worker function that records processed jobs
	workerFunc := func(job interface{}) error {
		jobID, ok := job.(int)
		if !ok {
			t.Errorf("unexpected job type")
			return nil
		}

		mu.Lock()
		processedJobs = append(processedJobs, jobID)
		mu.Unlock()

		// Simulate some work
		time.Sleep(10 * time.Millisecond)
		return nil
	}

	// Create worker pool
	wp := NewWorkerPool(3, workerFunc)

	// Start the pool
	wp.Start()

	// Add some jobs
	jobCount := 10
	for i := 0; i < jobCount; i++ {
		err := wp.AddJob(i)
		if err != nil {
			t.Errorf("failed to add job %d: %v", i, err)
		}
	}

	// Wait for jobs to be processed
	time.Sleep(200 * time.Millisecond)

	// Stop the pool
	wp.Stop()

	// Check results
	mu.Lock()
	defer mu.Unlock()

	if len(processedJobs) != jobCount {
		t.Errorf("expected %d processed jobs, got %d", jobCount, len(processedJobs))
	}

	// Check that all jobs were processed (order may vary due to concurrency)
	jobMap := make(map[int]bool)
	for _, job := range processedJobs {
		jobMap[job] = true
	}

	for i := 0; i < jobCount; i++ {
		if !jobMap[i] {
			t.Errorf("job %d was not processed", i)
		}
	}
}

func TestWorkerPoolCancellation(t *testing.T) {
	// Worker function that takes some time
	workerFunc := func(job interface{}) error {
		time.Sleep(100 * time.Millisecond)
		return nil
	}

	// Create worker pool
	wp := NewWorkerPool(2, workerFunc)

	// Start the pool
	wp.Start()

	// Add a job
	err := wp.AddJob("test-job")
	if err != nil {
		t.Errorf("failed to add job: %v", err)
	}

	// Stop the pool immediately
	start := time.Now()
	wp.Stop()
	duration := time.Since(start)

	// Should stop relatively quickly (not wait for job completion)
	if duration > 200*time.Millisecond {
		t.Errorf("worker pool took too long to stop: %v", duration)
	}
}

func TestWorkerPoolFullQueue(t *testing.T) {
	// Worker function that blocks
	workerFunc := func(job interface{}) error {
		time.Sleep(1 * time.Second)
		return nil
	}

	// Create worker pool with small buffer
	wp := NewWorkerPool(1, workerFunc)
	wp.jobChan = make(chan interface{}, 2) // Small buffer for testing

	// Start the pool
	wp.Start()
	defer wp.Stop()

	// Fill the queue
	for i := 0; i < 2; i++ {
		err := wp.AddJob(i)
		if err != nil {
			t.Errorf("failed to add job %d: %v", i, err)
		}
	}

	// Try to add one more job (should fail or block)
	err := wp.AddJob("overflow")
	if err == nil {
		t.Errorf("expected error when queue is full")
	}
}
