from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase

from sync_engine.flat_file_reader import read_csv_in_chunks


class FlatFileReaderTests(SimpleTestCase):
    def test_reads_headered_csv_in_chunks(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "data.csv"
            p.write_text("id,name\n1,A\n2,B\n3,C\n", encoding="utf-8")
            headers, chunks, stats = read_csv_in_chunks(p, chunk_size=2)
            all_chunks = list(chunks)
            self.assertEqual(headers, ["id", "name"])
            self.assertEqual(len(all_chunks), 2)
            self.assertEqual(all_chunks[0][0]["id"], "1")
            self.assertEqual(stats["rows_read"], 3)

    def test_no_header_generates_column_names(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "data.csv"
            p.write_text("1,A\n2,B\n", encoding="utf-8")
            headers, chunks, _stats = read_csv_in_chunks(p, has_header=False, chunk_size=10)
            rows = list(chunks)[0]
            self.assertEqual(headers, ["column_1", "column_2"])
            self.assertEqual(rows[1]["column_2"], "B")

    def test_empty_file_returns_empty_headers(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "data.csv"
            p.write_text("", encoding="utf-8")
            headers, chunks, _stats = read_csv_in_chunks(p)
            self.assertEqual(headers, [])
            self.assertEqual(list(chunks), [])

    def test_inconsistent_width_tracks_padding_and_truncation(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "data.csv"
            p.write_text("a,b\n1\n2,3,4\n", encoding="utf-8")
            headers, chunks, stats = read_csv_in_chunks(p, chunk_size=10)
            rows = list(chunks)[0]
            self.assertEqual(headers, ["a", "b"])
            self.assertEqual(rows[0]["b"], "")
            self.assertEqual(rows[1]["b"], "3")
            self.assertEqual(stats["rows_padded"], 1)
            self.assertEqual(stats["rows_truncated"], 1)

