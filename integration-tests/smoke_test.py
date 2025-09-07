#!/usr/bin/env python3
"""
Voltadomar Automated Smoke Test

This script performs basic functionality verification to detect breaking changes
in the Voltadomar distributed network measurement system.

Purpose: Verify controller-agent communication, gRPC protocol, and basic traceroute functionality
Scope: Basic functionality only (not exhaustive testing)
"""

import os
import sys
import time
import socket
import subprocess
import threading
import signal
import logging
from pathlib import Path
from typing import Optional, Tuple, List
import tempfile
import shutil

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('smoke_test.log')
    ]
)
logger = logging.getLogger(__name__)

class SmokeTestError(Exception):
    """Custom exception for smoke test failures"""
    pass

class ProcessManager:
    """Manages subprocess lifecycle with proper cleanup"""
    
    def __init__(self):
        self.processes: List[subprocess.Popen] = []
        self.temp_dirs: List[str] = []
        
    def start_process(self, cmd: List[str], cwd: str, name: str, 
                     capture_output: bool = True) -> subprocess.Popen:
        """Start a subprocess with proper error handling"""
        logger.info(f"Starting {name}: {' '.join(cmd)}")
        
        try:
            if capture_output:
                process = subprocess.Popen(
                    cmd, 
                    cwd=cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    universal_newlines=True,
                    bufsize=1
                )
            else:
                process = subprocess.Popen(cmd, cwd=cwd)
                
            self.processes.append(process)
            logger.info(f"{name} started with PID {process.pid}")
            return process
            
        except Exception as e:
            raise SmokeTestError(f"Failed to start {name}: {e}")
    
    def cleanup(self):
        """Cleanup all processes and temporary resources"""
        logger.info("Starting cleanup...")
        
        # Terminate processes gracefully
        for process in self.processes:
            if process.poll() is None:  # Process is still running
                logger.info(f"Terminating process {process.pid}")
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"Force killing process {process.pid}")
                    process.kill()
                    process.wait()
                except Exception as e:
                    logger.error(f"Error terminating process {process.pid}: {e}")
        
        # Clean up temporary directories
        for temp_dir in self.temp_dirs:
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.error(f"Error removing temp dir {temp_dir}: {e}")
        
        logger.info("Cleanup completed")

