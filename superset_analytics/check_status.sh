#!/usr/bin/env bash
# Health check script for Superset analytics stack

echo "========================================"
echo "Superset Analytics - Status Check"
echo "========================================"
echo ""

# Check Docker
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker: Not running"
    echo "   Please start Docker Desktop"
    exit 1
else
    echo "✅ Docker: Running"
fi

# Check containers
echo ""
echo "Container Status:"
echo "----------------"

containers=("superset" "superset_db" "superset_cache" "superset_worker")
all_running=true

for container in "${containers[@]}"; do
    if docker ps --format "{{.Names}}" | grep -q "^${container}$"; then
        status=$(docker inspect -f '{{.State.Status}}' ${container} 2>/dev/null)
        health=$(docker inspect -f '{{.State.Health.Status}}' ${container} 2>/dev/null || echo "n/a")

        if [ "$status" = "running" ]; then
            if [ "$health" != "n/a" ] && [ "$health" != "healthy" ]; then
                echo "⚠️  ${container}: running (health: ${health})"
                all_running=false
            else
                echo "✅ ${container}: running"
            fi
        else
            echo "❌ ${container}: ${status}"
            all_running=false
        fi
    else
        echo "❌ ${container}: not found"
        all_running=false
    fi
done

# Check services
echo ""
echo "Service Health:"
echo "---------------"

# Postgres
if docker-compose exec -T superset_db pg_isready -U superset > /dev/null 2>&1; then
    echo "✅ PostgreSQL: Ready"
else
    echo "❌ PostgreSQL: Not ready"
    all_running=false
fi

# Redis
if docker-compose exec -T superset_cache redis-cli ping > /dev/null 2>&1; then
    echo "✅ Redis: Ready"
else
    echo "❌ Redis: Not ready"
    all_running=false
fi

# Superset
if curl -f -s http://localhost:8088/health > /dev/null 2>&1; then
    echo "✅ Superset Web: Ready"
else
    echo "❌ Superset Web: Not ready"
    all_running=false
fi

# Django SQLite
echo ""
echo "Data Sources:"
echo "-------------"

sqlite_path="../dbsync_tool/db.sqlite3"
if [ -f "$sqlite_path" ]; then
    size=$(du -h "$sqlite_path" | cut -f1)
    echo "✅ Django SQLite: Found ($size)"
else
    echo "❌ Django SQLite: Not found at $sqlite_path"
fi

# Analytics schema
echo ""
echo "Analytics Schema:"
echo "-----------------"

if docker-compose exec -T superset_db psql -U superset -d superset -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'analytics'" > /dev/null 2>&1; then
    table_count=$(docker-compose exec -T superset_db psql -U superset -d superset -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'analytics'" | xargs)
    if [ "$table_count" -gt 0 ]; then
        echo "✅ Analytics tables: $table_count tables found"
    else
        echo "⚠️  Analytics tables: 0 tables (run ./refresh_data.sh)"
    fi
else
    echo "❌ Analytics schema: Cannot check"
fi

# Summary
echo ""
echo "========================================"
if $all_running; then
    echo "✅ All systems operational"
    echo ""
    echo "🌐 Superset: http://localhost:8088"
    echo "   Login: admin / admin"
    echo ""
    echo "To refresh data: ./refresh_data.sh"
else
    echo "⚠️  Some services need attention"
    echo ""
    echo "Try:"
    echo "  docker-compose down && docker-compose up -d"
    echo "  docker-compose logs -f"
fi
echo "========================================"
