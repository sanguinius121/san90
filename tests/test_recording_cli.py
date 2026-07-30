from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.recording_fixtures import valid_fixture


class RecordingInspectionCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="san90-recording-cli-")
        self.directory = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "backend/tools/inspect_recording.py", *arguments],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_json_output_for_valid_and_truncated_file(self) -> None:
        valid_path = self.directory / "valid.san90rta"
        valid_path.write_bytes(valid_fixture())
        result = self.run_cli(str(valid_path), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertTrue(summary["valid"])
        self.assertTrue(summary["clean_finalization"])
        self.assertEqual(summary["format_version"], "1.0")
        self.assertEqual(summary["trace_batch_count"], 1)
        self.assertEqual(summary["trace_count"], 2)
        self.assertEqual(summary["configurations"][0]["config_id"], 1)

        truncated_path = self.directory / "truncated.san90rta.part"
        truncated_path.write_bytes(valid_fixture()[:-7])
        result = self.run_cli(str(truncated_path), "--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        summary = json.loads(result.stdout)
        self.assertFalse(summary["valid"])
        self.assertTrue(summary["recoverable"])
        self.assertIsNotNone(summary["first_invalid_offset"])

    def test_csv_trace_export(self) -> None:
        recording = self.directory / "export.san90rta"
        output = self.directory / "trace.csv"
        recording.write_bytes(valid_fixture())
        result = self.run_cli(
            str(recording),
            "--json",
            "--export-trace",
            "3:1",
            "--csv",
            str(output),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(summary["export"]["samples"], 4)
        with output.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 4)
        self.assertEqual(list(rows[0]), ["sample_index", "frequency_hz", "dbm"])
        self.assertEqual(rows[0]["sample_index"], "0")
        self.assertAlmostEqual(float(rows[0]["frequency_hz"]), 2_412_500_000.0)
        self.assertAlmostEqual(float(rows[0]["dbm"]), -96.25)

    def test_human_list_configs(self) -> None:
        recording = self.directory / "human.san90rta"
        recording.write_bytes(valid_fixture(multiple_configs=True))
        result = self.run_cli(str(recording), "--list-configs")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Configurations:", result.stdout)
        self.assertIn("config_id=2 generation=8", result.stdout)


if __name__ == "__main__":
    unittest.main()
