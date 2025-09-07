# Voltadomar Testing Guide

This document describes the testing infrastructure for the Voltadomar distributed network measurement system.

## Automated Smoke Test

### Overview

The automated smoke test (`integration-tests/smoke_test.py`) provides basic functionality verification to detect breaking changes in the codebase. It performs end-to-end testing of the controller-agent communication, gRPC protocol, and basic traceroute functionality.

**Purpose:** Detect breaking changes in core functionality  
**Scope:** Basic functionality verification (not exhaustive testing)  
**Duration:** ~30-60 seconds  
**Dependencies:** Python 3.7+, Go 1.21+, network connectivity

### Prerequisites

#### System Requirements
```bash
# Go 1.21 or higher
go version

# Python 3.7 or higher
python3 --version

# Network connectivity for test targets
ping -c 1 8.8.8.8
```

#### Port Requirements
- Port 50051 must be available for gRPC communication
- No other Voltadomar instances should be running

#### File Structure
```
voltadomar/
├── src/voltadomar/
│   ├── controller-binary    # Built controller executable
│   ├── agent-binary        # Built agent executable
│   └── ...
├── examples/
│   └── client.py           # Python gRPC client
├── integration-tests/
│   ├── smoke_test.py       # Main smoke test script
│   └── test_failure_detection.py
└── docs/
    └── testing.md          # This file
```

### Running the Smoke Test

#### Basic Usage
```bash
# From project root
cd voltadomar
python3 integration-tests/smoke_test.py
```

#### Expected Output (Success)
```
============================================================
Voltadomar Automated Smoke Test
============================================================
2025-09-06 17:18:47,364 - INFO - Starting Voltadomar smoke test...
2025-09-06 17:18:47,369 - INFO - Validating environment...
2025-09-06 17:18:47,375 - INFO - Go version: go version go1.25.0 darwin/arm64
2025-09-06 17:18:47,389 - INFO - Environment validation passed
2025-09-06 17:18:47,389 - INFO - Starting Controller: [...]
2025-09-06 17:18:47,390 - INFO - Controller started with PID 36781
2025-09-06 17:18:47,896 - INFO - Controller is ready
2025-09-06 17:18:49,902 - INFO - Starting Agent: [...]
2025-09-06 17:18:49,908 - INFO - Agent started with PID 36784
2025-09-06 17:18:58,189 - INFO - Agent registered successfully
2025-09-06 17:19:00,193 - INFO - Testing basic traceroute functionality...
2025-09-06 17:19:00,194 - INFO - Running traceroute test: [...]
2025-09-06 17:19:05,357 - INFO - Traceroute test completed successfully
2025-09-06 17:19:05,357 - INFO - Smoke test completed successfully!
[cleanup messages...]

✅ SMOKE TEST PASSED
No breaking changes detected in the codebase.
```

#### Expected Output (Failure)
```
============================================================
Voltadomar Automated Smoke Test
============================================================
[test execution logs...]
2025-09-06 17:20:15,123 - ERROR - Smoke test failed: Controller failed to start properly
[cleanup messages...]

❌ SMOKE TEST FAILED
Breaking changes detected or system malfunction.
Check smoke_test.log for detailed information.
```

### Test Components

#### 1. Environment Validation
- Checks Go version (requires 1.21+)
- Verifies binary existence and executability
- Tests port availability (50051)
- Validates network connectivity to test target (8.8.8.8)

#### 2. Component Startup
- Starts controller with test configuration:
  - Port: 50051
  - Session range: 10000-20000
  - Block size: 100
- Starts agent with test ID: `smoke-test-agent`
- Verifies agent registration with controller

#### 3. Functionality Test
- Sends single traceroute request to 8.8.8.8
- Validates response format and content
- Verifies complete request-response cycle

#### 4. Cleanup and Validation
- Gracefully terminates all processes
- Verifies port release
- Cleans up temporary resources

### Success Criteria

The smoke test **PASSES** if:
- ✅ All environment prerequisites are met
- ✅ Controller starts and accepts connections
- ✅ Agent registers successfully with controller
- ✅ Traceroute request completes without errors
- ✅ Response contains expected format and content
- ✅ All processes terminate cleanly
- ✅ Resources are properly cleaned up

