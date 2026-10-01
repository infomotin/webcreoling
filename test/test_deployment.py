#!/usr/bin/env python3
"""
Deployment Solution Test Suite

This test suite verifies the deployment solution functionality
and components.
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

def test_file_structure() -> bool:
    """Test if required files exist."""
    print("Testing file structure...")
    
    required_files = [
        'deployment.sh',
        'bin/deployer.py',
        'bin/webcreoling_deployer.py',
        'DEPLOYMENT.md',
        'lib/deployment_logger.py',
        'lib/version_manager.py',
        'lib/system_validator.py',
        'lib/database_initializer.py',
        'lib/application_deployer.py',
        'lib/security_manager.py',
    ]
    
    missing_files = []
    for file_path in required_files:
        if not Path(file_path).exists():
            missing_files.append(file_path)
    
    if missing_files:
        print(f"  ✗ Missing files: {missing_files}")
        return False
    
    print(f"  ✓ All {len(required_files)} required files exist")
    return True

def test_executable_files() -> bool:
    """Test if executable files are executable."""
    print("Testing executable permissions...")
    
    executable_files = [
        'deployment.sh',
        'bin/deployer.py',
        'bin/webcreoling_deployer.py',
    ]
    
    non_executable = []
    for file_path in executable_files:
        if Path(file_path).exists():
            if not os.access(file_path, os.X_OK):
                non_executable.append(file_path)
    
    if non_executable:
        print(f"  ✗ Non-executable files: {non_executable}")
        return False
    
    print(f"  ✓ All {len(executable_files)} executable files are executable")
    return True

def test_python_syntax() -> bool:
    """Test if Python files have valid syntax."""
    print("Testing Python syntax...")
    
    python_files = list(Path('.').rglob('*.py'))
    python_files = [f for f in python_files if not str(f).startswith('test_')]
    
    invalid_syntax = []
    for file_path in python_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                compile(f.read(), str(file_path), 'exec')
        except SyntaxError as e:
            invalid_syntax.append(f"{file_path}: {e}")
    
    if invalid_syntax:
        print(f"  ✗ Files with invalid syntax: {len(invalid_syntax)}")
        for error in invalid_syntax[:3]:  # Show first 3 errors
            print(f"    {error}")
        return False
    
    print(f"  ✓ All {len(python_files)} Python files have valid syntax")
    return True

def test_documentation() -> bool:
    """Test if documentation files exist."""
    print("Testing documentation...")
    
    doc_files = [
        'DEPLOYMENT.md',
        'docs/DEPLOYMENT.md',
    ]
    
    missing_docs = []
    for doc_path in doc_files:
        if not Path(doc_path).exists():
            missing_docs.append(doc_path)
    
    if missing_docs:
        print(f"  ✗ Missing documentation files: {missing_docs}")
        return False
    
    print(f"  ✓ All documentation files exist")
    return True

def test_examples() -> bool:
    """Test if example files exist."""
    print("Testing examples...")
    
    example_files = [
        'examples/nginx.conf.example',
        'examples/systemd.service.example',
    ]
    
    missing_examples = []
    for example_path in example_files:
        if not Path(example_path).exists():
            missing_examples.append(example_path)
    
    if missing_examples:
        print(f"  ✗ Missing example files: {missing_examples}")
        return False
    
    print(f"  ✓ All example files exist")
    return True

def test_version_compatibility() -> bool:
    """Test version compatibility."""
    print("Testing version compatibility...")
    
    try:
        # Try to import deployment modules
        from bin.deployer import DeploymentOrchestrator
        from lib.deployment_logger import DeploymentLogger
        from lib.version_manager import VersionManager
        from lib.system_validator import SystemValidator
        from lib.database_initializer import DatabaseInitializer
        from lib.application_deployer import ApplicationDeployer
        from lib.security_manager import SecurityManager
        
        print("  ✓ All deployment modules import successfully")
        return True
    except ImportError as e:
        print(f"  ✗ Import error: {e}")
        return False

def run_tests() -> bool:
    """Run all tests."""
    print("=" * 70)
    print("Webcreoling Deployment Solution Test Suite")
    print("=" * 70)
    print()
    
    tests = [
        ("File Structure", test_file_structure),
        ("Executable Permissions", test_executable_files),
        ("Python Syntax", test_python_syntax),
        ("Documentation", test_documentation),
        ("Examples", test_examples),
        ("Version Compatibility", test_version_compatibility),
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"Running {test_name} test...")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"  ✗ Test failed with exception: {e}")
            results.append((test_name, False))
        print()
    
    # Summary
    print("=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{test_name:<30} - {status}")
        if result:
            passed += 1
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("✓ All tests passed!")
        return True
    else:
        print("✗ Some tests failed!")
        return False
if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
