#!/usr/bin/env python3
"""Short API-driven SAN-90 recording acceptance diagnostic."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.recording.reader import San90RtaReader


def request_json(base_url: str, path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()
    if args.duration <= 0 or args.duration > 30:
        parser.error("--duration must be in (0, 30] seconds")
    original = None
    try:
        source = request_json(args.base_url, "/api/analyzer/source")
        if source.get("source") != "san90":
            raise RuntimeError(f"backend source is {source.get('source')!r}, expected 'san90'")
        analyzer_before = request_json(args.base_url, "/api/analyzer/status")
        original = request_json(args.base_url, "/api/analyzer/recording/config")
        configured = {
            "mode": "fixed",
            "duration_s": args.duration,
            "file_size_limit_bytes": original["file_size_limit_bytes"],
            "free_disk_reserve_bytes": original["free_disk_reserve_bytes"],
            "output_directory": original["output_directory"],
            "file_prefix": "SAN90_ACCEPTANCE",
        }
        request_json(
            args.base_url,
            "/api/analyzer/recording/config",
            method="PUT",
            body=configured,
        )
        request_json(args.base_url, "/api/analyzer/recording/start", method="POST")
        deadline = time.monotonic() + args.timeout
        status = {}
        while time.monotonic() < deadline:
            status = request_json(args.base_url, "/api/analyzer/recording/status")
            if status.get("state") in {"completed", "failed"}:
                break
            time.sleep(0.2)
        if status.get("state") != "completed":
            raise RuntimeError(f"recording did not complete cleanly: {status}")
        path = Path(status["final_file_path"])
        report = San90RtaReader(path).validate()
        analyzer_after = request_json(args.base_url, "/api/analyzer/status")
        duration = max(float(status["elapsed_s"]), 1e-9)
        metrics = {
            "source": source["source"],
            "device": (
                report.session_metadata.get("device")
                if report.session_metadata is not None
                else None
            ),
            "recording_path": str(path),
            "duration_s": duration,
            "file_size_bytes": path.stat().st_size,
            "average_raw_MB_s": report.raw_sample_count / duration / 1e6,
            "trace_count": report.trace_count,
            "batch_count": report.trace_batch_count,
            "point_count": analyzer_after.get("point_count"),
            "config_count": report.config_record_count,
            "queue_high_water_bytes": status["queue_high_water_bytes"],
            "queue_high_water_items": status["queue_high_water_items"],
            "rejected_batches": status["rejected_batches"],
            "gap_count": report.gap_count,
            "lost_trace_count": report.lost_trace_count,
            "reader_valid": not report.issues,
            "reader_issues": [issue.to_dict() for issue in report.issues],
            "acquisition_errors_before": analyzer_before.get("acquisition_errors"),
            "acquisition_errors_after": analyzer_after.get("acquisition_errors"),
            "timeouts_before": analyzer_before.get("timeouts"),
            "timeouts_after": analyzer_after.get("timeouts"),
            "stop_reason": status["stop_reason"],
        }
        print(json.dumps(metrics, indent=2, sort_keys=True))
        return 0 if not report.issues else 1
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as error:
        print(f"recording acceptance failed: {error}", file=sys.stderr)
        return 1
    finally:
        if original is not None:
            restore = {
                key: original[key]
                for key in (
                    "mode",
                    "duration_s",
                    "file_size_limit_bytes",
                    "free_disk_reserve_bytes",
                    "output_directory",
                    "file_prefix",
                )
            }
            try:
                request_json(
                    args.base_url,
                    "/api/analyzer/recording/config",
                    method="PUT",
                    body=restore,
                )
            except Exception as error:
                print(f"warning: unable to restore recording configuration: {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
