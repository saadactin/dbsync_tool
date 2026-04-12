"""
Tests for DataIntegrityVerifier transform-plan awareness.
"""

from unittest.mock import Mock, patch
import unittest

from sync_engine.data_integrity_verifier import DataIntegrityVerifier


class DataIntegrityVerifierTransformTests(unittest.TestCase):
    def _make_source_connector(self):
        c = Mock()
        c.__class__.__name__ = "PostgresConnector"
        c.get_primary_key.return_value = []
        # fetch_batch is called in a loop until it returns an empty list.
        # Return a single batch, then signal completion.
        c.fetch_batch.side_effect = [[(1, "alice")], []]
        return c

    def _make_target_connector(self):
        c = Mock()
        c.__class__.__name__ = "PostgresConnector"
        c.get_row_count.return_value = 1
        # Match the single-batch then-empty behavior for the target fetch loop.
        c.fetch_batch.side_effect = [[(1, "alice")], []]
        return c

    def test_uses_compiled_transform_sql_for_source_fetch(self):
        source = self._make_source_connector()
        target = self._make_target_connector()

        verifier = DataIntegrityVerifier(source_connector=source, target_connector=target)

        job_table = Mock()
        job_table.table_name = "a"
        job_table.transformation_query = ""
        job_table.column_transformations = {}
        job_table.excluded_columns = []
        job_table.protected_columns = []
        job_table.transform_plan = {"mode": "join"}  # triggers uses_transform_runtime()
        job_table.sync_job = Mock()

        compiled_sql = 'SELECT "id" AS "id", "name" AS "name" FROM x'

        with patch(
            "sync_engine.data_integrity_verifier.prepare_runtime_transform_plan",
            return_value={"mode": "join", "source_db_type": "postgres"},
        ) as prep, patch(
            "sync_engine.data_integrity_verifier.compile_select_from_plan",
            return_value=(compiled_sql, []),
        ) as comp:
            ok, err, report = verifier.verify_data_accuracy(
                job_table=job_table,
                source_schema="public",
                target_schema="public",
                expected_row_count=1,
                column_names=["id", "name"],
                target_column_names=["id", "name"],
                target_table="a",
            )

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertTrue(report["row_count_match"])

        prep.assert_called()
        comp.assert_called()

        # Ensure the source fetch used compiled transform SQL
        # (first call contains the query that was compiled from the plan)
        first_call = source.fetch_batch.call_args_list[0]
        self.assertEqual(first_call.kwargs["query"], compiled_sql)


if __name__ == "__main__":
    unittest.main()

