#!/bin/bash
# DB Sync Tool Backup Script (Linux/Mac)
# Usage: ./scripts/backup.sh [backup_dir] [retention_days]

set -e

BACKUP_DIR="${1:-backups}"
RETENTION_DAYS="${2:-30}"

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
BACKUP_PATH="$PROJECT_ROOT/$BACKUP_DIR"

print_step "DB Sync Tool Backup Script"
print_info "Backup Directory: $BACKUP_PATH"
print_info "Retention: $RETENTION_DAYS days"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_PATH"
print_success "Backup directory ready"

# Generate timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_PATH/backup_$TIMESTAMP.sql"
BACKUP_ZIP="$BACKUP_FILE.gz"

# Database backup
print_step "Step 1: Database Backup"
print_info "Creating database backup..."

# Load environment variables if .env exists
if [ -f "$PROJECT_ROOT/dbsync_tool/.env" ]; then
    export $(cat "$PROJECT_ROOT/dbsync_tool/.env" | grep -v '^#' | xargs)
fi

# Database connection details (adjust as needed)
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-tauseef}"
DB_USER="${DB_USER:-migration_user}"

print_info "Database backup command (configure based on your setup):"
print_info "PGPASSWORD=\$DB_PASSWORD pg_dump -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME > $BACKUP_FILE"

# Example backup command (uncomment and adjust):
# export PGPASSWORD="$DB_PASSWORD"
# pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" > "$BACKUP_FILE"

if [ -f "$BACKUP_FILE" ]; then
    print_info "Compressing backup..."
    gzip "$BACKUP_FILE"
    print_success "Backup compressed: $BACKUP_ZIP"
else
    print_info "Backup file not created (command not executed - configure above)"
fi

# Configuration backup
print_step "Step 2: Configuration Backup"
CONFIG_BACKUP="$BACKUP_PATH/config_$TIMESTAMP.tar.gz"
CONFIG_FILES=(
    ".env"
    "dbsync_tool/dbsync_tool/settings.py"
    "requirements.txt"
)

CONFIG_FILES_TO_BACKUP=()
for file in "${CONFIG_FILES[@]}"; do
    FILE_PATH="$PROJECT_ROOT/$file"
    if [ -f "$FILE_PATH" ]; then
        CONFIG_FILES_TO_BACKUP+=("$FILE_PATH")
    fi
done

if [ ${#CONFIG_FILES_TO_BACKUP[@]} -gt 0 ]; then
    tar -czf "$CONFIG_BACKUP" -C "$PROJECT_ROOT" "${CONFIG_FILES_TO_BACKUP[@]#$PROJECT_ROOT/}"
    print_success "Configuration backup created: $CONFIG_BACKUP"
else
    print_info "No configuration files found to backup"
fi

# Cleanup old backups
print_step "Step 3: Cleanup Old Backups"
CUTOFF_DATE=$(date -d "$RETENTION_DAYS days ago" +%Y%m%d 2>/dev/null || date -v-${RETENTION_DAYS}d +%Y%m%d 2>/dev/null || echo "")

if [ -n "$CUTOFF_DATE" ]; then
    OLD_BACKUPS=$(find "$BACKUP_PATH" -name "backup_*.sql*" -type f -mtime +$RETENTION_DAYS 2>/dev/null || echo "")
    if [ -n "$OLD_BACKUPS" ]; then
        OLD_COUNT=$(echo "$OLD_BACKUPS" | wc -l)
        print_info "Removing $OLD_COUNT old backup(s)..."
        echo "$OLD_BACKUPS" | xargs rm -f
        print_success "Old backups removed"
    else
        print_info "No old backups to remove"
    fi
else
    print_info "Cannot determine cutoff date, skipping cleanup"
fi

# Summary
print_step "Backup Summary"
print_success "Backup completed successfully!"
if [ -f "$BACKUP_ZIP" ]; then
    print_info "Backup file: $BACKUP_ZIP"
fi
if [ -f "$CONFIG_BACKUP" ]; then
    print_info "Config backup: $CONFIG_BACKUP"
fi

# List recent backups
print_info "Recent backups:"
ls -lt "$BACKUP_PATH"/backup_* 2>/dev/null | head -5 | awk '{print "  " $9 " - " $6 " " $7 " " $8}' || print_info "  No backups found"

