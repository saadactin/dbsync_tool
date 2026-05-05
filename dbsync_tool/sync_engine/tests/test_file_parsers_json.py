from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from sync_engine.file_parsers import iter_records


class JsonParserTests(SimpleTestCase):
    def _source(self, relative_path: str, **kwargs):
        defaults = {
            "file_format": "json",
            "relative_path": relative_path,
            "encoding": "utf-8",
            "delimiter": ",",
            "has_header": True,
            "record_path": "",
            "sheet_name": "",
            "nested_strategy": "flatten",
            "flatten_separator": ".",
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_json_array_flatten(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "orders.json").write_text(
                '[{"id":1,"customer":{"name":"A"}},{"id":2,"customer":{"name":"B"}}]',
                encoding="utf-8",
            )
            source = self._source("orders.json", file_format="json")
            with override_settings(FILE_SYNC_ROOT=str(root)):
                headers, chunks, stats = iter_records(source, chunk_size=10)
                rows = [r for chunk in chunks for r in chunk]
            self.assertIn("customer.name", headers)
            self.assertEqual(rows[0]["customer.name"], "A")
            self.assertEqual(stats["rows_read"], 2)

    def test_jsonl_blob_mode(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "events.jsonl").write_text(
                '{"id":1,"payload":{"x":10}}\n{"id":2,"payload":{"x":20}}\n',
                encoding="utf-8",
            )
            source = self._source(
                "events.jsonl",
                file_format="jsonl",
                nested_strategy="json_blob",
            )
            with override_settings(FILE_SYNC_ROOT=str(root)):
                headers, chunks, _stats = iter_records(source, chunk_size=10)
                rows = [r for chunk in chunks for r in chunk]
            self.assertIn("payload", headers)
            self.assertIn('"x": 10', rows[0]["payload"])
