#!/usr/bin/env python3
"""
Test script to verify that the smoke test can detect breaking changes.
This script temporarily modifies the controller binary to simulate a failure.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

def test_failure_detection():
    """Test that smoke test can detect breaking changes"""
    project_root = Path(__file__).parent.parent
    voltadomar_dir = project_root / "src" / "voltadomar"
    controller_binary = voltadomar_dir / "controller-binary"
    backup_binary = voltadomar_dir / "controller-binary.backup"
    
    print("Testing smoke test failure detection...")
    
    try:
        # Backup the original binary
        shutil.copy2(controller_binary, backup_binary)
        print("✓ Backed up original controller binary")
        
        # Replace with a failing binary (just copy a non-executable file)
        with open(controller_binary, 'w') as f:
            f.write("#!/bin/bash\necho 'Simulated failure'\nexit 1\n")
        os.chmod(controller_binary, 0o755)
        print("✓ Created failing controller binary")
        
        # Run smoke test - should fail
        result = subprocess.run([
            'python3', 'integration-tests/smoke_test.py'
        ], cwd=project_root, capture_output=True, text=True)
        
        if result.returncode != 0:
            print("✅ SUCCESS: Smoke test correctly detected the failure")
            print("Return code:", result.returncode)
            return True
        else:
            print("❌ FAILURE: Smoke test did not detect the breaking change")
            print("Output:", result.stdout)
            return False
            
    finally:
        # Restore original binary
        if backup_binary.exists():
            shutil.move(backup_binary, controller_binary)
            print("✓ Restored original controller binary")
    
    return False

if __name__ == "__main__":
    success = test_failure_detection()
    sys.exit(0 if success else 1)
