#!/usr/bin/env python3
"""Standalone validator/preview receiver for SAN-90 GRAY8 waterfall images."""

from __future__ import annotations

import argparse
from collections import deque
import json
import math
import sys
import time
from pathlib import Path
from typing import Sequence

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ai_stream.protocol import validate_multipart


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", default="tcp://127.0.0.1:5557")
    parser.add_argument("--save-dir", type=Path)
    parser.add_argument("--save-every", type=int, default=10)
    parser.add_argument("--max-files", type=int, default=20)
    parser.add_argument("--stop-after", type=int, help="Exit after receiving N valid images")
    parser.add_argument("--display", action="store_true")
    parser.add_argument(
        "--auto-labelme",
        nargs="?",
        const=True,
        default=False,
        type=_parse_bool,
        metavar="BOOL",
        help="Write automatic LabelMe rectangle candidates (default: false)",
    )
    parser.add_argument(
        "--threshold-db",
        type=float,
        default=6.0,
        help="Signal threshold in dB above the per-frequency noise floor (default: 6)",
    )
    parser.add_argument(
        "--detection-mode",
        choices=("transient", "persistent", "hybrid"),
        default="transient",
        help="Auto-label detector: transient, persistent, or hybrid (default: transient)",
    )
    parser.add_argument(
        "--persistent-min-duty",
        type=float,
        default=0.60,
        help="Minimum fraction of image rows occupied by a persistent signal (default: 0.60)",
    )
    parser.add_argument(
        "--auto-label",
        default="AUTO_CANDIDATE",
        help="Placeholder label for automatic rectangles (default: AUTO_CANDIDATE)",
    )
    args = parser.parse_args(argv)
    if args.save_every < 1 or args.max_files < 1:
        parser.error("--save-every and --max-files must be positive")
    if args.stop_after is not None and args.stop_after < 1:
        parser.error("--stop-after must be positive")
    if not math.isfinite(args.threshold_db) or args.threshold_db <= 0:
        parser.error("--threshold-db must be finite and positive")
    if not math.isfinite(args.persistent_min_duty) or not 0 < args.persistent_min_duty <= 1:
        parser.error("--persistent-min-duty must be finite and in the interval (0, 1]")
    if not args.auto_label.strip():
        parser.error("--auto-label must not be empty")
    return args


def _connected_components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """Return sparse 8-connected components as x0, y0, x1, y1, area."""
    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=np.bool_)
    components: list[tuple[int, int, int, int, int]] = []
    for start_y, start_x in np.argwhere(mask):
        y = int(start_y)
        x = int(start_x)
        if visited[y, x]:
            continue
        visited[y, x] = True
        pending = deque([(x, y)])
        min_x = max_x = x
        min_y = max_y = y
        area = 0
        while pending:
            current_x, current_y = pending.popleft()
            area += 1
            min_x = min(min_x, current_x)
            max_x = max(max_x, current_x)
            min_y = min(min_y, current_y)
            max_y = max(max_y, current_y)
            for neighbor_y in range(max(0, current_y - 1), min(height, current_y + 2)):
                for neighbor_x in range(max(0, current_x - 1), min(width, current_x + 2)):
                    if mask[neighbor_y, neighbor_x] and not visited[neighbor_y, neighbor_x]:
                        visited[neighbor_y, neighbor_x] = True
                        pending.append((neighbor_x, neighbor_y))
        components.append((min_x, min_y, max_x + 1, max_y + 1, area))
    return components


def detect_candidate_boxes(
    image: np.ndarray,
    metadata: dict[str, object],
    *,
    threshold_db: float,
    padding: int = 4,
    detection_mode: str = "transient",
    persistent_min_duty: float = 0.60,
) -> list[tuple[int, int, int, int]]:
    """Detect transient bursts, persistent emissions, or both.

    Transient mode compares every pixel with the 15th time percentile of its
    frequency column. Persistent mode compares the time-median frequency
    profile with a rolling local frequency floor, then requires the selected
    columns to exceed that floor for ``persistent_min_duty`` of all rows.
    """
    if image.ndim != 2 or image.dtype != np.uint8:
        raise ValueError("auto LabelMe detection requires a 2-D uint8 image")
    db_per_gray_level = float(metadata["db_per_gray_level"])
    if not math.isfinite(db_per_gray_level) or db_per_gray_level <= 0:
        raise ValueError("metadata db_per_gray_level must be finite and positive")
    if detection_mode not in {"transient", "persistent", "hybrid"}:
        raise ValueError("detection_mode must be transient, persistent, or hybrid")
    if not math.isfinite(persistent_min_duty) or not 0 < persistent_min_duty <= 1:
        raise ValueError("persistent_min_duty must be finite and in the interval (0, 1]")
    threshold_codes = threshold_db / db_per_gray_level
    image_codes = image.astype(np.float32)
    boxes: list[tuple[int, int, int, int]] = []
    if detection_mode in {"transient", "hybrid"}:
        noise_codes = np.percentile(image, 15.0, axis=0)
        transient_mask = image_codes >= noise_codes[np.newaxis, :] + threshold_codes
        boxes.extend(_boxes_from_transient_mask(transient_mask))
    if detection_mode in {"persistent", "hybrid"}:
        boxes.extend(
            _persistent_boxes(
                image_codes,
                threshold_codes=threshold_codes,
                minimum_duty=persistent_min_duty,
            )
        )
    boxes = _merge_same_burst_fragments(boxes)
    height, width = image.shape

    padded_boxes = {
        (
            max(0, x0 - padding),
            max(0, y0 - padding),
            min(width, x1 + padding),
            min(height, y1 + padding),
        )
        for x0, y0, x1, y1 in boxes
    }
    return sorted(padded_boxes, key=lambda box: (box[1], box[0], box[3], box[2]))


