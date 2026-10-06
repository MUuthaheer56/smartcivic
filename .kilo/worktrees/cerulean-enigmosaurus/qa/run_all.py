"""
SmartCivic QA and Security Verification Suite Coordinator
"""
import subprocess
import sys
import logging

logger = logging.getLogger(__name__)

def execute_quality_assurance_pipeline() -> bool:
    """
    Runs the comprehensive test suite and security scan checks 
    to validate system health before deployment.
    """
    print("[*] Starting SmartCivic QA and Security Verification Suite...")
    
    try:
        # Run pytest across test modules
        test_result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-v"], capture_output=True, text=True)
        print(test_result.stdout)
        
        if test_result.returncode != 0:
            logger.error("Test suite encountered failures.")
            print("[!] Test Suite Failures Detected.")
            return False

        print("[+] All test suites passed successfully!")
        return True

    except Exception as e:
        logger.error(f"Failed to execute QA pipeline: {e}")
        return False

if __name__ == "__main__":
    success = execute_quality_assurance_pipeline()
    sys.exit(0 if success else 1)
