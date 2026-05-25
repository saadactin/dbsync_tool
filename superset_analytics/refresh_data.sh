#!/usr/bin/env bash
set -e

echo "========================================"
echo "Refreshing Superset Analytics Data"
echo "========================================"
echo "Started: $(date)"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker Desktop."
    exit 1
fi

# Check if containers are running
if ! docker-compose ps | grep -q "Up"; then
    echo "📦 Starting Docker containers..."
    docker-compose up -d

    echo "⏳ Waiting for Postgres to be ready..."
    for i in {1..30}; do
        if docker-compose exec -T superset_db pg_isready -U superset > /dev/null 2>&1; then
            echo "✅ Postgres is ready"
            break
        fi
        echo "   Waiting... ($i/30)"
        sleep 2
    done
fi

# Run sync script
echo ""
echo "📊 Syncing data from Django SQLite to Postgres..."
python3 sync_to_postgres.py

echo ""
echo "✅ Data refresh complete!"
echo "🌐 Open Superset: http://localhost:8088"
echo "   Login: admin / admin"
echo ""