def _boxes_from_transient_mask(raw_mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Extract individual burst boxes from a sparse transient mask."""
    padded = np.pad(raw_mask, 1, mode="constant", constant_values=False)
    neighbor_count = np.zeros(raw_mask.shape, dtype=np.uint8)
    for y_offset in range(3):
        for x_offset in range(3):
            neighbor_count += padded[
                y_offset : y_offset + raw_mask.shape[0],
                x_offset : x_offset + raw_mask.shape[1],
            ]
    mask = raw_mask & (neighbor_count >= 2)

    boxes: list[tuple[int, int, int, int]] = []
    for x0, y0, x1, y1, area in _connected_components(mask):
        # Short FHSS bursts may be only one or two rows high. Requiring both a
        # modest horizontal extent and area rejects isolated noise while
        # retaining those valid individual emissions.
        if area >= 6 and x1 - x0 >= 4:
            boxes.append((x0, y0, x1, y1))
    return boxes


def _persistent_boxes(
    image_codes: np.ndarray,
    *,
    threshold_codes: float,
    minimum_duty: float,
) -> list[tuple[int, int, int, int]]:
    """Find emissions persistent in time but locally elevated in frequency."""
    height, width = image_codes.shape
    profile = np.median(image_codes, axis=0)
    window_width = min(321, width if width % 2 else width - 1)
    half_window = window_width // 2
    padded_profile = np.pad(profile, (half_window, half_window), mode="reflect")
    windows = np.lib.stride_tricks.sliding_window_view(padded_profile, window_width)
    local_floor = np.percentile(windows, 15.0, axis=1)
    above_floor = image_codes >= local_floor[np.newaxis, :] + threshold_codes
    persistent_columns = np.mean(above_floor, axis=0) >= minimum_duty

    boxes: list[tuple[int, int, int, int]] = []
    for x0, x1 in _true_runs(persistent_columns, maximum_gap=2):
        active_rows = np.flatnonzero(np.any(above_floor[:, x0:x1], axis=1))
        area = int(np.count_nonzero(above_floor[:, x0:x1]))
        if x1 - x0 < 4 or area < 6 or active_rows.size == 0:
            continue
        boxes.append((x0, int(active_rows[0]), x1, int(active_rows[-1]) + 1))
    return boxes


def _true_runs(values: np.ndarray, *, maximum_gap: int = 0) -> list[tuple[int, int]]:
    indexes = np.flatnonzero(values)
    if indexes.size == 0:
        return []
    runs: list[tuple[int, int]] = []
    start = previous = int(indexes[0])
    for raw_index in indexes[1:]:
        index = int(raw_index)
        if index - previous > maximum_gap + 1:
            runs.append((start, previous + 1))
            start = index
        previous = index
    runs.append((start, previous + 1))
    return runs


def _merge_same_burst_fragments(
    boxes: Sequence[tuple[int, int, int, int]],
    *,
    maximum_empty_gap: int = 2,
) -> list[tuple[int, int, int, int]]:
    """Join threshold-fragmented pieces without bridging separate time bursts."""
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        result: list[tuple[int, int, int, int]] = []
        while merged:
            current = merged.pop()
            for index, other in enumerate(merged):
                horizontal_gap = max(0, max(current[0], other[0]) - min(current[2], other[2]))
                vertical_gap = max(0, max(current[1], other[1]) - min(current[3], other[3]))
                overlaps_in_time = current[1] < other[3] and other[1] < current[3]
                overlaps_in_frequency = current[0] < other[2] and other[0] < current[2]
                if (overlaps_in_time and horizontal_gap <= maximum_empty_gap) or (
                    overlaps_in_frequency and vertical_gap <= maximum_empty_gap
                ):
                    current = (
                        min(current[0], other[0]),
                        min(current[1], other[1]),
                        max(current[2], other[2]),
                        max(current[3], other[3]),
                    )
                    merged.pop(index)
                    changed = True
                    break
            result.append(current)
        merged = result
    return merged


def build_labelme_document(
    image_path: str,
    image: np.ndarray,
    boxes: Sequence[tuple[int, int, int, int]],
    *,
    label: str,
    threshold_db: float,
    detection_mode: str = "transient",
) -> dict[str, object]:
    height, width = image.shape
    return {
        "version": "7.0.4",
        "flags": {"san90_auto_generated": True},
        "shapes": [
            {
                "label": label,
                "points": [[float(x0), float(y0)], [float(x1), float(y1)]],
                "group_id": None,
                "description": (
                    f"Auto-generated using {detection_mode} detection at "
                    f"{threshold_db:g} dB above the local noise floor"
                ),
                "shape_type": "rectangle",
                "flags": {"auto_generated": True},
                "mask": None,
            }
            for x0, y0, x1, y1 in boxes
        ],
        "imagePath": image_path,
        "imageData": None,
        "imageHeight": height,
        "imageWidth": width,
    }


def save_preview(
    directory: Path,
    image: np.ndarray,
    metadata: dict[str, object],
    max_files: int,
    *,
    auto_labelme: bool = False,
    threshold_db: float = 6.0,
    auto_label: str = "AUTO_CANDIDATE",
    detection_mode: str = "transient",
    persistent_min_duty: float = 0.60,
) -> None:
    from PIL import Image

    directory.mkdir(parents=True, exist_ok=True)
    stem = f"received_san90_gray8_{int(metadata['sequence']):012d}_{int(metadata['timestamp_ns'])}"
    image_path = directory / f"{stem}.png"
    json_path = directory / f"{stem}.json"
    Image.fromarray(image, mode="L").save(image_path, format="PNG")
    if auto_labelme:
        boxes = detect_candidate_boxes(
            image,
            metadata,
            threshold_db=threshold_db,
            detection_mode=detection_mode,
            persistent_min_duty=persistent_min_duty,
        )
        labelme = build_labelme_document(
            image_path.name,
            image,
            boxes,
            label=auto_label,
            threshold_db=threshold_db,
            detection_mode=detection_mode,
        )
        json_path.write_text(json.dumps(labelme, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        json_path.with_suffix(".meta.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    else:
        json_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    files = sorted(directory.glob("received_san90_gray8_*.png"), key=lambda path: path.stat().st_mtime_ns)
    for path in files[:-max_files]:
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)
        path.with_suffix(".meta.json").unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    try:
        import zmq
    except ImportError:
        print("pyzmq is required: python3 -m pip install -r backend/requirements.txt", file=sys.stderr)
        return 2
    cv2 = None
    if args.display:
        try:
            import cv2 as cv2_module
            cv2 = cv2_module
        except ImportError:
            print("--display requires optional OpenCV; receiving will continue without a window", file=sys.stderr)
    context = zmq.Context.instance()
    socket = context.socket(zmq.PULL)
    socket.setsockopt(zmq.RCVHWM, 2)
    socket.connect(args.connect)
    received = 0
    reported_at = time.monotonic()
    reported_count = 0
    print(f"Receiving SAN-90 GRAY8 images from {args.connect}")
    try:
        while True:
            parts = socket.recv_multipart()
            if len(parts) != 2:
                print(f"Rejected malformed message with {len(parts)} parts", file=sys.stderr)
                continue
            try:
                metadata, image = validate_multipart(parts[0], parts[1])
            except ValueError as error:
                print(f"Rejected malformed message: {error}", file=sys.stderr)
                continue
            received += 1
            if args.save_dir is not None and received % args.save_every == 0:
                save_preview(
                    args.save_dir,
                    image,
                    metadata,
                    args.max_files,
                    auto_labelme=args.auto_labelme,
                    threshold_db=args.threshold_db,
                    auto_label=args.auto_label,
                    detection_mode=args.detection_mode,
                    persistent_min_duty=args.persistent_min_duty,
                )
            if args.stop_after is not None and received >= args.stop_after:
                print(f"Received {received} valid images; stopping.")
                break
            if cv2 is not None:
                cv2.imshow("SAN-90 GRAY8 waterfall", image)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
            now = time.monotonic()
            if now - reported_at >= 1.0:
                count = received - reported_count
                duration_ms = (
                    int(metadata["capture_end_timestamp_ns"]) - int(metadata["capture_start_timestamp_ns"])
                ) / 1e6
                print(
                    f"sequence={metadata['sequence']} receive_fps={count/(now-reported_at):.2f} "
                    f"payload={len(parts[1])} profile={metadata['power_profile']} "
                    f"limits=[{metadata['power_min_dbm']},{metadata['power_max_dbm']}]dBm "
                    f"center={float(metadata['center_frequency_hz'])/1e9:.9f}GHz "
                    f"start/stop={float(metadata['start_frequency_hz'])/1e9:.9f}/"
                    f"{float(metadata['stop_frequency_hz'])/1e9:.9f}GHz duration={duration_ms:.3f}ms "
                    f"clip_low/high={float(metadata['clipped_low_ratio']):.6f}/"
                    f"{float(metadata['clipped_high_ratio']):.6f} "
                    f"min/max={float(metadata['image_min_dbm']):.2f}/{float(metadata['image_max_dbm']):.2f}dBm"
                )
                reported_at = now
                reported_count = received
    except KeyboardInterrupt:
        pass
    finally:
        socket.close(linger=0)
        if cv2 is not None:
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
