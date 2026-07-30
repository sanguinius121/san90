"""Catalog plus engine façade used by AnalyzerService."""

from __future__ import annotations

from dataclasses import asdict

from .engine import PlaybackEngine
from .storage import RecordingCatalog


class PlaybackService:
    def __init__(self, catalog: RecordingCatalog, engine: PlaybackEngine | None = None) -> None:
        self.catalog = catalog
        self.engine = engine or PlaybackEngine()

    def recordings_payload(self) -> dict[str, object]:
        return {"recordings": [asdict(item) for item in self.catalog.list()]}

    def recording_payload(self, recording_id: str) -> dict[str, object]:
        return asdict(self.catalog.get(recording_id))

    def status_payload(self) -> dict[str, object]:
        payload = asdict(self.engine.status())
        payload["state"] = self.engine.status().state.value
        return payload
