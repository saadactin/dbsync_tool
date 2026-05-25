#!/usr/bin/env python3
"""
Script to create example dashboard SQL queries for Superset.

These SQL queries can be used in Superset's SQL Lab to create charts,
or as reference for building your own dashboards.
"""

# Dashboard 1: Sync Job Overview
SYNC_JOB_OVERVIEW = {
    "dashboard_name": "Sync Job Overview",
    "queries": {
        "total_jobs": """
            -- Total Jobs Run (all time)
            SELECT COUNT(*) as total_jobs
            FROM analytics.sync_executions;
        """,

        "jobs_by_status": """
            -- Jobs by Status
            SELECT
                status,
                COUNT(*) as count
            FROM analytics.sync_jobs
            GROUP BY status
            ORDER BY count DESC;
        """,

        "jobs_trend_30d": """
            -- Job Executions Trend (Last 30 Days)
            SELECT
                DATE(started_at) as date,
                COUNT(*) as executions
            FROM analytics.sync_executions
            WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY DATE(started_at)
            ORDER BY date;
        """,

        "avg_duration_per_day": """
            -- Average Job Duration Per Day (Last 30 Days)
            SELECT
                DATE(started_at) as date,
                AVG(EXTRACT(EPOCH FROM (completed_at - started_at))/60) as avg_minutes
            FROM analytics.sync_executions
            WHERE
                started_at >= CURRENT_DATE - INTERVAL '30 days'
                AND completed_at IS NOT NULL
                AND status = 'completed'
            GROUP BY DATE(started_at)
            ORDER BY date;
        """
    }
}

# Dashboard 2: Connection Health
CONNECTION_HEALTH = {
    "dashboard_name": "Connection Health",
    "queries": {
        "all_connections_status": """
            -- All Connections with Last Sync
            SELECT
                dc.name,
                dc.db_type,
                dc.host,
                dc.is_active,
                dc.last_tested_at,
                COUNT(sj.id) as job_count
            FROM analytics.database_connections dc
            LEFT JOIN analytics.sync_jobs sj ON sj.source_connection_id = dc.id
            GROUP BY dc.id, dc.name, dc.db_type, dc.host, dc.is_active, dc.last_tested_at
            ORDER BY job_count DESC;
        """,

        "success_rate_by_db_type": """
            -- Success Rate by Database Type
            SELECT
                dc.db_type,
                COUNT(*) as total_executions,
                SUM(CASE WHEN se.status = 'completed' THEN 1 ELSE 0 END) as successful,
                ROUND(100.0 * SUM(CASE WHEN se.status = 'completed' THEN 1 ELSE 0 END) / COUNT(*), 1) as success_rate
            FROM analytics.sync_executions se
            JOIN analytics.sync_jobs sj ON sj.id = se.job_id
            JOIN analytics.database_connections dc ON dc.id = sj.source_connection_id
            WHERE se.started_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY dc.db_type
            ORDER BY total_executions DESC;
        """,

        "active_connections_count": """
            -- Total Active Connections
            SELECT
                COUNT(*) as active_connections
            FROM analytics.database_connections
            WHERE is_active = true;
        """,

        "most_active_connections": """
            -- Most Active Connections (by execution count)
            SELECT
                dc.name as connection_name,
                dc.db_type,
                COUNT(se.id) as execution_count,
                SUM(se.total_rows_synced) as total_rows_synced
            FROM analytics.database_connections dc
            JOIN analytics.sync_jobs sj ON sj.source_connection_id = dc.id
            JOIN analytics.sync_executions se ON se.job_id = sj.id
            WHERE se.started_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY dc.id, dc.name, dc.db_type
            ORDER BY execution_count DESC
            LIMIT 10;
        """
    }
}

