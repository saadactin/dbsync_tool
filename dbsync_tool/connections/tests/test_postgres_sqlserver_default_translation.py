"""PostgreSQL DDL defaults: SQL Server metadata expressions must translate safely."""

from django.test import TestCase

from connections.connectors.postgres import PostgresConnector


class PostgresSqlServerDefaultTranslationTests(TestCase):
    def setUp(self):
        self.pg = PostgresConnector(
            host="localhost",
            port=5432,
            username="u",
            password="p",
            database_name="db",
        )

    def test_getdate_wrapped_variants(self):
        self.assertEqual(
            self.pg._format_default_value("(getdate())", "TIMESTAMP WITHOUT TIME ZONE"),
            "CURRENT_TIMESTAMP",
        )
        self.assertEqual(
            self.pg._format_default_value("((GETDATE()))", "TIMESTAMP WITHOUT TIME ZONE"),
            "CURRENT_TIMESTAMP",
        )
        self.assertEqual(
            self.pg._format_default_value("GETDATE()", "TIMESTAMP"),
            "CURRENT_TIMESTAMP",
        )

    def test_sysdatetime_variants(self):
        self.assertEqual(
            self.pg._format_default_value("(SYSDATETIME())", "TIMESTAMP WITHOUT TIME ZONE"),
            "CURRENT_TIMESTAMP",
        )
        self.assertEqual(
            self.pg._format_default_value("SYSUTCDATETIME()", "TIMESTAMP WITHOUT TIME ZONE"),
            "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')",
        )
        self.assertEqual(
            self.pg._format_default_value("GETUTCDATE()", "TIMESTAMP WITHOUT TIME ZONE"),
            "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')",
        )

    def test_newid_to_gen_random_uuid(self):
        self.assertEqual(
            self.pg._format_default_value("(NEWID())", "UUID"),
            "gen_random_uuid()",
        )
        self.assertEqual(
            self.pg._format_default_value("NEWSEQUENTIALID()", "UUID"),
            "gen_random_uuid()",
        )

    def test_numeric_literal_wrapped_for_integer(self):
        self.assertEqual(self.pg._format_default_value("((0))", "INTEGER"), "0")
        self.assertEqual(self.pg._format_default_value("(1)", "BIGINT"), "1")

    def test_numeric_wrapped_quoted_for_text_column(self):
        self.assertEqual(self.pg._format_default_value("((0))", "TEXT"), "'0'")
        self.assertEqual(self.pg._format_default_value("((1))", "TEXT"), "'1'")

    def test_preserves_postgres_builtins(self):
        self.assertEqual(self.pg._format_default_value("now()", "TIMESTAMP"), "NOW()")
        self.assertEqual(
            self.pg._format_default_value("public.gen_random_uuid()", "UUID"),
            "public.gen_random_uuid()",
        )

    def test_now_on_text_column_casts_to_text(self):
        self.assertEqual(
            self.pg._format_default_value("now()", "TEXT"),
            "(NOW())::text",
        )

    def test_convert_getdate_peeled_for_timestamp_column(self):
        self.assertEqual(
            self.pg._format_default_value(
                "(CONVERT([datetime],GETDATE()))",
                "TIMESTAMP WITHOUT TIME ZONE",
            ),
            "CURRENT_TIMESTAMP",
        )

    def test_convert_getdate_peeled_for_text_column(self):
        self.assertEqual(
            self.pg._format_default_value("(CONVERT(VARCHAR(30),GETDATE(),121))", "TEXT"),
            "(CURRENT_TIMESTAMP)::text",
        )

    def test_try_convert_getdate(self):
        self.assertEqual(
            self.pg._format_default_value("TRY_CONVERT(date,GETDATE())", "DATE"),
            "CURRENT_TIMESTAMP",
        )

    def test_cast_getdate_as_datetime(self):
        self.assertEqual(
            self.pg._format_default_value("(CAST(GETDATE() AS DATETIME))", "TIMESTAMP"),
            "CURRENT_TIMESTAMP",
        )

    def test_nested_convert_peels_to_getdate(self):
        self.assertEqual(
            self.pg._format_default_value(
                "CONVERT(VARCHAR(23),CONVERT(DATETIME,GETDATE()),121)",
                "TEXT",
            ),
            "(CURRENT_TIMESTAMP)::text",
        )

    def test_datefromparts_literal_to_pg_date(self):
        self.assertEqual(
            self.pg._format_default_value("(DATEFROMPARTS(2020,1,1))", "DATE"),
            "'2020-01-01'::date",
        )

    def test_datefromparts_on_text_column(self):
        self.assertEqual(
            self.pg._format_default_value("DATEFROMPARTS(2019,12,31)", "TEXT"),
            "('2019-12-31'::date)::text",
        )

    def test_eomonth_getdate_maps_to_end_of_month(self):
        self.assertEqual(
            self.pg._format_default_value("(EOMONTH(GETDATE()))", "DATE"),
            "(date_trunc('month', (CURRENT_TIMESTAMP)::timestamp) + interval '1 month - 1 day')::date",
        )
        self.assertEqual(
            self.pg._format_default_value("EOMONTH(GETDATE(),0)", "TIMESTAMP WITHOUT TIME ZONE"),
            "(date_trunc('month', (CURRENT_TIMESTAMP)::timestamp) + interval '1 month - 1 day')::timestamp",
        )

    def test_dateadd_day_on_getdate(self):
        self.assertEqual(
            self.pg._format_default_value("DATEADD(day,-1,GETDATE())", "TIMESTAMP WITHOUT TIME ZONE"),
            "((CURRENT_TIMESTAMP)::timestamp + (-1 || ' days')::interval)",
        )

    def test_next_value_for_nextval_fragment(self):
        self.assertEqual(
            self.pg._format_default_value(
                "(NEXT VALUE FOR [dbo].[InvoiceSeq])",
                "BIGINT",
            ),
            "nextval('\"dbo\".\"InvoiceSeq\"'::regclass)",
        )

    def test_omits_unknown_parenthetic_expression(self):
        self.assertEqual(
            self.pg._format_default_value("(UNKNOWNFUNC(GETDATE()))", "DATE"),
            "",
        )
