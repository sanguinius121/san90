#!/usr/bin/env python3
"""Inspect and validate a SAN-90 native RTA recording."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.recording.models import TraceBatchRecord
from backend.recording.reader import San90RtaReader


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable JSON")
    parser.add_argument("--no-payload-crc", action="store_true", help="Skip payload CRC verification")
    parser.add_argument("--list-configs", action="store_true", help="Print detailed configuration records")
    parser.add_argument(
        "--export-trace",
        metavar="RECORD_INDEX:TRACE_INDEX",
        help="Select one trace batch record and trace within it",
    )
    parser.add_argument("--csv", type=Path, help="CSV output used with --export-trace")
    args = parser.parse_args()
    if bool(args.export_trace) != bool(args.csv):
        parser.error("--export-trace and --csv must be supplied together")
    return args


def _timestamp(unix_ns: int | None) -> str | None:
    if unix_ns is None:
        return None
    return datetime.fromtimestamp(unix_ns / 1e9, tz=timezone.utc).isoformat()


def _selection(value: str) -> tuple[int, int]:
    try:
        record_text, trace_text = value.split(":", 1)
        record_index, trace_index = int(record_text), int(trace_text)
    except (ValueError, AttributeError) as error:
        raise ValueError("trace selection must be RECORD_INDEX:TRACE_INDEX") from error
    if record_index <= 0 or trace_index < 0:
        raise ValueError("record index must be positive and trace index must be non-negative")
    return record_index, trace_index


def export_trace(reader: San90RtaReader, selection: str, output: Path) -> dict[str, int | str]:
    record_index, trace_index = _selection(selection)
    batch: TraceBatchRecord | None = None
    for record in reader.iter_records():
        if isinstance(record, TraceBatchRecord) and record.prefix.record_index == record_index:
            batch = record
            break
    if batch is None:
        raise ValueError(f"record index {record_index} is not a trace batch")
    dbm = reader.reconstruct_dbm(batch, trace_index)
    frequencies = reader.reconstruct_frequency_axis(batch)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("sample_index", "frequency_hz", "dbm"))
        for index, (frequency, power) in enumerate(zip(frequencies, dbm, strict=True)):
            writer.writerow((index, format(float(frequency), ".17g"), format(float(power), ".9g")))
    return {
        "record_index": record_index,
        "trace_index": trace_index,
        "samples": batch.frame_width,
        "csv": str(output),
    }


def _print_human(summary: dict, *, list_configs: bool) -> None:
    print(f"Format: {summary['format_version']}")
    print(f"Session UUID: {summary['session_uuid']}")
    print(f"File size: {summary['file_size']} bytes")
    state = "clean" if summary["clean_finalization"] and summary["valid"] else (
        "incomplete/recoverable" if summary["recoverable"] else "invalid"
    )
    print(f"State: {state}")
    print(f"First invalid offset: {summary['first_invalid_offset']}")
    print(f"Created: {_timestamp(summary['creation_unix_ns'])}")
    print(f"Stopped: {_timestamp(summary['stop_unix_ns'])}")
    print(f"Duration: {summary['duration_ns']} ns")
    print(f"Stop reason: {summary['stop_reason']}")
    print(
        "Counts: "
        f"records={summary['record_count']} batches={summary['trace_batch_count']} "
        f"traces={summary['trace_count']} samples={summary['raw_sample_count']} "
        f"gaps={summary['gap_count']} lost={summary['lost_trace_count']}"
    )
    print(f"Sequence: {summary['first_sequence']}..{summary['last_sequence']}")
    session = summary.get("session_metadata") or {}
    print(f"Device: {json.dumps(session.get('device'), ensure_ascii=False, sort_keys=True)}")
    print(f"Discontinuities: {json.dumps(summary['discontinuities'], ensure_ascii=False)}")
    if list_configs:
        print("Configurations:")
        for config in summary["configurations"]:
            print(
                "  "
                f"config_id={config['config_id']} generation={config['configuration_generation']} "
                f"range={config['start_frequency_hz']}..{config['stop_frequency_hz']} Hz "
                f"points={config['frame_width']} RBW={config['rbw_hz']} Hz"
            )
    if summary["issues"]:
        print("Issues:")
        for issue in summary["issues"]:
            print(
                f"  {issue['code']} offset={issue['offset']} "
                f"checksum={issue['checksum_kind']}: {issue['message']}"
            )


def main() -> int:
    args = parse_args()
    reader = San90RtaReader(args.file)
    try:
        report = reader.validate(verify_payload_crc=not args.no_payload_crc)
        summary = report.to_dict()
        if args.export_trace:
            summary["export"] = export_trace(reader, args.export_trace, args.csv)
    except (OSError, ValueError) as error:
        if args.as_json:
            print(json.dumps({"path": str(args.file), "error": str(error)}, sort_keys=True))
        else:
            print(f"Error: {error}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        _print_human(summary, list_configs=args.list_configs)
        if "export" in summary:
            print(f"Export: {summary['export']}")
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
