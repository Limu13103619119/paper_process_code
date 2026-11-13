import csv
import tempfile
import unittest
from pathlib import Path

from process import write_summary_report


class SummaryReportTests(unittest.TestCase):
    def test_writes_headers_and_result_rows(self):
        result = {
            "paper_file": "paper_01.pdf",
            "status": "matched",
            "author_passed": True,
            "target_author": "A. Researcher",
            "matched_citation_count": 1,
            "matched_citations": "A useful paper title",
            "error": "",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = write_summary_report([result], output_dir=temp_dir)

            self.assertEqual(Path(report_path).name, "summary.csv")
            with open(report_path, newline="", encoding="utf-8-sig") as csv_file:
                rows = list(csv.DictReader(csv_file))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["paper_file"], "paper_01.pdf")
        self.assertEqual(rows[0]["status"], "matched")
        self.assertEqual(rows[0]["author_passed"], "True")
        self.assertEqual(rows[0]["matched_citation_count"], "1")
        self.assertEqual(rows[0]["matched_citations"], "A useful paper title")


if __name__ == "__main__":
    unittest.main()
