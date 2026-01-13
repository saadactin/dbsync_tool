#!/bin/bash
# DB Sync Tool Health Check Script (Linux/Mac)
# Usage: ./scripts/health_check.sh [base_url]

set -e

BASE_URL="${1:-http://localhost:8000}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

function print_step {
    echo -e "\n${CYAN}==== $1 ====${NC}"
}

function print_success {
    echo -e "${GREEN}✓ $1${NC}"
}

function print_error {
    echo -e "${RED}✗ $1${NC}"
}

function print_info {
    echo -e "${YELLOW}→ $1${NC}"
}

ALL_HEALTHY=true

print_step "DB Sync Tool Health Check"
print_info "Base URL: $BASE_URL"

# Check 1: Health endpoint
print_step "Check 1: Application Health Endpoint"
if curl -s -f "$BASE_URL/health/" > /dev/null 2>&1; then
    HEALTH_DATA=$(curl -s "$BASE_URL/health/")
    print_success "Health endpoint accessible"
    
    # Parse JSON (requires jq or python)
    if command -v jq &> /dev/null; then
        OVERALL_STATUS=$(echo "$HEALTH_DATA" | jq -r '.overall_status')
        print_info "Overall Status: $OVERALL_STATUS"
        
        echo "$HEALTH_DATA" | jq -r '.checks | to_entries[] | "\(.key): \(.value.status)"' | while read -r line; do
            if [[ $line == *": healthy" ]]; then
                print_success "$line"
            else
                print_error "$line"
                ALL_HEALTHY=false
            fi
        done
    else
        print_info "Health data received (install jq for detailed parsing)"
        echo "$HEALTH_DATA"
    fi
else
    print_error "Cannot connect to health endpoint"
    ALL_HEALTHY=false
fi

# Check 2: Database connectivity
print_step "Check 2: Database Connectivity"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")/dbsync_tool"

if [ -d "$PROJECT_DIR/venv" ]; then
    cd "$PROJECT_DIR"
    source venv/bin/activate
    if python -c "from django.core.management import execute_from_command_line; import os; import django; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dbsync_tool.settings'); django.setup(); from django.db import connection; connection.ensure_connection(); print('OK')" 2>/dev/null; then
        print_success "Database connection successful"
    else
        print_error "Database connection failed"
        ALL_HEALTHY=false
    fi
else
    print_info "Virtual environment not found, skipping database check"
fi

# Check 3: Redis connectivity
print_step "Check 3: Redis Connectivity"
if command -v redis-cli &> /dev/null; then
    if redis-cli ping > /dev/null 2>&1; then
        print_success "Redis connection successful"
    else
        print_error "Redis connection failed"
        ALL_HEALTHY=false
    fi
else
    print_info "redis-cli not found, skipping Redis check"
fi

# Check 4: Application accessibility
print_step "Check 4: Application Accessibility"
if curl -s -f -o /dev/null -w "%{http_code}" "$BASE_URL/" | grep -q "200\|302"; then
    print_success "Application is accessible"
else
    print_error "Application is not accessible"
    ALL_HEALTHY=false
fi

# Summary
print_step "Health Check Summary"
if [ "$ALL_HEALTHY" = true ]; then
    print_success "All health checks passed!"
    exit 0
else
    print_error "Some health checks failed!"
    exit 1
fi