class VoltadomarSmokeTest:
    """Main smoke test class"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.voltadomar_dir = self.project_root / "src" / "voltadomar"
        self.controller_binary = self.voltadomar_dir / "controller-binary"
        self.agent_binary = self.voltadomar_dir / "agent-binary"
        self.process_manager = ProcessManager()
        
        # Test configuration
        self.controller_port = 50051
        self.session_range = "10000-20000"
        self.block_size = 100
        self.agent_id = "smoke-test-agent"
        self.test_target = "8.8.8.8"
        
    def validate_environment(self):
        """Validate environment prerequisites"""
        logger.info("Validating environment...")
        
        # Check Go version
        try:
            result = subprocess.run(['go', 'version'], capture_output=True, text=True)
            if result.returncode != 0:
                raise SmokeTestError("Go is not installed or not in PATH")
            logger.info(f"Go version: {result.stdout.strip()}")
        except FileNotFoundError:
            raise SmokeTestError("Go is not installed or not in PATH")
        
        # Check binary existence
        if not self.controller_binary.exists():
            raise SmokeTestError(f"Controller binary not found: {self.controller_binary}")
        if not self.agent_binary.exists():
            raise SmokeTestError(f"Agent binary not found: {self.agent_binary}")
            
        # Make binaries executable
        os.chmod(self.controller_binary, 0o755)
        os.chmod(self.agent_binary, 0o755)
        
        # Check port availability
        if not self._is_port_available(self.controller_port):
            raise SmokeTestError(f"Port {self.controller_port} is not available")
            
        # Test network connectivity
        if not self._test_connectivity(self.test_target):
            logger.warning(f"Cannot reach test target {self.test_target}, test may fail")
            
        logger.info("Environment validation passed")
    
    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return True
        except OSError:
            return False
    
    def _test_connectivity(self, target: str) -> bool:
        """Test basic network connectivity"""
        try:
            result = subprocess.run(['ping', '-c', '1', target],
                                  capture_output=True, timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def start_controller(self) -> subprocess.Popen:
        """Start the controller process"""
        cmd = [
            str(self.controller_binary),
            '--port', str(self.controller_port),
            '--range', self.session_range,
            '--block', str(self.block_size)
        ]

        process = self.process_manager.start_process(
            cmd, str(self.voltadomar_dir), "Controller"
        )

        # Wait for controller to start
        if not self._wait_for_controller_startup(process):
            raise SmokeTestError("Controller failed to start properly")

        return process

    def _wait_for_controller_startup(self, process: subprocess.Popen, timeout: int = 10) -> bool:
        """Wait for controller to start and be ready"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if process.poll() is not None:
                # Process has terminated
                stdout, _ = process.communicate()
                logger.error(f"Controller process terminated: {stdout}")
                return False

            # Check if controller is listening on port
            if self._is_controller_ready():
                logger.info("Controller is ready")
                return True

            time.sleep(0.5)

        logger.error("Controller startup timeout")
        return False

    def _is_controller_ready(self) -> bool:
        """Check if controller is ready to accept connections"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('localhost', self.controller_port))
                return result == 0
        except Exception:
            return False

    def start_agent(self) -> subprocess.Popen:
        """Start the agent process"""
        cmd = [
            str(self.agent_binary),
            '-i', self.agent_id,
            '-c', f'localhost:{self.controller_port}'
        ]

        process = self.process_manager.start_process(
            cmd, str(self.voltadomar_dir), "Agent"
        )

        # Wait for agent registration
        if not self._wait_for_agent_registration(process):
            raise SmokeTestError("Agent failed to register with controller")

        return process

    def _wait_for_agent_registration(self, process: subprocess.Popen, timeout: int = 10) -> bool:
        """Wait for agent to register with controller"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if process.poll() is not None:
                # Process has terminated
                stdout, _ = process.communicate()
                logger.error(f"Agent process terminated: {stdout}")
                return False

            # Read agent output to check for registration
            try:
                # Non-blocking read
                line = process.stdout.readline()
                if line and "started successfully" in line.lower():
                    logger.info("Agent registered successfully")
                    return True
            except Exception:
                pass

            time.sleep(0.5)

        logger.error("Agent registration timeout")
        return False

    def test_basic_traceroute(self) -> bool:
        """Test basic traceroute functionality using gRPC client"""
        logger.info("Testing basic traceroute functionality...")

        # Use the existing Python client
        client_script = self.project_root / "examples" / "client.py"
        if not client_script.exists():
            logger.error(f"Client script not found: {client_script}")
            return False

        cmd = [
            'python3', str(client_script),
            self.agent_id,
            self.test_target,
            '1',  # Single run
            '--controller', f'localhost:{self.controller_port}'
        ]

        try:
            logger.info(f"Running traceroute test: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info("Traceroute test completed successfully")
                logger.debug(f"Traceroute output: {result.stdout}")

                # Basic validation of output format
                if self._validate_traceroute_output(result.stdout):
                    return True
                else:
                    logger.error("Traceroute output validation failed")
                    return False
            else:
                logger.error(f"Traceroute test failed with return code {result.returncode}")
                logger.error(f"Error output: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Traceroute test timed out")
            return False
        except Exception as e:
            logger.error(f"Traceroute test error: {e}")
            return False

    def _validate_traceroute_output(self, output: str) -> bool:
        """Validate traceroute output format"""
        required_patterns = [
            "Voltadomar Traceroute Client",
            f"Source: {self.agent_id}",
            f"Destination: {self.test_target}",
            "Traceroute completed successfully"
        ]

        for pattern in required_patterns:
            if pattern not in output:
                logger.error(f"Missing required pattern in output: {pattern}")
                return False

        return True

    def run_smoke_test(self) -> bool:
        """Run the complete smoke test"""
        logger.info("Starting Voltadomar smoke test...")

        try:
            # Step 1: Validate environment
            self.validate_environment()

            # Step 2: Start controller
            controller_process = self.start_controller()
            time.sleep(2)  # Give controller time to fully initialize

            # Step 3: Start agent
            agent_process = self.start_agent()
            time.sleep(2)  # Give agent time to register

            # Step 4: Test basic functionality
            if not self.test_basic_traceroute():
                return False

            logger.info("Smoke test completed successfully!")
            return True

        except SmokeTestError as e:
            logger.error(f"Smoke test failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during smoke test: {e}")
            return False
        finally:
            # Always cleanup
            self.process_manager.cleanup()

            # Verify port is released
            time.sleep(1)
            if self._is_port_available(self.controller_port):
                logger.info("Port cleanup verified")
            else:
                logger.warning(f"Port {self.controller_port} may still be in use")

def main():
    """Main entry point"""
    print("=" * 60)
    print("Voltadomar Automated Smoke Test")
    print("=" * 60)

    # Handle Ctrl+C gracefully
    def signal_handler(signum, frame):
        logger.info("Received interrupt signal, cleaning up...")
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    test = VoltadomarSmokeTest()
    success = test.run_smoke_test()

    if success:
        print("\n✅ SMOKE TEST PASSED")
        print("No breaking changes detected in the codebase.")
        sys.exit(0)
    else:
        print("\n❌ SMOKE TEST FAILED")
        print("Breaking changes detected or system malfunction.")
        print("Check smoke_test.log for detailed information.")
        sys.exit(1)

if __name__ == "__main__":
    main()
