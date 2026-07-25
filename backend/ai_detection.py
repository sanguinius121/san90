"""Bounded realtime subscriber for current-frame AI detection results."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Callable, Mapping
from typing import Any

import zmq
import zmq.asyncio

logger = logging.getLogger("san90.ai_detection")

DEFAULT_ENDPOINT = "tcp://127.0.0.1:5558"
MAX_MESSAGE_BYTES = 256 * 1024
MAX_DETECTIONS = 128


def _first_present(mapping: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def normalize_ai_detection_payload(payload: bytes | str | Mapping[str, Any]) -> dict[str, Any]:
    """Validate one current-frame result and discard historical aggregate fields."""
    if isinstance(payload, bytes):
        if len(payload) > MAX_MESSAGE_BYTES:
            raise ValueError("AI detection payload is too large")
        try:
            data = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("AI detection payload is not valid UTF-8 JSON") from error
    elif isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise ValueError("AI detection payload is too large")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("AI detection payload is not valid JSON") from error
    else:
        data = dict(payload)
    if not isinstance(data, dict) or not isinstance(data.get("detections"), list):
        raise ValueError("AI detection payload must contain a detections array")
    if len(data["detections"]) > MAX_DETECTIONS:
        raise ValueError("AI detection payload contains too many detections")

    detections: list[dict[str, Any]] = []
    for raw in data["detections"]:
        if not isinstance(raw, Mapping):
            raise ValueError("AI detection entry must be an object")
        label = raw.get("label")
        confidence = raw.get("confidence")
        frequency_start = _first_present(
            raw,
            ("frequency_start", "frequency_start_hz", "start_frequency_hz", "start_hz"),
        )
        frequency_stop = _first_present(
            raw,
            ("frequency_stop", "frequency_stop_hz", "stop_frequency_hz", "stop_hz"),
        )
        if not isinstance(label, str) or not label.strip() or len(label) > 64:
            raise ValueError("AI detection label is invalid")
        if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in (
            confidence,
            frequency_start,
            frequency_stop,
        )):
            raise ValueError("AI detection confidence and frequency bounds must be finite")
        confidence_value = float(confidence)
        start_value = float(frequency_start)
        stop_value = float(frequency_stop)
        if not 0.0 <= confidence_value <= 1.0:
            raise ValueError("AI detection confidence must be between zero and one")
        if start_value < 0.0 or stop_value <= start_value:
            raise ValueError("AI detection frequency bounds are invalid")
        detection: dict[str, Any] = {
            "label": label.strip(),
            "confidence": confidence_value,
            "frequency_start": start_value,
            "frequency_stop": stop_value,
        }
        if isinstance(raw.get("class_id"), int):
            detection["class_id"] = raw["class_id"]
        detections.append(detection)

    normalized: dict[str, Any] = {
        "detections": detections,
        "received_at_ns": time.time_ns(),
    }
    for key in ("sequence", "timestamp_ns"):
        value = data.get(key)
        if isinstance(value, int) and value >= 0:
            normalized[key] = value
    generated_at = data.get("generated_at")
    if isinstance(generated_at, (int, float)) and math.isfinite(float(generated_at)):
        normalized["generated_at"] = float(generated_at)
    return normalized


class AiDetectionSubscriber:
    """Reconnect-safe latest-only ZeroMQ SUB consumer."""

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, reconnect_delay_s: float = 0.25) -> None:
        if not endpoint.startswith(("tcp://", "ipc://", "inproc://")):
            raise ValueError("AI detection endpoint is invalid")
        if not math.isfinite(reconnect_delay_s) or reconnect_delay_s <= 0:
            raise ValueError("AI detection reconnect delay must be positive")
        self.endpoint = endpoint
        self.reconnect_delay_s = reconnect_delay_s
        self.messages_received = 0
        self.messages_rejected = 0
        self.transport_errors = 0
        self.last_error: str | None = None

    async def run(self, publish: Callable[[dict[str, Any]], None]) -> None:
        context = zmq.asyncio.Context()
        try:
            while True:
                socket = context.socket(zmq.SUB)
                socket.setsockopt(zmq.LINGER, 0)
                socket.setsockopt(zmq.RCVHWM, 1)
                socket.setsockopt(zmq.CONFLATE, 1)
                socket.setsockopt(zmq.SUBSCRIBE, b"")
                try:
                    socket.connect(self.endpoint)
                    while True:
                        if not await socket.poll(timeout=250):
                            continue
                        raw = await socket.recv()
                        try:
                            result = normalize_ai_detection_payload(raw)
                        except ValueError as error:
                            self.messages_rejected += 1
                            self.last_error = str(error)
                            logger.warning("Rejected AI detection result endpoint=%s error=%s", self.endpoint, error)
                            continue
                        self.messages_received += 1
                        self.last_error = None
                        publish(result)
                except asyncio.CancelledError:
                    raise
                except zmq.ZMQError as error:
                    self.transport_errors += 1
                    self.last_error = str(error)
                    logger.warning("AI detection subscriber reconnecting endpoint=%s error=%s", self.endpoint, error)
                    await asyncio.sleep(self.reconnect_delay_s)
                finally:
                    socket.close(linger=0)
        finally:
            context.destroy(linger=0)
