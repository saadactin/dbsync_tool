"""Tests for Model Data wizard step (join/union/lookup) scaffolding."""
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role, UserProfile
from connections.models import DatabaseConnection
from sync_jobs.services.transform_plan_service import (
    TransformPlanValidationError,
    compile_preview_select,
    validate_transform_plan,
    ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE,
)
from connections.connectors.base import ColumnInfo


class WizardModelStepTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="model_wiz_user", password="pass123")
        UserProfile.objects.update_or_create(
            user=self.user, defaults={"role": Role.ADMIN, "tenant": self.user}
        )
        self.source = DatabaseConnection.objects.create(
            name="Src",
            db_type="mysql",
            host="localhost",
            port=3306,
            username="u",
            password="p",
            database_name="db",
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )
        self.target = DatabaseConnection.objects.create(
            name="Tgt",
            db_type="postgres",
            host="localhost",
            port=5432,
            username="u",
            password="p",
            database_name="db",
            is_active=True,
            created_by=self.user,
            tenant=self.user,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def _seed_db_job_session(self, tables=None):
        if tables is None:
            tables = [{"schema_name": "public", "table_name": "a"}]
        s = self.client.session
        s["sync_job_name"] = "Job"
        s["sync_job_source_connection_type"] = "database"
        s["sync_job_source_connection_id"] = str(self.source.id)
        s["sync_job_target_connection_id"] = str(self.target.id)
        s["sync_job_selected_tables"] = tables
        s.save()

    def test_step2_submits_to_model_step(self):
        self._seed_db_job_session()
        resp = self.client.post(
            reverse("sync_jobs:create_step2_submit"),
            {"selected_tables": [json.dumps({"schema": "public", "table": "a"})]},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("sync_jobs:create_step3_model"), resp["Location"])

    def test_mapping_without_model_redirects(self):
        self._seed_db_job_session()
        resp = self.client.get(reverse("sync_jobs:create_step3"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("sync_jobs:create_step3_model"), resp["Location"])

    def test_model_submit_then_mapping_ok(self):
        from sync_jobs.tests.wizard_helpers import post_model_step_with_default_plans

        self._seed_db_job_session()
        post_model_step_with_default_plans(self.client, source_db_type="mysql")
        resp = self.client.get(reverse("sync_jobs:create_step3"))
        self.assertEqual(resp.status_code, 200)

    def test_step3_model_preview_returns_error_code_for_missing_physical_columns(self):
        """
        Preview must fail fast with a stable error_code when join/output columns
        reference non-existent physical columns in source DB metadata.
        """
        self._seed_db_job_session(
            tables=[
                {"schema_name": "public", "table_name": "a"},
                {"schema_name": "public", "table_name": "b"},
            ]
        )
        session_tables = self.client.session.get("sync_job_selected_tables") or []
        # Preview is for base table `a`
        table_key = f"public.a"

        plan_input = {
            "mode": "join",
            "source_db_type": "mysql",
            "base_table": {"schema_name": "public", "table_name": "a"},
            "join_nodes": [
                {
                    "join_type": "LEFT",
                    "schema_name": "public",
                    "table_name": "b",
                    "alias": "j1",
                    "on": [
                        {
                            "left_alias": "b0",
                            "left_column": "cust_id",
                            "right_alias": "j1",
                            "right_column": "id",
                        }
                    ],
                }
            ],
            "selected_output_columns": [
                {"alias": "order_id", "table_ref": "b0", "column": "id", "data_type": "int"},
                {"alias": "customer_name", "table_ref": "j1", "column": "name", "data_type": "varchar"},
            ],
            "structured_filters": [],
            "order_by": [],
        }

        normalized = validate_transform_plan(
            plan_input,
            plan_table_key=table_key,
            allowed_table_keys={table_key, "public.b"},
            source_db_type="mysql",
        )
        body = {"table_key": table_key, "plan": normalized}

        with patch("connections.connectors.get_connector") as get_conn, patch(
            "sync_jobs.services.transform_plan_service.execute_preview_query"
        ) as exec_preview:
            connector = get_conn.return_value
            connector.connect.return_value = None
            connector.close.return_value = None

            def get_columns(schema, table):
                if schema == "public" and table == "a":
                    # Intentionally missing `id` (but includes `cust_id` for join predicate)
                    return [ColumnInfo(name="cust_id", data_type="int", is_nullable=True)]
                if schema == "public" and table == "b":
                    return [
                        ColumnInfo(name="id", data_type="int", is_nullable=True),
                        ColumnInfo(name="name", data_type="varchar", is_nullable=True),
                    ]
                return []

            connector.get_columns.side_effect = get_columns

            resp = self.client.post(
                reverse("sync_jobs:create_step3_model_preview"),
                data=json.dumps(body),
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 400)
        payload = resp.json()
        self.assertFalse(payload.get("ok"))
        self.assertEqual(payload.get("error_code"), ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE)

    def test_mysql_full_outer_validation_error(self):
        with self.assertRaises(TransformPlanValidationError) as ctx:
            validate_transform_plan(
                {
                    "mode": "join",
                    "base_table": {"schema_name": "public", "table_name": "a"},
                    "join_nodes": [
                        {
                            "join_type": "FULL",
                            "schema_name": "public",
                            "table_name": "b",
                            "alias": "j1",
                            "on": [
                                {
                                    "left_alias": "b0",
                                    "left_column": "id",
                                    "right_alias": "j1",
                                    "right_column": "id",
                                }
                            ],
                        }
                    ],
                    "selected_output_columns": [
                        {"alias": "x", "table_ref": "b0", "column": "id", "data_type": "int"},
                    ],
                },
                plan_table_key="public.a",
                allowed_table_keys={"public.a", "public.b"},
                source_db_type="mysql",
            )
        self.assertEqual(ctx.exception.error_code, "unsupported_full_mysql")

    def test_compile_preview_includes_limit_mysql(self):
        plan = validate_transform_plan(
            {
                "mode": "single_table",
                "base_table": {"schema_name": "public", "table_name": "t"},
                "source_db_type": "mysql",
            },
            plan_table_key="public.t",
            allowed_table_keys={"public.t"},
            source_db_type="mysql",
        )
        sql, _ = compile_preview_select(plan, limit=10)
        self.assertIn("LIMIT 10", sql)

    def test_migration_applies_transform_plan_column(self):
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("PRAGMA table_info(sync_job_tables);")
            cols = [row[1] for row in cursor.fetchall()]
        self.assertIn("transform_plan", cols)

    def test_structured_filter_rejects_non_identifier_column(self):
        with self.assertRaises(TransformPlanValidationError):
            validate_transform_plan(
                {
                    "mode": "single_table",
                    "base_table": {"schema_name": "public", "table_name": "t"},
                    "structured_filters": [{"column": "id; DROP TABLE x", "op": "=", "value": "1"}],
                },
                plan_table_key="public.t",
                allowed_table_keys={"public.t"},
                source_db_type="postgres",
            )

    def test_step3_model_preview_returns_columns_in_plan_order(self):
        """
        Preview endpoint should reflect join output alias ordering.

        This validates that:
        - the SQL generated from the validated plan preserves selected_output_columns order
        - the preview response `columns` and `generated_sql` are consistent
        """
        self._seed_db_job_session(
            tables=[
                {"schema_name": "public", "table_name": "a"},
                {"schema_name": "public", "table_name": "b"},
            ]
        )

        plan_input = {
            "mode": "join",
            "source_db_type": "mysql",
            "base_table": {"schema_name": "public", "table_name": "a"},
            "join_nodes": [
                {
                    "join_type": "LEFT",
                    "schema_name": "public",
                    "table_name": "b",
                    "alias": "j1",
                    "on": [
                        {
                            "left_alias": "b0",
                            "left_column": "join_key",
                            "right_alias": "j1",
                            "right_column": "join_key",
                        }
                    ],
                }
            ],
            "selected_output_columns": [
                {"alias": "order_id", "table_ref": "b0", "column": "id", "data_type": "int"},
                {"alias": "updated_at", "table_ref": "b0", "column": "updated_at", "data_type": "timestamp"},
                {"alias": "customer_name", "table_ref": "j1", "column": "name", "data_type": "varchar"},
            ],
            "structured_filters": [],
            "order_by": ["id"],
        }

        expected_cols = ["order_id", "updated_at", "customer_name"]

        table_key = "public.a"
        allowed_keys = {"public.a", "public.b"}
        normalized = validate_transform_plan(
            plan_input,
            plan_table_key=table_key,
            allowed_table_keys=allowed_keys,
            source_db_type="mysql",
        )

        body = {"table_key": table_key, "plan": normalized}

        # Mock connector + preview execution so we don't need real DB credentials.
        with patch("connections.connectors.get_connector") as get_conn, patch(
            "sync_jobs.services.transform_plan_service.execute_preview_query"
        ) as exec_preview:
            connector = get_conn.return_value
            connector.connect.return_value = None
            connector.close.return_value = None

            def get_columns(schema, table):
                if schema == "public" and table == "a":
                    return [
                        ColumnInfo(name="join_key", data_type="int", is_nullable=True),
                        ColumnInfo(name="id", data_type="int", is_nullable=True),
                        ColumnInfo(name="updated_at", data_type="timestamp", is_nullable=True),
                    ]
                if schema == "public" and table == "b":
                    return [
                        ColumnInfo(name="join_key", data_type="int", is_nullable=True),
                        ColumnInfo(name="name", data_type="varchar", is_nullable=True),
                    ]
                return []

            connector.get_columns.side_effect = get_columns

            # Preview endpoint returns `columns` from execute_preview_query.
            exec_preview.return_value = (expected_cols, [[1, "2024-01-01", "Alice"]])

            resp = self.client.post(
                reverse("sync_jobs:create_step3_model_preview"),
                data=json.dumps(body),
                content_type="application/json",
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("columns"), expected_cols)
        self.assertIn("generated_sql", payload)

        # Ensure alias order in the compiled SELECT matches selected_output_columns order.
        sql = payload["generated_sql"].upper()
        # Identifier quoting differs by DB (mysql uses backticks, sqlserver uses [], postgres uses "").
        idx_order_id = sql.find("AS `ORDER_ID`")
        if idx_order_id == -1:
            idx_order_id = sql.find('AS "ORDER_ID"')
        if idx_order_id == -1:
            idx_order_id = sql.find("AS ORDER_ID")
        if idx_order_id == -1:
            idx_order_id = sql.find("AS [ORDER_ID]")

        idx_updated_at = sql.find("AS `UPDATED_AT`")
        if idx_updated_at == -1:
            idx_updated_at = sql.find('AS "UPDATED_AT"')
        if idx_updated_at == -1:
            idx_updated_at = sql.find("AS UPDATED_AT")
        if idx_updated_at == -1:
            idx_updated_at = sql.find("AS [UPDATED_AT]")

        idx_customer = sql.find("AS `CUSTOMER_NAME`")
        if idx_customer == -1:
            idx_customer = sql.find('AS "CUSTOMER_NAME"')
        if idx_customer == -1:
            idx_customer = sql.find("AS CUSTOMER_NAME")
        if idx_customer == -1:
            idx_customer = sql.find("AS [CUSTOMER_NAME]")
        self.assertTrue(idx_order_id >= 0)
        self.assertTrue(idx_updated_at >= 0)
        self.assertTrue(idx_customer >= 0)
        self.assertLess(idx_order_id, idx_updated_at)
        self.assertLess(idx_updated_at, idx_customer)

    def test_step3_model_submit_stores_transform_plan_and_mapping_uses_output_aliases(self):
        """
        Submitting a join transform plan should:
        - validate and store `sync_job_transform_plan` in session
        - allow Step 3 mapping to use plan output aliases (not base-table columns)
        """
        self._seed_db_job_session(
            tables=[
                {"schema_name": "public", "table_name": "a"},
                {"schema_name": "public", "table_name": "b"},
            ]
        )

        table_key = "public.a"
        plan_input = {
            "mode": "join",
            "source_db_type": "mysql",
            "base_table": {"schema_name": "public", "table_name": "a"},
            "join_nodes": [
                {
                    "join_type": "INNER",
                    "schema_name": "public",
                    "table_name": "b",
                    "alias": "j1",
                    "on": [
                        {
                            "left_alias": "b0",
                            "left_column": "join_key",
                            "right_alias": "j1",
                            "right_column": "join_key",
                        }
                    ],
                }
            ],
            "selected_output_columns": [
                {"alias": "order_id", "table_ref": "b0", "column": "id", "data_type": "int"},
                {"alias": "customer_name", "table_ref": "j1", "column": "name", "data_type": "varchar"},
            ],
            "structured_filters": [],
            "order_by": ["id"],
        }

        with patch("connections.connectors.get_connector") as get_conn:
            # Submit doesn't execute preview, so we mainly avoid accidental connector access.
            get_conn.return_value.connect.return_value = None
            get_conn.return_value.close.return_value = None

            def get_columns(schema, table):
                if schema == "public" and table == "a":
                    return [
                        ColumnInfo(name="join_key", data_type="int", is_nullable=True),
                        ColumnInfo(name="id", data_type="int", is_nullable=True),
                    ]
                if schema == "public" and table == "b":
                    return [
                        ColumnInfo(name="join_key", data_type="int", is_nullable=True),
                        ColumnInfo(name="name", data_type="varchar", is_nullable=True),
                    ]
                return []

            get_conn.return_value.get_columns.side_effect = get_columns

            resp = self.client.post(
                reverse("sync_jobs:create_step3_model_submit"),
                data={"transform_plans_json": json.dumps({table_key: plan_input})},
                follow=False,
            )

        # Redirect to mapping step.
        self.assertEqual(resp.status_code, 302)

        session = self.client.session
        stored = session.get("sync_job_transform_plan") or {}
        self.assertIn(table_key, stored)
        stored_plan = stored[table_key]
        self.assertEqual((stored_plan.get("mode") or "").lower(), "join")
        stored_aliases = [c.get("alias") for c in (stored_plan.get("selected_output_columns") or [])]
        self.assertEqual(stored_aliases, ["order_id", "customer_name"])

        # Mapping step should reflect plan output aliases via synthetic mapping columns.
        mapping_resp = self.client.get(reverse("sync_jobs:create_step3"))
        self.assertEqual(mapping_resp.status_code, 200)
        content = mapping_resp.content.decode("utf-8", errors="replace")
        self.assertIn("order_id", content)
        self.assertIn("customer_name", content)

    @patch("sync_jobs.views.load_table_columns")
    def test_builder_metadata_returns_columns_and_suggestions(self, mock_load_columns):
        self._seed_db_job_session(
            tables=[
                {"schema_name": "dbo", "table_name": "Laptop"},
                {"schema_name": "dbo", "table_name": "Sales"},
            ]
        )

        def side_effect(conn_id, schema, table, user):
            if schema == "dbo" and table == "Laptop":
                return [{"name": "LaptopID"}, {"name": "Brand"}]
            if schema == "dbo" and table == "Sales":
                return [{"name": "LaptopID"}, {"name": "SaleID"}]
            return []

        mock_load_columns.side_effect = side_effect
        resp = self.client.get(reverse("sync_jobs:create_step3_model_builder_metadata"))
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertTrue(payload.get("ok"))
        self.assertIn("dbo.Laptop", payload.get("tables", {}))
        sugg = payload.get("join_suggestions", {}).get("dbo.Laptop__dbo.Sales", [])
        self.assertTrue(any((x.get("left_column") or "").lower() == "laptopid" for x in sugg))

    def test_step3_model_preview_accepts_builder_payload_join(self):
        self._seed_db_job_session(
            tables=[
                {"schema_name": "public", "table_name": "a"},
                {"schema_name": "public", "table_name": "b"},
            ]
        )
        body = {
            "table_key": "public.a",
            "plan": {},
            "builder_payload": {
                "mode": "join",
                "source_db_type": "mysql",
                "base_table": {"schema_name": "public", "table_name": "a"},
                "join_nodes": [
                    {
                        "join_type": "LEFT",
                        "schema_name": "public",
                        "table_name": "b",
                        "alias": "j1",
                        "on": [
                            {
                                "left_alias": "b0",
                                "left_column": "id",
                                "right_alias": "j1",
                                "right_column": "id",
                            }
                        ],
                    }
                ],
                "selected_output_columns": [
                    {"alias": "id", "table_ref": "b0", "column": "id", "data_type": "int"},
                ],
                "structured_filters": [],
                "order_by": [],
            },
        }
        with patch("connections.connectors.get_connector") as get_conn, patch(
            "sync_jobs.services.transform_plan_service.execute_preview_query"
        ) as exec_preview:
            connector = get_conn.return_value
            connector.connect.return_value = None
            connector.close.return_value = None
            connector.get_columns.side_effect = lambda s, t: [ColumnInfo(name="id", data_type="int", is_nullable=True)]
            exec_preview.return_value = (["id"], [[1]])
            resp = self.client.post(
                reverse("sync_jobs:create_step3_model_preview"),
                data=json.dumps(body),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

    def test_step3_model_preview_rejects_custom_sql_for_non_admin(self):
        viewer = User.objects.create_user(username="operator_user", password="pass123")
        UserProfile.objects.update_or_create(
            user=viewer, defaults={"role": Role.OPERATOR, "tenant": self.user}
        )
        self.client.force_login(viewer)
        self._seed_db_job_session(
            tables=[{"schema_name": "public", "table_name": "a"}]
        )
        body = {
            "table_key": "public.a",
            "plan": {},
            "builder_payload": {
                "mode": "custom_sql",
                "custom_sql": "SELECT * FROM public.a",
                "base_table": {"schema_name": "public", "table_name": "a"},
            },
        }
        with patch("connections.connectors.get_connector") as get_conn:
            get_conn.return_value.connect.return_value = None
            get_conn.return_value.close.return_value = None
            resp = self.client.post(
                reverse("sync_jobs:create_step3_model_preview"),
                data=json.dumps(body),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error_code"), "custom_sql_not_allowed")