The smoke test **FAILS** if:
- ❌ Environment validation fails
- ❌ Controller or agent fails to start
- ❌ Agent registration fails
- ❌ Traceroute request fails or times out
- ❌ Response format is invalid
- ❌ Processes don't terminate properly
- ❌ Resource cleanup fails

### Logging and Debugging

#### Log Files
- `smoke_test.log` - Detailed test execution log
- Console output - Summary and real-time progress

#### Debug Information
```bash
# View detailed logs
cat smoke_test.log

# Check for specific errors
grep -i error smoke_test.log
grep -i failed smoke_test.log

# Monitor system resources during test
ps aux | grep -E "(controller|agent)-binary"
netstat -tlnp | grep :50051
```

### Troubleshooting

#### Common Issues

**Issue: Port 50051 already in use**
```bash
# Find process using the port
lsof -ti:50051 | xargs kill -9

# Or use alternative port (modify smoke_test.py)
# Change self.controller_port = 50052
```

**Issue: Go not found or wrong version**
```bash
# Install Go 1.21+
# macOS: brew install go
# Linux: Download from https://golang.org/dl/

# Verify installation
go version
```

**Issue: Python gRPC libraries missing**
```bash
# Install required libraries
pip3 install grpcio grpcio-tools

# Verify installation
python3 -c "import grpc; print('gRPC available')"
```

**Issue: Binaries not found**
```bash
# Build binaries
cd src/voltadomar
go build -o controller-binary ./cmd/controller
go build -o agent-binary ./cmd/agent

# Verify binaries exist and are executable
ls -la *-binary
```

**Issue: Network connectivity problems**
```bash
# Test connectivity to target
ping -c 3 8.8.8.8

# Check DNS resolution
nslookup google.com

# Test with alternative target (modify smoke_test.py)
# Change self.test_target = "1.1.1.1"
```

**Issue: Permission denied for raw sockets**
```bash
# This is expected - agent runs without ICMP capture capability
# The test should still pass as it tests UDP probe functionality
# For full functionality, run agent with sudo (not recommended for testing)
```

#### Advanced Debugging

**Enable verbose logging:**
```python
# Modify smoke_test.py logging level
logging.basicConfig(level=logging.DEBUG, ...)
```

**Manual component testing:**
```bash
# Test controller manually
./src/voltadomar/controller-binary --port 50052 --range 10000-20000 --block 100

# Test agent manually (in another terminal)
./src/voltadomar/agent-binary -i test-agent -c localhost:50052

# Test client manually (in another terminal)
python3 examples/client.py test-agent 8.8.8.8 1 --controller localhost:50052
```

**Process monitoring:**
```bash
# Monitor processes during test
watch 'ps aux | grep -E "(controller|agent)-binary"'

# Monitor network connections
watch 'netstat -tlnp | grep :50051'

# Monitor system resources
top -p $(pgrep -f "controller-binary\|agent-binary")
```

### Integration with CI/CD

#### GitHub Actions Example
```yaml
name: Smoke Test
on: [push, pull_request]

jobs:
  smoke-test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-go@v3
      with:
        go-version: '1.21'
    - uses: actions/setup-python@v3
      with:
        python-version: '3.9'

    - name: Install dependencies
      run: |
        pip install grpcio grpcio-tools

    - name: Build binaries
      run: |
        cd src/voltadomar
        go build -o controller-binary ./cmd/controller
        go build -o agent-binary ./cmd/agent

    - name: Run smoke test
      run: python3 integration-tests/smoke_test.py
```

#### Pre-commit Hook
```bash
#!/bin/bash
# .git/hooks/pre-commit
echo "Running Voltadomar smoke test..."
python3 integration-tests/smoke_test.py
if [ $? -ne 0 ]; then
    echo "Smoke test failed. Commit aborted."
    exit 1
fi
echo "Smoke test passed."
```

### Test Development Guidelines

#### Adding New Test Cases
1. Keep tests focused on basic functionality
2. Ensure tests are deterministic and repeatable
3. Add proper error handling and cleanup
4. Update documentation when adding new test scenarios

#### Test Maintenance
- Review test reliability regularly
- Update test targets if network endpoints change
- Adjust timeouts based on system performance
- Keep test execution time under 2 minutes

### Related Documentation
- [API Reference](api.md) - Complete API documentation
- [README.md](../README.md) - Project overview and setup
