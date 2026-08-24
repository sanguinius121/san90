"""Persists annotated AI detection review snapshots into the Postgres
`spectrogram` table so past detections can be re-rendered later.

Runs alongside the existing in-memory review store (backend/ai_detection_review.py)
and the optional disk-save action; this module is the third, independent sink.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.ai_detection_review import AiDetectionReviewSnapshot

logger = logging.getLogger("san90.ai_detection_db")

DEFAULT_DSN = "postgresql://postgres:123456@localhost:5432/uavdetection"

_INSERT_SQL = """
    INSERT INTO spectrogram (
        receiver_id, source, sequence, captured_at,
        center_freq_hz, start_freq_hz, stop_freq_hz, image_png
    )
    VALUES (%s, 'ai_stream', %s, to_timestamp(%s), %s, %s, %s, %s)
    ON CONFLICT (receiver_id, sequence) WHERE sequence IS NOT NULL DO NOTHING
    RETURNING spectrogram_id
"""


class SpectrogramDbWriter:
    """Blocking psycopg2 writer; callers must run it off the event loop
    (e.g. via asyncio.to_thread), matching save_snapshot_to_disk's contract."""

    def __init__(self, dsn: str, receiver_id: int | None, retry_cooldown_s: float = 5.0) -> None:
        self.dsn = dsn
        self.receiver_id = receiver_id
        self.retry_cooldown_s = retry_cooldown_s
        self._conn = None
        self._next_retry_monotonic = 0.0

    def _connection(self):
        import psycopg2

        if self._conn is not None and self._conn.closed:
            self._conn = None
        if self._conn is None:
            self._conn = psycopg2.connect(self.dsn)
            self._conn.autocommit = True
        return self._conn

    def insert_snapshot(self, snapshot: "AiDetectionReviewSnapshot") -> int | None:
        """Insert one annotated snapshot. Returns the new spectrogram_id, or
        None if it was skipped as a duplicate (receiver_id, sequence)."""
        import psycopg2

        now = time.monotonic()
        if self._conn is None and now < self._next_retry_monotonic:
            raise RuntimeError("spectrogram database connection is in retry cooldown")

        captured_at_epoch_s = (
            snapshot.timestamp_ns / 1e9 if snapshot.timestamp_ns is not None
            else snapshot.generated_at
        )

        try:
            conn = self._connection()
            with conn.cursor() as cursor:
                cursor.execute(
                    _INSERT_SQL,
                    (
                        self.receiver_id,
                        snapshot.sequence,
                        captured_at_epoch_s,
                        snapshot.center_frequency_hz,
                        snapshot.start_frequency_hz,
                        snapshot.stop_frequency_hz,
                        psycopg2.Binary(snapshot.annotated_image),
                    ),
                )
                row = cursor.fetchone()
        except psycopg2.Error:
            if self._conn is not None:
                self._conn.close()
            self._conn = None
            self._next_retry_monotonic = time.monotonic() + self.retry_cooldown_s
            raise

        return None if row is None else row[0]

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None