# Dashboard 3: Performance Analytics
PERFORMANCE_ANALYTICS = {
    "dashboard_name": "Performance Analytics",
    "queries": {
        "rows_synced_per_day": """
            -- Rows Synced Per Day (Last 30 Days)
            SELECT
                DATE(started_at) as date,
                SUM(total_rows_synced) as rows_synced
            FROM analytics.sync_executions
            WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY DATE(started_at)
            ORDER BY date;
        """,

        "data_volume_trend": """
            -- Data Volume Trend (Bytes Over Time)
            SELECT
                DATE(started_at) as date,
                SUM(total_source_bytes) / (1024*1024) as source_mb,
                SUM(total_target_bytes) / (1024*1024) as target_mb
            FROM analytics.sync_executions
            WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY DATE(started_at)
            ORDER BY date;
        """,

        "slowest_jobs": """
            -- Top 10 Slowest Sync Jobs (Last 30 Days)
            SELECT
                sj.name as job_name,
                se.started_at,
                se.completed_at,
                EXTRACT(EPOCH FROM (se.completed_at - se.started_at))/60 as duration_minutes,
                se.total_rows_synced
            FROM analytics.sync_executions se
            JOIN analytics.sync_jobs sj ON sj.id = se.job_id
            WHERE
                se.started_at >= CURRENT_DATE - INTERVAL '30 days'
                AND se.completed_at IS NOT NULL
                AND se.status = 'completed'
            ORDER BY duration_minutes DESC
            LIMIT 10;
        """,

        "heatmap_by_hour_day": """
            -- Job Runs Heatmap (Hour vs Day of Week)
            SELECT
                EXTRACT(DOW FROM started_at) as day_of_week,
                EXTRACT(HOUR FROM started_at) as hour_of_day,
                COUNT(*) as execution_count
            FROM analytics.sync_executions
            WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY
                EXTRACT(DOW FROM started_at),
                EXTRACT(HOUR FROM started_at)
            ORDER BY day_of_week, hour_of_day;
        """
    }
}

# Dashboard 4: Error Analysis
ERROR_ANALYSIS = {
    "dashboard_name": "Error Analysis",
    "queries": {
        "common_errors": """
            -- Most Common Error Types
            SELECT
                LEFT(error_message, 100) as error_type,
                COUNT(*) as occurrence_count
            FROM analytics.sync_execution_logs
            WHERE
                status = 'failed'
                AND error_message IS NOT NULL
            GROUP BY LEFT(error_message, 100)
            ORDER BY occurrence_count DESC
            LIMIT 10;
        """,

        "failed_jobs_with_details": """
            -- Failed Jobs with Connection Details (Last 7 Days)
            SELECT
                sj.name as job_name,
                dc.name as connection_name,
                dc.db_type,
                se.started_at,
                sel.error_message
            FROM analytics.sync_executions se
            JOIN analytics.sync_jobs sj ON sj.id = se.job_id
            LEFT JOIN analytics.database_connections dc ON dc.id = sj.source_connection_id
            LEFT JOIN analytics.sync_execution_logs sel ON sel.execution_id = se.id
            WHERE
                se.status = 'failed'
                AND se.started_at >= CURRENT_DATE - INTERVAL '7 days'
            ORDER BY se.started_at DESC
            LIMIT 50;
        """,

        "error_rate_trend": """
            -- Error Rate Trend (Last 30 Days)
            SELECT
                DATE(started_at) as date,
                COUNT(*) as total_executions,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_executions,
                ROUND(100.0 * SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) / COUNT(*), 1) as error_rate
            FROM analytics.sync_executions
            WHERE started_at >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY DATE(started_at)
            ORDER BY date;
        """,

        "jobs_need_attention": """
            -- Jobs That Failed in Last 7 Days
            SELECT
                sj.name as job_name,
                sj.status as current_status,
                COUNT(se.id) as failure_count,
                MAX(se.started_at) as last_failure
            FROM analytics.sync_jobs sj
            JOIN analytics.sync_executions se ON se.job_id = sj.id
            WHERE
                se.status = 'failed'
                AND se.started_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY sj.id, sj.name, sj.status
            ORDER BY failure_count DESC;
        """
    }
}

def print_dashboard_queries():
    """Print all dashboard queries in a formatted way."""

    dashboards = [
        SYNC_JOB_OVERVIEW,
        CONNECTION_HEALTH,
        PERFORMANCE_ANALYTICS,
        ERROR_ANALYSIS
    ]

    print("=" * 80)
    print("SUPERSET DASHBOARD SQL QUERIES")
    print("=" * 80)
    print()
    print("These queries can be used in Superset SQL Lab to create charts.")
    print("Copy and paste them into SQL Lab, then click 'Save' to create a dataset.")
    print()

    for dashboard in dashboards:
        print("=" * 80)
        print(f"DASHBOARD: {dashboard['dashboard_name']}")
        print("=" * 80)
        print()

        for query_name, query_sql in dashboard['queries'].items():
            print("-" * 80)
            print(f"Chart: {query_name.replace('_', ' ').title()}")
            print("-" * 80)
            print(query_sql.strip())
            print()

        print()

if __name__ == '__main__':
    print_dashboard_queries()
