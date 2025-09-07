# Voltadomar Integration Tests

This directory contains automated tests for the Voltadomar distributed network measurement system.

## Files

- **`smoke_test.py`** - Main automated smoke test script
- **`test_failure_detection.py`** - Verification script to test failure detection
- **`README.md`** - This file

## Quick Start

### Prerequisites
- Go 1.21+
- Python 3.7+
- Built Voltadomar binaries (`controller-binary`, `agent-binary`)
- Network connectivity to test targets

### Running Tests

```bash
# Run the main smoke test
python3 integration-tests/smoke_test.py

# Test failure detection capability
python3 integration-tests/test_failure_detection.py
```

### Expected Results

**Smoke Test Success:**
```
✅ SMOKE TEST PASSED
No breaking changes detected in the codebase.
```

**Smoke Test Failure:**
```
❌ SMOKE TEST FAILED
Breaking changes detected or system malfunction.
Check smoke_test.log for detailed information.
```

## Test Coverage

The smoke test verifies:

1. **Environment Setup**
   - Go version compatibility
   - Binary existence and executability
   - Port availability (50051)
   - Network connectivity

2. **Component Startup**
   - Controller initialization
   - Agent connection and registration
   - gRPC communication establishment

3. **Basic Functionality**
   - Traceroute request processing
   - UDP probe transmission
   - Response format validation

4. **Resource Cleanup**
   - Process termination
   - Port release
   - Temporary resource cleanup

## Configuration

Key test parameters (in `smoke_test.py`):

```python
self.controller_port = 50051        # gRPC port
self.session_range = "10000-20000"  # Session ID range
self.block_size = 100               # Session block size
self.agent_id = "smoke-test-agent"  # Test agent identifier
self.test_target = "8.8.8.8"        # Traceroute target
```

## Troubleshooting

**Port conflicts:**
```bash
# Kill processes using port 50051
lsof -ti:50051 | xargs kill -9
```

**Missing binaries:**
```bash
# Build binaries
cd src/voltadomar
go build -o controller-binary ./cmd/controller
go build -o agent-binary ./cmd/agent
```

**Python dependencies:**
```bash
# Install gRPC libraries
pip3 install grpcio grpcio-tools
```

## Development

### Adding New Tests
1. Follow the existing pattern in `smoke_test.py`
2. Add proper error handling and cleanup
3. Update documentation
4. Test both success and failure scenarios

### Test Maintenance
- Keep execution time under 2 minutes
- Ensure tests are deterministic
- Handle network timeouts gracefully
- Maintain compatibility with CI/CD systems

For detailed documentation, see [Testing Guide](../docs/testing.md).
