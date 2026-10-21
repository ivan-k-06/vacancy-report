import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from report import (fetch_vacancies, normalize_vacancy, render_markdown,
                    select_vacancies, summarize, unique_vacancies)


class ReportTests(unittest.TestCase):
    def test_pipeline_preserves_input_and_removes_duplicates(self):
        raw = [{"id": 1, "title": "PYTHON intern", "salary": ""}] * 2
        original = copy.deepcopy(raw)
        items = unique_vacancies([normalize_vacancy(item) for item in raw])
        self.assertEqual(len(select_vacancies(items, "python")), 1)
        self.assertEqual(select_vacancies(items, "java"), [])
        self.assertEqual(raw, original)

    def test_summary_groups_and_preserves_salary_text(self):
        items = [normalize_vacancy({"id": index, "title": "Developer",
                 "company_name": "Demo", "category": "Software Development",
                 "job_type": "full_time", "salary": salary})
                 for index, salary in enumerate(["$80,000 - $100,000 yearly", None, " "]) ]
        result = summarize(items)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["companies"], [("Demo", 3)])
        self.assertEqual(result["categories"], [("Software Development", 3)])
        self.assertEqual(result["job_types"], [("full_time", 3)])
        self.assertEqual(result["salary_count"], 1)
        self.assertEqual(result["vacancies"][0]["salary"], "$80,000 - $100,000 yearly")

    def test_empty_report(self):
        self.assertIn("По заданному фильтру вакансий нет", render_markdown(summarize([])))

    def test_source_links_and_markdown_escaping(self):
        item = normalize_vacancy({"id": 1, "title": "A|B\n<script>",
                                 "url": "https://remotive.com/remote-jobs/test/1"})
        text = render_markdown(summarize([item]))
        self.assertIn(r"A\|B &lt;script&gt;", text)
        self.assertIn("[Remotive](<https://remotive.com/remote-jobs/test/1>)", text)
        item["url"] = "javascript:alert(1)"
        self.assertNotIn("javascript:", render_markdown(summarize([item])))

    def test_cli_example_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.md"
            result = subprocess.run([sys.executable, "report.py", "--input", "example.json",
                                     "--keyword", "python", "--output", str(output)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Вакансий: 3", output.read_text())
            bad = Path(directory) / "bad.json"
            bad.write_text('{"items": []}')
            result = subprocess.run([sys.executable, "report.py", "--input", str(bad)], capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("jobs", result.stderr.decode())


class ApiTests(unittest.TestCase):
    def test_api_request_and_response_without_credentials(self):
        payload = {"jobs": [{"id": 1, "title": "Python developer"}]}
        with patch("report.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as open_url:
            self.assertEqual(fetch_vacancies("python developer"), payload)
        request = open_url.call_args.args[0]
        parsed = urlsplit(request.full_url)
        self.assertEqual(parsed.hostname, "remotive.com")
        self.assertEqual(parse_qs(parsed.query), {"search": ["python developer"], "limit": ["100"]})
        self.assertFalse(request.has_header("Authorization"))
        self.assertEqual(open_url.call_args.kwargs["timeout"], 30)

    def test_network_failure(self):
        with patch("report.urlopen", side_effect=URLError("offline")):
            with self.assertRaises(URLError):
                fetch_vacancies("python")

    def test_rate_limit_and_forbidden(self):
        for code in (403, 429):
            with self.subTest(code=code):
                error = HTTPError("https://remotive.com/api/remote-jobs", code, "Error", {}, None)
                with patch("report.urlopen", side_effect=error):
                    with self.assertRaisesRegex(ValueError, str(code)):
                        fetch_vacancies("python")
