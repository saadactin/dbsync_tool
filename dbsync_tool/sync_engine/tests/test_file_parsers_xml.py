from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from sync_engine.exceptions import FlatFileReadError
from sync_engine.file_parsers import iter_records


class XmlParserTests(SimpleTestCase):
    def _source(self, relative_path: str, **kwargs):
        defaults = {
            "file_format": "xml",
            "relative_path": relative_path,
            "encoding": "utf-8",
            "delimiter": ",",
            "has_header": True,
            "record_path": "/root/items/item",
            "sheet_name": "",
            "nested_strategy": "flatten",
            "flatten_separator": ".",
        }
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_xml_record_path_parses_rows(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "items.xml").write_text(
                "<root><items><item id='1'><name>A</name></item><item id='2'><name>B</name></item></items></root>",
                encoding="utf-8",
            )
            source = self._source("items.xml")
            with override_settings(FILE_SYNC_ROOT=str(root)):
                headers, chunks, stats = iter_records(source, chunk_size=10)
                rows = [r for chunk in chunks for r in chunk]
            self.assertIn("@id", headers)
            self.assertEqual(rows[0]["name"], "A")
            self.assertEqual(stats["rows_read"], 2)

    def test_xml_rejects_doctype(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.xml").write_text(
                "<!DOCTYPE root [<!ENTITY xxe SYSTEM 'file:///etc/passwd'>]><root><items><item><name>x</name></item></items></root>",
                encoding="utf-8",
            )
            source = self._source("bad.xml")
            with override_settings(FILE_SYNC_ROOT=str(root)):
                with self.assertRaises(FlatFileReadError):
                    _headers, chunks, _stats = iter_records(source, chunk_size=10)
                    list(chunks)
