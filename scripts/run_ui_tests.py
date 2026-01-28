#!/usr/bin/env python
"""
Test execution script for UI tests
Runs all UI tests and generates a comprehensive report
"""
import os
import sys
import django
from io import StringIO
from datetime import datetime
import json

# Setup Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'dbsync_tool'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings')
django.setup()

from django.test.utils import get_runner
from django.conf import settings
from django.test import TestCase
import traceback


class TestResultCollector:
    """Collects test results for reporting"""
    
    def __init__(self):
        self.results = {
            'test_suites': {},
            'summary': {
                'total_tests': 0,
                'passed': 0,
                'failed': 0,
                'errors': 0,
                'skipped': 0,
                'start_time': None,
                'end_time': None,
            },
            'test_details': []
        }
    
    def add_test_result(self, test_name, status, error_msg=None, traceback_str=None):
        """Add a test result"""
        suite_name = test_name.split('.')[0]
        if suite_name not in self.results['test_suites']:
            self.results['test_suites'][suite_name] = {
                'total': 0,
                'passed': 0,
                'failed': 0,
                'errors': 0,
                'skipped': 0
            }
        
        self.results['test_suites'][suite_name]['total'] += 1
        self.results['summary']['total_tests'] += 1
        
        if status == 'passed':
            self.results['test_suites'][suite_name]['passed'] += 1
            self.results['summary']['passed'] += 1
        elif status == 'failed':
            self.results['test_suites'][suite_name]['failed'] += 1
            self.results['summary']['failed'] += 1
        elif status == 'error':
            self.results['test_suites'][suite_name]['errors'] += 1
            self.results['summary']['errors'] += 1
        elif status == 'skipped':
            self.results['test_suites'][suite_name]['skipped'] += 1
            self.results['summary']['skipped'] += 1
        
        self.results['test_details'].append({
            'test_name': test_name,
            'status': status,
            'error_msg': error_msg,
            'traceback': traceback_str
        })


def run_tests():
    """Run all UI tests and collect results"""
    collector = TestResultCollector()
    collector.results['summary']['start_time'] = datetime.now().isoformat()
    
    # Test modules to run
    test_modules = [
        'accounts.tests.test_ui_user_management',
        'accounts.tests.test_ui_tenant_isolation',
        'connections.tests.test_ui_connections',
        'sync_jobs.tests.test_ui_sync_jobs',
    ]
    
    print("=" * 80)
    print("UI Test Execution Report")
    print("=" * 80)
    print(f"Start Time: {collector.results['summary']['start_time']}\n")
    
    # Use Django's test runner
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=2, interactive=False, keepdb=False)
    
    # Run tests
    all_results = []
    for module in test_modules:
        print(f"\n{'='*80}")
        print(f"Running tests from: {module}")
        print(f"{'='*80}\n")
        
        try:
            # Capture stdout/stderr to parse results
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = StringIO()
            sys.stderr = StringIO()
            
            result = test_runner.run_tests([module])
            
            # Restore stdout/stderr
            output = sys.stdout.getvalue()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            
            # Print output
            print(output)
            
            all_results.append((module, result))
            
            # Parse results from output (basic parsing)
            if hasattr(result, 'testsRun'):
                for i in range(result.testsRun):
                    if hasattr(result, 'failures') and i < len(result.failures):
                        test_name = result.failures[i][0]
                        error_msg = result.failures[i][1]
                        collector.add_test_result(
                            test_name,
                            'failed',
                            error_msg=error_msg
                        )
                    elif hasattr(result, 'errors') and i < len(result.errors):
                        test_name = result.errors[i][0]
                        error_msg = result.errors[i][1]
                        collector.add_test_result(
                            test_name,
                            'error',
                            error_msg=error_msg
                        )
                    else:
                        # Assume passed if not in failures or errors
                        pass
                        
        except Exception as e:
            print(f"ERROR running tests for {module}: {str(e)}")
            traceback.print_exc()
            collector.add_test_result(
                f"{module}.ERROR",
                'error',
                error_msg=str(e),
                traceback_str=traceback.format_exc()
            )
    
    collector.results['summary']['end_time'] = datetime.now().isoformat()
    
    # Generate report
    generate_report(collector)
    
    return collector


