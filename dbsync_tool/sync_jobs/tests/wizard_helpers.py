"""
Helpers for multi-step job creation wizard tests.
"""
import json
from unittest.mock import patch

from django.urls import reverse

from sync_jobs.services.transform_plan_service import (
    default_plan_for_table,
    ensure_default_plans,
    normalize_internal_db_type,
)


def post_model_step_with_default_plans(client, source_db_type: str = "postgres"):
    """
    Complete Step 3a (model data) with single_table plans for all selected tables.

    Requires client session to already contain sync_job_selected_tables.
    """
    session = client.session
    tables = session.get("sync_job_selected_tables") or []
    if not tables:
        raise ValueError("post_model_step_with_default_plans requires sync_job_selected_tables in session")
    internal = normalize_internal_db_type(source_db_type)
    plans = {}
    for t in tables:
        key = f"{t['schema_name']}.{t['table_name']}"
        plans[key] = default_plan_for_table(t["schema_name"], t["table_name"], internal)
    # Step 3 submit now validates column references against source metadata by
    # connecting to the real connector. For wizard tests we mock the connector.
    with patch("connections.connectors.get_connector") as get_conn:
        connector = get_conn.return_value
        connector.connect.return_value = None
        connector.close.return_value = None
        connector.get_columns.return_value = []
        return client.post(
            reverse("sync_jobs:create_step3_model_submit"),
            data={"transform_plans_json": json.dumps(plans)},
        )


def seed_transform_plans_in_session(client, source_db_type: str = "postgres"):
    """
    Set validated default transform plans without an extra HTTP POST (avoids rate limits in tests).
    """
    session = client.session
    tables = session.get("sync_job_selected_tables") or []
    if not tables:
        raise ValueError("seed_transform_plans_in_session requires sync_job_selected_tables in session")
    internal = normalize_internal_db_type(source_db_type)
    session["sync_job_transform_plan"] = ensure_default_plans(tables, internal, {})
    session["sync_job_transform_validated"] = True
    session.modified = True
    session.save()
