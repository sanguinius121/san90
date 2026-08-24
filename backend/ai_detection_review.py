"""Bounded realtime subscriber for the annotated AI detection review channel.

Consumes the [json metadata, raw JPEG, annotated JPEG] multipart stream
published by tools/yolo_detection.py's --review-publish channel (default
tcp://127.0.0.1:5555) and exposes a latest-only in-memory snapshot for the
AI review panel, plus a save-to-disk action.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Literal

import zmq
import zmq.asyncio

logger = logging.getLogger("san90.ai_detection_review")

DEFAULT_ENDPOINT = "tcp://127.0.0.1:5555"
MAX_METADATA_BYTES = 256 * 1024
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_DETECTIONS = 128
JPEG_MAGIC = b"\xff\xd8"


def _validate_review_detections(raw_detections: Any) -> list[dict[str, Any]]:
    """Validate the [{class_id, label, confidence, bbox}] shape sent by
    tools/yolo_detection.py's review channel. Unlike the lightweight 5558
    detections channel, boxes here carry pixel bbox coordinates rather than
    a per-box frequency range (frequency is conveyed via the aggregate
    label_freq_ranges_hz field instead)."""
    if not isinstance(raw_detections, list):
        raise ValueError("AI review detections must be a list")
    if len(raw_detections) > MAX_DETECTIONS:
        raise ValueError("AI review detections payload contains too many entries")
    detections: list[dict[str, Any]] = []
    for raw in raw_detections:
        if not isinstance(raw, Mapping):
            raise ValueError("AI review detection entry must be an object")
        label = raw.get("label")
        confidence = raw.get("confidence")
        bbox = raw.get("bbox")
        if not isinstance(label, str) or not label.strip() or len(label) > 64:
            raise ValueError("AI review detection label is invalid")
        if not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)):
            raise ValueError("AI review detection confidence must be finite")
        confidence_value = float(confidence)
        if not 0.0 <= confidence_value <= 1.0:
            raise ValueError("AI review detection confidence must be between zero and one")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not all(
            isinstance(value, (int, float)) and math.isfinite(float(value)) for value in bbox
        ):
            raise ValueError("AI review detection bbox must contain 4 finite numbers")
        detection: dict[str, Any] = {
            "label": label.strip(),
            "confidence": confidence_value,
            "bbox": [float(value) for value in bbox],
        }
        if isinstance(raw.get("class_id"), int):
            detection["class_id"] = raw["class_id"]
        detections.append(detection)
    return detections


def _finite_frequency_range(raw: Any) -> tuple[float, float]:
    if not isinstance(raw, Mapping):
        raise ValueError("AI review label_freq_ranges_hz entry must be an object")
    start = raw.get("start_hz")
    stop = raw.get("stop_hz")
    if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in (start, stop)):
        raise ValueError("AI review label_freq_ranges_hz entry must be finite")
    start_value, stop_value = float(start), float(stop)
    if stop_value <= start_value:
        raise ValueError("AI review label_freq_ranges_hz entry must have stop_hz > start_hz")
    return start_value, stop_value


def normalize_ai_review_payload(
    metadata_bytes: bytes,
    raw_image: bytes,
    annotated_image: bytes,
) -> dict[str, Any]:
    """Validate one review-channel message and return its normalized fields."""
    if len(metadata_bytes) > MAX_METADATA_BYTES:
        raise ValueError("AI review metadata is too large")
    if len(raw_image) > MAX_IMAGE_BYTES or len(annotated_image) > MAX_IMAGE_BYTES:
        raise ValueError("AI review image payload is too large")
    if not raw_image.startswith(JPEG_MAGIC) or not annotated_image.startswith(JPEG_MAGIC):
        raise ValueError("AI review images must be JPEG")
    try:
        data = json.loads(metadata_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("AI review metadata is not valid UTF-8 JSON") from error
    if not isinstance(data, dict):
        raise ValueError("AI review metadata JSON must be an object")

    normalized: dict[str, Any] = {
        "detections": _validate_review_detections(data.get("detections")),
        "received_at_ns": time.time_ns(),
    }
    sequence = data.get("sequence")
    if isinstance(sequence, int) and sequence >= 0:
        normalized["sequence"] = sequence
    timestamp_ns = data.get("timestamp_ns")
    if isinstance(timestamp_ns, int) and timestamp_ns >= 0:
        normalized["timestamp_ns"] = timestamp_ns
    generated_at = data.get("generated_at")
    if isinstance(generated_at, (int, float)) and math.isfinite(float(generated_at)):
        normalized["generated_at"] = float(generated_at)

    width = data.get("width")
    height = data.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("AI review metadata width/height are invalid")

    numeric_fields = ("center_frequency_hz", "start_frequency_hz", "stop_frequency_hz")
    if not all(
        isinstance(data.get(name), (int, float)) and math.isfinite(float(data[name]))
        for name in numeric_fields
    ):
        raise ValueError("AI review metadata frequency fields are invalid")

    label_freq_ranges_hz: dict[str, tuple[float, float]] = {}
    raw_ranges = data.get("label_freq_ranges_hz")
    if raw_ranges is not None:
        if not isinstance(raw_ranges, Mapping):
            raise ValueError("AI review label_freq_ranges_hz must be an object")
        for label, value in raw_ranges.items():
            label_freq_ranges_hz[str(label)] = _finite_frequency_range(value)

    normalized.update(
        {
            "width": width,
            "height": height,
            "center_frequency_hz": float(data["center_frequency_hz"]),
            "start_frequency_hz": float(data["start_frequency_hz"]),
            "stop_frequency_hz": float(data["stop_frequency_hz"]),
            "content_type": "image/jpeg",
            "label_freq_ranges_hz": label_freq_ranges_hz,
            "raw_image": bytes(raw_image),
            "annotated_image": bytes(annotated_image),
        }
    )
    optional_power = (
        "power_min_dbm",
        "power_max_dbm",
        "power_range_db",
        "db_per_gray_level",
    )
    present = [name in data for name in optional_power]
    if any(present):
        if not all(present) or not all(
            isinstance(data[name], (int, float)) and math.isfinite(float(data[name]))
            for name in optional_power
        ):
            raise ValueError("AI review power-range metadata is incomplete or invalid")
        low = float(data["power_min_dbm"])
        high = float(data["power_max_dbm"])
        if high <= low:
            raise ValueError("AI review power range must be increasing")
        normalized.update({name: float(data[name]) for name in optional_power})
    generation = data.get("power_range_generation")
    if generation is not None:
        if not isinstance(generation, int) or generation < 0:
            raise ValueError("AI review power-range generation is invalid")
        normalized["power_range_generation"] = generation
    return normalized


@dataclass(frozen=True, slots=True)
class AiDetectionReviewSnapshot:
    sequence: int | None
    timestamp_ns: int | None
    generated_at: float | None
    received_at_ns: int
    width: int
    height: int
    center_frequency_hz: float
    start_frequency_hz: float
    stop_frequency_hz: float
    power_min_dbm: float | None
    power_max_dbm: float | None
    power_range_db: float | None
    db_per_gray_level: float | None
    power_range_generation: int | None
    content_type: str
    detections: list[dict[str, Any]]
    label_freq_ranges_hz: dict[str, tuple[float, float]]
    raw_image: bytes
    annotated_image: bytes

    def image_for(self, variant: Literal["raw", "annotated"]) -> bytes:
        return self.raw_image if variant == "raw" else self.annotated_image

    def status(self) -> dict[str, Any]:
        return {
            "available": True,
            "reason": None,
            "sequence": self.sequence,
            "timestamp_ns": self.timestamp_ns,
            "width": self.width,
            "height": self.height,
            "center_frequency_hz": self.center_frequency_hz,
            "frequency_start_hz": self.start_frequency_hz,
            "frequency_stop_hz": self.stop_frequency_hz,
            "power_min_dbm": self.power_min_dbm,
            "power_max_dbm": self.power_max_dbm,
            "power_range_db": self.power_range_db,
            "db_per_gray_level": self.db_per_gray_level,
            "power_range_generation": self.power_range_generation,
            "content_type": self.content_type,
            "detection_count": len(self.detections),
            "received_at_ns": self.received_at_ns,
        }


class LatestAiDetectionReviewStore:
    """One immutable latest snapshot; readers never observe mismatched fields."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot: AiDetectionReviewSnapshot | None = None
        self._reason = "waiting"

    def publish(self, snapshot: AiDetectionReviewSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot
            self._reason = "waiting"

    def clear(self, reason: str = "waiting") -> None:
        with self._lock:
            self._snapshot = None
            self._reason = reason

    def snapshot(self) -> AiDetectionReviewSnapshot | None:
        with self._lock:
            return self._snapshot

    def snapshot_for_sequence(self, sequence: int) -> AiDetectionReviewSnapshot | None:
        with self._lock:
            snapshot = self._snapshot
            return snapshot if snapshot is not None and snapshot.sequence == sequence else None

    def status(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self._snapshot
            reason = self._reason
        if snapshot is not None:
            return snapshot.status()
        return {
            "available": False,
            "reason": reason,
            "sequence": None,
            "timestamp_ns": None,
            "width": 640,
            "height": 640,
            "center_frequency_hz": None,
            "frequency_start_hz": None,
            "frequency_stop_hz": None,
            "power_min_dbm": None,
            "power_max_dbm": None,
            "power_range_db": None,
            "db_per_gray_level": None,
            "power_range_generation": None,
            "content_type": "image/jpeg",
            "detection_count": 0,
            "received_at_ns": None,
        }


class AiDetectionReviewSubscriber:
    """Reconnect-safe latest-only ZeroMQ SUB consumer for the review channel.

    ZMQ_CONFLATE is not used here: libzmq does not conflate multi-part
    messages correctly, so staleness is instead bounded by draining any
    backlog after each poll and keeping only the newest complete message.
    """

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, reconnect_delay_s: float = 0.25) -> None:
        if not endpoint.startswith(("tcp://", "ipc://", "inproc://")):
            raise ValueError("AI review endpoint is invalid")
        if not math.isfinite(reconnect_delay_s) or reconnect_delay_s <= 0:
            raise ValueError("AI review reconnect delay must be positive")
        self.endpoint = endpoint
        self.reconnect_delay_s = reconnect_delay_s
        self.messages_received = 0
        self.messages_rejected = 0
        self.transport_errors = 0
        self.last_error: str | None = None

    async def run(self, publish: Callable[[AiDetectionReviewSnapshot], None]) -> None:
        context = zmq.asyncio.Context()
        try:
            while True:
                socket = context.socket(zmq.SUB)
                socket.setsockopt(zmq.LINGER, 0)
                socket.setsockopt(zmq.RCVHWM, 2)
                socket.setsockopt(zmq.SUBSCRIBE, b"")
                try:
                    socket.connect(self.endpoint)
                    while True:
                        if not await socket.poll(timeout=250):
                            continue
                        parts = await socket.recv_multipart()
                        # Drain any backlog so a slow consumer still only acts
                        # on the newest available frame.
                        while await socket.poll(timeout=0):
                            parts = await socket.recv_multipart()
                        if len(parts) != 3:
                            self.messages_rejected += 1
                            self.last_error = f"expected 3 message parts, received {len(parts)}"
                            logger.warning(
                                "Rejected AI review message endpoint=%s error=%s",
                                self.endpoint, self.last_error,
                            )
                            continue
                        try:
                            normalized = normalize_ai_review_payload(parts[0], parts[1], parts[2])
                        except ValueError as error:
                            self.messages_rejected += 1
                            self.last_error = str(error)
                            logger.warning("Rejected AI review result endpoint=%s error=%s", self.endpoint, error)
                            continue
                        self.messages_received += 1
                        self.last_error = None
                        publish(
                            AiDetectionReviewSnapshot(
                                sequence=normalized.get("sequence"),
                                timestamp_ns=normalized.get("timestamp_ns"),
                                generated_at=normalized.get("generated_at"),
                                received_at_ns=normalized["received_at_ns"],
                                width=normalized["width"],
                                height=normalized["height"],
                                center_frequency_hz=normalized["center_frequency_hz"],
                                start_frequency_hz=normalized["start_frequency_hz"],
                                stop_frequency_hz=normalized["stop_frequency_hz"],
                                power_min_dbm=normalized.get("power_min_dbm"),
                                power_max_dbm=normalized.get("power_max_dbm"),
                                power_range_db=normalized.get("power_range_db"),
                                db_per_gray_level=normalized.get("db_per_gray_level"),
                                power_range_generation=normalized.get("power_range_generation"),
                                content_type=normalized["content_type"],
                                detections=normalized["detections"],
                                label_freq_ranges_hz=normalized["label_freq_ranges_hz"],
                                raw_image=normalized["raw_image"],
                                annotated_image=normalized["annotated_image"],
                            )
                        )
                except asyncio.CancelledError:
                    raise
                except zmq.ZMQError as error:
                    self.transport_errors += 1
                    self.last_error = str(error)
                    logger.warning("AI review subscriber reconnecting endpoint=%s error=%s", self.endpoint, error)
                    await asyncio.sleep(self.reconnect_delay_s)
                finally:
                    socket.close(linger=0)
        finally:
            context.destroy(linger=0)


def _yolo_label_lines(detections: list[dict[str, Any]], width: int, height: int) -> list[str]:
    lines = []
    for det in detections:
        bbox = det.get("bbox")
        class_id = det.get("class_id")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or not isinstance(class_id, int):
            continue
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2 / width
        cy = (y1 + y2) / 2 / height
        w = (x2 - x1) / width
        h = (y2 - y1) / height
        lines.append(f"{class_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return lines


def save_snapshot_to_disk(snapshot: AiDetectionReviewSnapshot, out_root: Path) -> dict[str, Any]:
    """Persist one review snapshot as images/<stem>.jpg, annotated/<stem>.jpg,
    labels/<stem>.txt (YOLO format, if any detections) and <stem>.json."""
    images_dir = out_root / "images"
    annotated_dir = out_root / "annotated"
    labels_dir = out_root / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir.mkdir(parents=True, exist_ok=True)

    sequence = snapshot.sequence if snapshot.sequence is not None else 0
    timestamp_ns = snapshot.timestamp_ns if snapshot.timestamp_ns is not None else time.time_ns()
    stem = f"detect_san90_{sequence:012d}_{timestamp_ns}"

    image_path = images_dir / f"{stem}.jpg"
    annotated_path = annotated_dir / f"{stem}.jpg"
    image_path.write_bytes(snapshot.raw_image)
    annotated_path.write_bytes(snapshot.annotated_image)

    label_path = None
    lines = _yolo_label_lines(snapshot.detections, snapshot.width, snapshot.height)
    if lines:
        labels_dir.mkdir(parents=True, exist_ok=True)
        label_path = labels_dir / f"{stem}.txt"
        label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    metadata_path = out_root / f"{stem}.json"
    metadata_payload = {
        "sequence": snapshot.sequence,
        "timestamp_ns": snapshot.timestamp_ns,
        "generated_at": snapshot.generated_at,
        "width": snapshot.width,
        "height": snapshot.height,
        "center_frequency_hz": snapshot.center_frequency_hz,
        "start_frequency_hz": snapshot.start_frequency_hz,
        "stop_frequency_hz": snapshot.stop_frequency_hz,
        "power_min_dbm": snapshot.power_min_dbm,
        "power_max_dbm": snapshot.power_max_dbm,
        "power_range_db": snapshot.power_range_db,
        "db_per_gray_level": snapshot.db_per_gray_level,
        "power_range_generation": snapshot.power_range_generation,
        "detections": snapshot.detections,
        "label_freq_ranges_hz": {
            label: {"start_hz": lo, "stop_hz": hi}
            for label, (lo, hi) in snapshot.label_freq_ranges_hz.items()
        },
        "saved_at_ns": time.time_ns(),
    }
    metadata_path.write_text(json.dumps(metadata_payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    return {
        "image": str(image_path),
        "annotated": str(annotated_path),
        "label": str(label_path) if label_path else None,
        "metadata": str(metadata_path),
        "sequence": snapshot.sequence,
    }