def generate_report(collector):
    """Generate comprehensive test report"""
    report_path = os.path.join(
        os.path.dirname(__file__),
        '..',
        'docs',
        'TEST_EXECUTION_REPORT.md'
    )
    
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# UI Test Execution Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # Summary
        f.write("## Summary\n\n")
        summary = collector.results['summary']
        f.write(f"- **Total Tests:** {summary['total_tests']}\n")
        f.write(f"- **Passed:** {summary['passed']} ✅\n")
        f.write(f"- **Failed:** {summary['failed']} ❌\n")
        f.write(f"- **Errors:** {summary['errors']} ⚠️\n")
        f.write(f"- **Skipped:** {summary['skipped']} ⏭️\n")
        f.write(f"- **Start Time:** {summary['start_time']}\n")
        f.write(f"- **End Time:** {summary['end_time']}\n\n")
        
        # Calculate pass rate
        if summary['total_tests'] > 0:
            pass_rate = (summary['passed'] / summary['total_tests']) * 100
            f.write(f"- **Pass Rate:** {pass_rate:.2f}%\n\n")
        
        # Test Suites Summary
        f.write("## Test Suites Summary\n\n")
        f.write("| Suite | Total | Passed | Failed | Errors | Skipped |\n")
        f.write("|-------|-------|--------|--------|--------|----------|\n")
        
        for suite_name, suite_stats in collector.results['test_suites'].items():
            f.write(f"| {suite_name} | {suite_stats['total']} | "
                   f"{suite_stats['passed']} | {suite_stats['failed']} | "
                   f"{suite_stats['errors']} | {suite_stats['skipped']} |\n")
        
        f.write("\n")
        
        # Feature Status Table
        f.write("## Feature Status Table\n\n")
        f.write("| Feature | Expected Behavior | Status | Notes |\n")
        f.write("|---------|-------------------|--------|-------|\n")
        
        # Map test names to features
        feature_map = {
            'test_1_super_admin_can_access_user_list': 'Super Admin - Access User List',
            'test_2_super_admin_can_create_admin_user': 'Super Admin - Create Admin User',
            'test_3_super_admin_can_create_operator_user': 'Super Admin - Create Operator User',
            'test_4_super_admin_can_create_viewer_user': 'Super Admin - Create Viewer User',
            'test_5_super_admin_can_view_all_users': 'Super Admin - View All Users',
            'test_6_super_admin_can_update_any_user': 'Super Admin - Update Any User',
            'test_7_super_admin_cannot_change_super_admin_role': 'Super Admin - Cannot Change Super Admin Role',
            'test_8_super_admin_can_delete_admin_without_tenant_users': 'Super Admin - Delete Admin (no users)',
            'test_9_super_admin_cannot_delete_admin_with_tenant_users': 'Super Admin - Cannot Delete Admin (with users)',
            'test_10_super_admin_cannot_delete_super_admin': 'Super Admin - Cannot Delete Super Admin',
            'test_11_super_admin_sees_all_connections': 'Super Admin - See All Connections',
            'test_12_super_admin_sees_all_sync_jobs': 'Super Admin - See All Sync Jobs',
            'test_13_admin_can_access_user_list': 'Admin - Access User List',
            'test_14_admin_can_create_operator_user': 'Admin - Create Operator User',
            'test_15_admin_can_create_viewer_user': 'Admin - Create Viewer User',
            'test_16_admin_cannot_create_admin_user': 'Admin - Cannot Create Admin User',
            'test_17_admin_can_update_tenant_users': 'Admin - Update Tenant Users',
            'test_18_admin_cannot_update_other_tenant_users': 'Admin - Cannot Update Other Tenant Users',
            'test_19_admin_can_delete_tenant_users': 'Admin - Delete Tenant Users',
            'test_20_admin_cannot_delete_other_tenant_users': 'Admin - Cannot Delete Other Tenant Users',
            'test_21_admin_creates_connection': 'Admin - Create Connection',
            'test_22_admin_sees_only_tenant_connections': 'Admin - See Only Tenant Connections',
            'test_23_admin_can_edit_tenant_connections': 'Admin - Edit Tenant Connections',
            'test_24_admin_cannot_edit_other_tenant_connections': 'Admin - Cannot Edit Other Tenant Connections',
            'test_25_admin_creates_sync_job': 'Admin - Create Sync Job',
            'test_26_admin_sees_only_tenant_jobs': 'Admin - See Only Tenant Jobs',
            'test_27_admin_can_edit_tenant_jobs': 'Admin - Edit Tenant Jobs',
            'test_28_operator_cannot_access_user_list': 'Operator - Cannot Access User List',
            'test_29_operator_cannot_create_users': 'Operator - Cannot Create Users',
            'test_30_operator_creates_connection': 'Operator - Create Connection',
            'test_31_operator_sees_only_tenant_connections': 'Operator - See Only Tenant Connections',
            'test_32_operator_can_edit_tenant_connections': 'Operator - Edit Tenant Connections',
            'test_33_operator_creates_sync_job': 'Operator - Create Sync Job',
            'test_34_operator_sees_only_tenant_jobs': 'Operator - See Only Tenant Jobs',
            'test_35_viewer_cannot_access_user_list': 'Viewer - Cannot Access User List',
            'test_36_viewer_cannot_create_users': 'Viewer - Cannot Create Users',
            'test_37_viewer_cannot_create_connection': 'Viewer - Cannot Create Connection',
            'test_38_viewer_sees_only_tenant_connections_readonly': 'Viewer - See Only Tenant Connections (Read-Only)',
            'test_39_viewer_cannot_edit_connections': 'Viewer - Cannot Edit Connections',
            'test_40_viewer_cannot_create_sync_job': 'Viewer - Cannot Create Sync Job',
            'test_41_viewer_sees_only_tenant_jobs_readonly': 'Viewer - See Only Tenant Jobs (Read-Only)',
            'test_42_viewer_cannot_edit_jobs': 'Viewer - Cannot Edit Jobs',
            'test_43_viewer_cannot_delete_jobs': 'Viewer - Cannot Delete Jobs',
            'test_44_viewer_cannot_pause_jobs': 'Viewer - Cannot Pause Jobs',
            'test_45_admin_a_cannot_see_admin_b_users': 'Tenant Isolation - Admin A Cannot See Admin B Users',
            'test_46_admin_a_cannot_see_admin_b_connections': 'Tenant Isolation - Admin A Cannot See Admin B Connections',
            'test_47_admin_a_cannot_see_admin_b_jobs': 'Tenant Isolation - Admin A Cannot See Admin B Jobs',
            'test_48_operator_a1_cannot_see_admin_b_data': 'Tenant Isolation - Operator A1 Cannot See Admin B Data',
            'test_49_viewer_a1_cannot_see_admin_b_data': 'Tenant Isolation - Viewer A1 Cannot See Admin B Data',
        }
        
        for test_detail in collector.results['test_details']:
            test_name = test_detail['test_name']
            # Extract test method name
            if '.' in test_name:
                method_name = test_name.split('.')[-1]
            else:
                method_name = test_name
            
            feature_name = feature_map.get(method_name, method_name)
            status_emoji = '✅ PASS' if test_detail['status'] == 'passed' else '❌ FAIL' if test_detail['status'] == 'failed' else '⚠️ ERROR'
            
            notes = test_detail.get('error_msg', '')[:100] if test_detail.get('error_msg') else '-'
            
            f.write(f"| {feature_name} | See test description | {status_emoji} | {notes} |\n")
        
        f.write("\n")
        
        # Detailed Test Results
        f.write("## Detailed Test Results\n\n")
        
        failed_tests = [t for t in collector.results['test_details'] if t['status'] in ['failed', 'error']]
        if failed_tests:
            f.write("### Failed Tests\n\n")
            for test in failed_tests:
                f.write(f"#### {test['test_name']}\n\n")
                f.write(f"**Status:** {test['status'].upper()}\n\n")
                if test.get('error_msg'):
                    f.write(f"**Error:** {test['error_msg']}\n\n")
                if test.get('traceback'):
                    f.write("**Traceback:**\n```\n")
                    f.write(test['traceback'])
                    f.write("\n```\n\n")
        else:
            f.write("### All Tests Passed! ✅\n\n")
        
        # Recommendations
        f.write("## Recommendations\n\n")
        if summary['failed'] > 0 or summary['errors'] > 0:
            f.write("1. Review failed tests and fix issues\n")
            f.write("2. Ensure all test data is properly set up\n")
            f.write("3. Verify tenant isolation is working correctly\n")
            f.write("4. Check permissions and role-based access control\n")
        else:
            f.write("1. All tests passed! ✅\n")
            f.write("2. Consider adding more edge case tests\n")
            f.write("3. Review test coverage and add missing scenarios\n")
        
        f.write("\n")
        f.write("---\n")
        f.write(f"*Report generated by run_ui_tests.py on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")
    
    print(f"\n{'='*80}")
    print(f"Report generated: {report_path}")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    print("Starting UI test execution...\n")
    collector = run_tests()
    
    # Print summary
    summary = collector.results['summary']
    print("\n" + "=" * 80)
    print("TEST EXECUTION SUMMARY")
    print("=" * 80)
    print(f"Total Tests: {summary['total_tests']}")
    print(f"Passed: {summary['passed']} ✅")
    print(f"Failed: {summary['failed']} ❌")
    print(f"Errors: {summary['errors']} ⚠️")
    print(f"Skipped: {summary['skipped']} ⏭️")
    
    if summary['total_tests'] > 0:
        pass_rate = (summary['passed'] / summary['total_tests']) * 100
        print(f"Pass Rate: {pass_rate:.2f}%")
    
    print("=" * 80)
    
    # Exit with appropriate code
    if summary['failed'] > 0 or summary['errors'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)
