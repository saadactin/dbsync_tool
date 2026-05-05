from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from sync_engine.file_parsers import iter_records


class XlsxParserTests(SimpleTestCase):
    def _source(self, relative_path: str, **kwargs):
        defaults = {
            "file_format": "xlsx",
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

    def test_xlsx_reads_first_sheet(self):
        try:
            from openpyxl import Workbook
        except Exception:
            self.skipTest("openpyxl not installed")
            return

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = Workbook()
            ws = book.active
            ws.title = "Data"
            ws.append(["id", "name"])
            ws.append([1, "Alice"])
            ws.append([2, "Bob"])
            book.save(root / "book.xlsx")

            source = self._source("book.xlsx", sheet_name="Data")
            with override_settings(FILE_SYNC_ROOT=str(root)):
                headers, chunks, stats = iter_records(source, chunk_size=10)
                rows = [r for chunk in chunks for r in chunk]

            self.assertEqual(headers, ["id", "name"])
            self.assertEqual(rows[1]["name"], "Bob")
            self.assertEqual(stats["rows_read"], 2)
