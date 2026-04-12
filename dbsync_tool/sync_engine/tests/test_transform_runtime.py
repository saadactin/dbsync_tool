"""Unit tests for model transform runtime compile and incremental subquery wrapper."""
import unittest
from unittest.mock import Mock

from sync_engine.query_builder import QueryBuilder
from sync_jobs.services.transform_plan_service import (
    builder_to_transform_plan,
    TransformPlanValidationError,
    check_transform_db_type_drift,
    compile_select_from_plan,
    prepare_runtime_transform_plan,
    suggest_join_keys,
    validate_transform_plan,
    validate_incremental_key_from_base,
    validate_custom_sql_preview,
    validate_transform_plan_column_references,
    ERROR_TRANSFORM_DB_TYPE_DRIFT,
    ERROR_INCREMENTAL_UNSUPPORTED_TRANSFORM,
    ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE,
)
from connections.connectors.base import ColumnInfo


class TransformRuntimeCompileTests(unittest.TestCase):
    def _validated_join_plan(self):
        raw = {
            "mode": "join",
            "source_db_type": "postgres",
            "base_table": {"schema_name": "public", "table_name": "orders"},
            "join_nodes": [
                {
                    "join_type": "LEFT",
                    "schema_name": "public",
                    "table_name": "customers",
                    "alias": "c1",
                    "on": [
                        {
                            "left_alias": "b0",
                            "left_column": "cust_id",
                            "right_alias": "c1",
                            "right_column": "id",
                        }
                    ],
                }
            ],
            "selected_output_columns": [
                {"alias": "order_id", "table_ref": "b0", "column": "id", "data_type": "int"},
                {"alias": "name", "table_ref": "c1", "column": "name", "data_type": "varchar"},
            ],
            "structured_filters": [],
            "order_by": [],
        }
        return validate_transform_plan(
            raw,
            plan_table_key="public.orders",
            allowed_table_keys={"public.orders", "public.customers"},
            source_db_type="postgres",
        )

    def test_runtime_join_sql_has_no_outer_limit(self):
        plan = self._validated_join_plan()
        sql, _ = compile_select_from_plan(plan, preview_limit=None)
        upper = sql.upper()
        self.assertNotRegex(upper, r"\bLIMIT\s+\d+")
        self.assertNotRegex(upper, r"\bTOP\s+\d+\s+\*")
        self.assertIn("JOIN", upper)

    def test_preview_join_sql_bounded(self):
        plan = self._validated_join_plan()
        sql, _ = compile_select_from_plan(plan, preview_limit=50)
        upper = sql.upper()
        self.assertTrue(
            "LIMIT 50" in upper or "TOP 50" in upper or "ROWNUM <=" in upper.replace(" ", ""),
            msg=sql,
        )

    def test_db_type_drift_raises(self):
        plan = {"source_db_type": "postgres", "mode": "single_table"}
        with self.assertRaises(TransformPlanValidationError) as ctx:
            check_transform_db_type_drift(plan, "mysql")
        self.assertEqual(ctx.exception.error_code, ERROR_TRANSFORM_DB_TYPE_DRIFT)

    def test_prepare_runtime_union_with_mock_job(self):
        job_table = Mock()
        job_table.schema_name = "public"
        job_table.table_name = "a"
        job_table.transform_plan = {
            "mode": "union",
            "source_db_type": "postgres",
            "base_table": {"schema_name": "public", "table_name": "a"},
            "union_branches": [
                {"schema_name": "public", "table_name": "a"},
                {"schema_name": "public", "table_name": "b"},
            ],
            "union_select_columns": ["id", "name"],
            "order_by": [],
        }
        t1 = Mock(schema_name="public", table_name="a")
        t2 = Mock(schema_name="public", table_name="b")
        job = Mock()
        job.tables.all = Mock(return_value=[t1, t2])
        plan = prepare_runtime_transform_plan(
            job_table,
            job,
            "postgres",
            excluded_cols_lower=set(),
            protected_cols_lower=set(),
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan["mode"], "union")

    def test_build_incremental_on_subquery_postgres(self):
        pg = Mock()
        pg.__class__ = type("PostgresConnector", (), {})
        pg.__class__.__name__ = "PostgresConnector"
        inner = 'SELECT "id" AS "id", "name" AS "name" FROM "public"."orders"'
        sql = QueryBuilder.build_incremental_on_subquery(
            pg,
            inner,
            "tfs",
            "id",
            None,
            ["id", "name"],
            "id",
        )
        self.assertIn('"tfs"', sql)
        self.assertIn("WHERE 1=1", sql)
        self.assertIn("ORDER BY", sql)

    def test_build_incremental_on_subquery_sqlserver_checkpoint(self):
        m = Mock()
        m.__class__ = type("SQLServerConnector", (), {})
        m.__class__.__name__ = "SQLServerConnector"
        inner = "SELECT [id] AS [id] FROM [dbo].[Orders]"
        sql = QueryBuilder.build_incremental_on_subquery(
            m,
            inner,
            "tfs",
            "id",
            100,
            ["id"],
            "id",
        )
        self.assertIn("[tfs]", sql)
        self.assertIn(">", sql)

    def test_incremental_key_requires_base_table_output_alias(self):
        plan = self._validated_join_plan()
        with self.assertRaises(TransformPlanValidationError) as ctx:
            validate_incremental_key_from_base(plan, "name")  # `name` comes from join alias c1, not base b0
        self.assertEqual(ctx.exception.error_code, ERROR_INCREMENTAL_UNSUPPORTED_TRANSFORM)

    def test_incremental_key_allows_base_table_output_alias(self):
        plan = self._validated_join_plan()
        validate_incremental_key_from_base(plan, "order_id")  # `order_id` comes from base alias b0

    def test_validate_column_references_join_missing_output_column(self):
        plan = self._validated_join_plan()
        connector = Mock()

        def get_columns(schema, table):
            # Base orders: intentionally missing `id` (but join condition uses cust_id)
            if schema == "public" and table == "orders":
                return [
                    ColumnInfo(name="cust_id", data_type="int", is_nullable=True),
                ]
            # Join customers: has id and name
            if schema == "public" and table == "customers":
                return [
                    ColumnInfo(name="id", data_type="int", is_nullable=True),
                    ColumnInfo(name="name", data_type="varchar", is_nullable=True),
                ]
            return []

        connector.get_columns.side_effect = get_columns

        with self.assertRaises(TransformPlanValidationError) as ctx:
            validate_transform_plan_column_references(plan, connector)
        self.assertEqual(ctx.exception.error_code, ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE)
        # Message should be actionable: list available columns for the missing physical table.
        msg = str(ctx.exception)
        self.assertIn("Available columns for public.orders", msg)
        self.assertIn("cust_id", msg)

    def test_validate_column_references_join_missing_on_column(self):
        plan = self._validated_join_plan()
        connector = Mock()

        def get_columns(schema, table):
            # Base orders: intentionally missing `cust_id` used by join condition.
            if schema == "public" and table == "orders":
                return [
                    ColumnInfo(name="id", data_type="int", is_nullable=True),
                ]
            if schema == "public" and table == "customers":
                return [
                    ColumnInfo(name="id", data_type="int", is_nullable=True),
                    ColumnInfo(name="name", data_type="varchar", is_nullable=True),
                ]
            return []

        connector.get_columns.side_effect = get_columns

        with self.assertRaises(TransformPlanValidationError) as ctx:
            validate_transform_plan_column_references(plan, connector)
        self.assertEqual(ctx.exception.error_code, ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE)

    def test_validate_column_references_union_missing_branch_column(self):
        raw = {
            "mode": "union",
            "source_db_type": "postgres",
            "base_table": {"schema_name": "public", "table_name": "a"},
            "union_branches": [
                {"schema_name": "public", "table_name": "a"},
                {"schema_name": "public", "table_name": "b"},
            ],
            "union_select_columns": ["id", "name"],
            "order_by": [],
        }
        plan = validate_transform_plan(
            raw,
            plan_table_key="public.a",
            allowed_table_keys={"public.a", "public.b"},
            source_db_type="postgres",
        )

        connector = Mock()

        def get_columns(schema, table):
            if schema == "public" and table == "a":
                return [
                    ColumnInfo(name="id", data_type="int", is_nullable=True),
                    # Missing `name`
                ]
            if schema == "public" and table == "b":
                return [
                    ColumnInfo(name="id", data_type="int", is_nullable=True),
                    ColumnInfo(name="name", data_type="varchar", is_nullable=True),
                ]
            return []

        connector.get_columns.side_effect = get_columns

        with self.assertRaises(TransformPlanValidationError) as ctx:
            validate_transform_plan_column_references(plan, connector)
        self.assertEqual(ctx.exception.error_code, ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE)

    def test_validate_column_references_single_table_structured_filter_missing_column(self):
        raw = {
            "mode": "single_table",
            "source_db_type": "postgres",
            "base_table": {"schema_name": "public", "table_name": "t"},
            "join_nodes": [],
            "union_branches": [],
            "union_select_columns": [],
            "lookup": None,
            "selected_output_columns": [],
            "structured_filters": [
                {"column": "missing_col", "op": "=", "value": 1},
            ],
            "order_by": [],
            "derived_columns": [],
        }
        plan = validate_transform_plan(
            raw,
            plan_table_key="public.t",
            allowed_table_keys={"public.t"},
            source_db_type="postgres",
        )

        connector = Mock()

        def get_columns(schema, table):
            if schema == "public" and table == "t":
                return [ColumnInfo(name="id", data_type="int", is_nullable=True)]
            return []

        connector.get_columns.side_effect = get_columns

        with self.assertRaises(TransformPlanValidationError) as ctx:
            validate_transform_plan_column_references(plan, connector)
        self.assertEqual(ctx.exception.error_code, ERROR_TRANSFORM_INVALID_COLUMN_REFERENCE)

    def test_suggest_join_keys_prefers_exact_match(self):
        out = suggest_join_keys(["LaptopID", "Brand"], ["LaptopID", "SaleID"])
        self.assertTrue(out)
        self.assertEqual(out[0]["left_column"], "LaptopID")
        self.assertEqual(out[0]["right_column"], "LaptopID")

    def test_validate_custom_sql_preview_blocks_dml(self):
        with self.assertRaises(TransformPlanValidationError):
            validate_custom_sql_preview("SELECT * FROM x DELETE FROM y")

    def test_builder_to_transform_plan_custom_sql_requires_permission(self):
        with self.assertRaises(TransformPlanValidationError) as ctx:
            builder_to_transform_plan(
                {"mode": "custom_sql", "custom_sql": "SELECT * FROM t"},
                plan_table_key="public.t",
                allowed_table_keys={"public.t"},
                source_db_type="postgres",
                allow_custom_sql=False,
            )
        self.assertEqual(ctx.exception.error_code, "custom_sql_not_allowed")


if __name__ == "__main__":
    unittest.main()
