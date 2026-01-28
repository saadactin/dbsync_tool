#!/bin/bash
# Setup admin user for DB Sync Tool
# Usage: ADMIN_PASSWORD=yourpassword ./scripts/setup_admin.sh

set -e

ADMIN_USERNAME="saadsayyed"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"

if [ -z "$ADMIN_PASSWORD" ]; then
    echo "Error: ADMIN_PASSWORD environment variable not set"
    echo "Usage: ADMIN_PASSWORD=yourpassword ./scripts/setup_admin.sh"
    exit 1
fi

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$PROJECT_ROOT/dbsync_tool"

cd "$PROJECT_DIR"

echo "Setting up admin user..."
python manage.py create_admin_user --password "$ADMIN_PASSWORD"

echo "Admin user setup complete!"

