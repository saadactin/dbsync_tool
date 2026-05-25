#!/usr/bin/env bash
set -e

echo "========================================"
echo "DB Sync Tool - Superset Analytics Setup"
echo "========================================"
echo "Started: $(date)"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop and try again."
    exit 1
fi

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "✅ Created .env file"
    echo "   Review and update credentials if needed"
    echo ""
fi

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Pull Docker images
echo "📦 Pulling Docker images..."
docker-compose pull

# Start containers
echo ""
echo "🚀 Starting Docker containers..."
docker-compose up -d

# Wait for Postgres
echo ""
echo "⏳ Waiting for Postgres to be ready..."
for i in {1..30}; do
    if docker-compose exec -T superset_db pg_isready -U ${SUPERSET_DB_USER} > /dev/null 2>&1; then
        echo "✅ Postgres is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ Timeout waiting for Postgres"
        exit 1
    fi
    echo "   Waiting... ($i/30)"
    sleep 2
done

# Wait for Superset
echo ""
echo "⏳ Waiting for Superset to be ready..."
for i in {1..60}; do
    if docker-compose exec -T superset curl -f http://localhost:8088/health > /dev/null 2>&1; then
        echo "✅ Superset is ready"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "❌ Timeout waiting for Superset"
        exit 1
    fi
    echo "   Waiting... ($i/60)"
    sleep 3
done

# Install Python dependencies for sync script
echo ""
echo "📦 Installing Python dependencies..."
pip install -q -r requirements_sync.txt

# Run initial data sync
echo ""
echo "📊 Running initial data sync..."
python3 sync_to_postgres.py

# Configure database connection in Superset
echo ""
echo "🔧 Configuring Superset database connection..."
docker-compose exec -T superset bash -c "
superset set-database-uri \
  -d 'DB Sync Analytics' \
  -u 'postgresql://${SUPERSET_DB_USER}:${SUPERSET_DB_PASSWORD}@${SUPERSET_DB_HOST}:${SUPERSET_DB_PORT}/${SUPERSET_DB_NAME}?options=-c%20search_path=analytics'
" || echo "⚠️  Database connection setup may need manual configuration"

echo ""
echo "========================================"
echo "✅ Setup Complete!"
echo "========================================"
echo ""
echo "🌐 Superset is running at: http://localhost:8088"
echo ""
echo "Login credentials:"
echo "  Username: ${ADMIN_USERNAME}"
echo "  Password: ${ADMIN_PASSWORD}"
echo ""
echo "Next steps:"
echo "  1. Open http://localhost:8088 in your browser"
echo "  2. Log in with the credentials above"
echo "  3. Configure database connection:"
echo "     - Go to: Settings → Database Connections"
echo "     - Add Database"
echo "     - Name: DB Sync Analytics"
echo "     - SQLAlchemy URI: postgresql://${SUPERSET_DB_USER}:${SUPERSET_DB_PASSWORD}@superset_db:5432/${SUPERSET_DB_NAME}?options=-c%20search_path=analytics"
echo "     - Test Connection → Connect"
echo "  4. Create datasets from analytics schema tables"
echo "  5. Build dashboards from the datasets"
echo ""
echo "To refresh data from Django SQLite:"
echo "  ./refresh_data.sh"
echo ""
echo "To stop Superset:"
echo "  docker-compose down"
echo ""
echo "To wipe all data and start fresh:"
echo "  docker-compose down -v"
echo ""
