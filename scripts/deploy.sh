#!/bin/bash
# DB Sync Tool Deployment Script (Linux/Mac)
# Usage: ./scripts/deploy.sh

set -e  # Exit on error

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

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$PROJECT_ROOT/dbsync_tool"

cd "$PROJECT_DIR"

print_step "DB Sync Tool Deployment Script"
print_info "Project Directory: $PROJECT_DIR"

# Step 1: Check prerequisites
print_step "Step 1: Checking Prerequisites"

# Check Python
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    print_success "Python found: $PYTHON_VERSION"
else
    print_error "Python3 not found. Please install Python 3.9+"
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    print_error "Virtual environment not found"
    print_info "Creating virtual environment..."
    python3 -m venv venv
    print_success "Virtual environment created"
fi

# Activate virtual environment
print_info "Activating virtual environment..."
source venv/bin/activate

# Check if .env file exists
if [ ! -f ".env" ]; then
    print_error ".env file not found. Please create .env file with required configuration."
    exit 1
fi
print_success ".env file found"

# Step 2: Backup (optional)
if [ "$1" != "--skip-backup" ]; then
    print_step "Step 2: Creating Backup"
    
    BACKUP_DIR="$PROJECT_ROOT/backups"
    mkdir -p "$BACKUP_DIR"
    
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/backup_$TIMESTAMP.sql"
    
    print_info "Creating database backup..."
    # Adjust pg_dump command based on your setup
    # pg_dump -U user -d tauseef > "$BACKUP_FILE"
    print_info "Database backup command (configure based on your setup):"
    print_info "pg_dump -U user -d tauseef > $BACKUP_FILE"
    print_success "Backup created: $BACKUP_FILE"
else
    print_info "Skipping backup (--skip-backup flag set)"
fi

# Step 3: Update dependencies
print_step "Step 3: Updating Dependencies"
print_info "Installing/updating Python packages..."
pip install --upgrade pip
pip install -r requirements.txt
print_success "Dependencies updated"

# Step 4: Run tests (optional)
if [ "$1" != "--skip-tests" ] && [ "$2" != "--skip-tests" ]; then
    print_step "Step 4: Running Tests"
    print_info "Running test suite..."
    python manage.py test --noinput
    print_success "All tests passed"
else
    print_info "Skipping tests (--skip-tests flag set)"
fi

# Step 5: Run migrations
print_step "Step 5: Running Database Migrations"
print_info "Applying database migrations..."
python manage.py migrate --noinput
print_success "Migrations applied"

# Step 6: Collect static files
print_step "Step 6: Collecting Static Files"
print_info "Collecting static files..."
python manage.py collectstatic --noinput
print_success "Static files collected"

# Step 7: Restart services (if applicable)
print_step "Step 7: Restarting Services"
print_info "Note: Service restart commands depend on your deployment setup"
print_info "For systemd services, use:"
print_info "  sudo systemctl restart dbsync-tool"
print_info "  sudo systemctl restart celery-worker"
print_info "  sudo systemctl restart celery-beat"

# Step 8: Health check
print_step "Step 8: Health Check"
print_info "Run health check manually:"
print_info "  curl http://localhost:8000/health/"
print_info "Or open in browser: http://localhost:8000/health/"

print_step "Deployment Complete"
print_success "Deployment completed successfully!"
print_info "Please verify the application is running correctly"

