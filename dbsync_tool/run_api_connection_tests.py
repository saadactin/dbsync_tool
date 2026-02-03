#!/usr/bin/env python
"""
Test runner for API Connection tests
Run this script to test all Day 4 API Connection features
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.test.utils import get_runner
from django.conf import settings

def run_tests():
    """Run all API connection tests"""
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=2, keepdb=True, interactive=False)
    
    # Run form tests
    print("\n" + "="*70)
    print("Running API Connection Form Tests")
    print("="*70 + "\n")
    failures = test_runner.run_tests(['connections.tests.test_api_connection_forms'])
    
    if failures:
        print(f"\n❌ Form tests failed: {failures} failures")
        return failures
    
    print("\n✅ All form tests passed!")
    
    # Run view tests
    print("\n" + "="*70)
    print("Running API Connection View Tests")
    print("="*70 + "\n")
    failures = test_runner.run_tests(['connections.tests.test_api_connection_views'])
    
    if failures:
        print(f"\n❌ View tests failed: {failures} failures")
        return failures
    
    print("\n✅ All view tests passed!")
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print("✅ Form Tests: PASSED")
    print("✅ View Tests: PASSED")
    print("\n🎉 All Day 4 API Connection tests completed successfully!")
    print("="*70 + "\n")
    
    return 0

if __name__ == '__main__':
    sys.exit(run_tests())
