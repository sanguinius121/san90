"""FastAPI entry point for the bounded analyzer display stream."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import math
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, field_validator
from fastapi.exceptions import RequestValidationError

from backend.api.service import AnalyzerService
from backend.analyzer.amplitude_correction import validate_amplitude_offset
from backend.analyzer.errors import ControlError, ControlErrorCode
from backend.hardware.rf_switch import RfSwitchManager
from backend.hardware.rf_switch.errors import RfSwitchError
from backend.frequency_scan import FrequencyScanEntry, MIN_SCAN_DWELL_SECONDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
service = AnalyzerService()
rf_switch = RfSwitchManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await service.start()
    await asyncio.to_thread(rf_switch.start)
    try:
        yield
    finally:
        # RF8 is restored before releasing the USB controller. This subsystem
        # is independent of analyzer acquisition and shutdown errors are
        # intentionally contained by the manager.
        await asyncio.to_thread(rf_switch.stop)
        await service.stop(disconnect=True)


app = FastAPI(title="SAN-90 Analyzer Backend", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)


class FrequencyRequest(BaseModel):
    center_frequency_hz: float

    @field_validator("center_frequency_hz")
    @classmethod
    def valid_center(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("center_frequency_hz must be finite and positive")
        return value


class FrequencyScanEntryRequest(BaseModel):
    id: str
    enabled: bool
    center_frequency_hz: float
    duration_seconds: float

    @field_validator("center_frequency_hz")
    @classmethod
    def valid_scan_center(cls, value: float) -> float:
        if not math.isfinite(value) or value <= 0:
            raise ValueError("center_frequency_hz must be finite and positive")
        return value

    @field_validator("duration_seconds")
    @classmethod
    def valid_scan_duration(cls, value: float) -> float:
        if not math.isfinite(value) or value < MIN_SCAN_DWELL_SECONDS:
            raise ValueError(f"duration_seconds must be at least {MIN_SCAN_DWELL_SECONDS}")
        return value


class FrequencyScanConfigRequest(BaseModel):
    entries: list[FrequencyScanEntryRequest]


class ReferenceLevelRequest(BaseModel):
    reference_level_dbm: float

    @field_validator("reference_level_dbm")
    @classmethod
    def valid_level(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("reference_level_dbm must be finite")
        return value


class AmplitudeOffsetRequest(BaseModel):
    amplitude_offset_db: float

    @field_validator("amplitude_offset_db")
    @classmethod
    def valid_offset(cls, value: float) -> float:
        return validate_amplitude_offset(value)


class AttenuationRequest(BaseModel):
    attenuation_db: int | None = None
    mode: Literal["auto", "manual"] = "manual"

    @field_validator("attenuation_db")
    @classmethod
    def valid_attenuation(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= 127:
            raise ValueError("manual attenuation must fit the non-negative SDK int8 range")
        return value


class ModeRequest(BaseModel):
    mode: str


class RbwRequest(BaseModel):
    rbw_hz: float | None = None
    mode: Literal["auto", "manual"] | None = None

    @field_validator("rbw_hz")
    @classmethod
    def valid_rbw(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError("rbw_hz must be finite and positive")
        return value


class WindowRequest(BaseModel):
    window: str


class DetectorRequest(BaseModel):
    detector: str


class ResolutionTradeoffRequest(BaseModel):
    index: int


class AiStreamEnabledRequest(BaseModel):
    enabled: bool


class AiPowerProfileRequest(BaseModel):
    profile: str


class RfPathRequest(BaseModel):
    path: str


@app.exception_handler(ControlError)
async def control_error_handler(_: Request, error: ControlError) -> JSONResponse:
    validation_codes = {
        ControlErrorCode.UNSUPPORTED_SETTING,
        ControlErrorCode.VALUE_OUT_OF_RANGE,
        ControlErrorCode.UNSUPPORTED_RBW,
        ControlErrorCode.UNSUPPORTED_WINDOW,
        ControlErrorCode.UNSUPPORTED_DETECTOR,
        ControlErrorCode.INVALID_PROFILE,
    }
    status = 422 if error.code in validation_codes else 503
    return JSONResponse(status_code=status, content={"error": error.as_dict()})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {"code": ControlErrorCode.VALUE_OUT_OF_RANGE.value, "message": error.errors()[0].get("msg", "Invalid control value"), "sdk_status": None, "requested_value": None, "previous_actual_value": None, "recoverable": True}})


@app.exception_handler(RfSwitchError)
async def rf_switch_error_handler(_: Request, error: RfSwitchError) -> JSONResponse:
    return JSONResponse(
        status_code=error.http_status,
        content={"detail": {"code": error.code, "message": str(error)}},
    )


@app.get("/api/analyzer/source")
async def source() -> dict[str, str]:
    return {"source": service.source_name}


@app.get("/api/analyzer/status")
async def status() -> dict[str, object]:
    return service.status_payload()


@app.get("/api/analyzer/capabilities")
async def capabilities() -> dict[str, object]:
    return service.capabilities_payload()


@app.get("/api/analyzer/settings")
async def settings() -> dict[str, object]:
    return service.settings_payload()


@app.get("/api/rf-switch/capabilities")
async def rf_switch_capabilities() -> dict[str, object]:
    return rf_switch.capabilities()


@app.get("/api/rf-switch/status")
async def rf_switch_status() -> dict[str, object]:
    return (await asyncio.to_thread(rf_switch.refresh)).as_dict()


@app.put("/api/rf-switch/path")
async def rf_switch_path(request: RfPathRequest) -> dict[str, object]:
    try:
        return (await asyncio.to_thread(rf_switch.set_path, request.path)).as_dict()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/ai-stream/status")
async def ai_stream_status() -> dict[str, object]:
    return service.ai_stream_status()


@app.put("/api/ai-stream/enabled")
async def ai_stream_enabled(request: AiStreamEnabledRequest) -> dict[str, object]:
    return await service.set_ai_stream_enabled(request.enabled)


@app.put("/api/ai-stream/power-profile")
async def ai_power_profile(request: AiPowerProfileRequest) -> dict[str, object]:
    return await service.set_ai_power_profile(request.profile)


@app.get("/api/ai-stream/preview.png")
async def ai_stream_preview() -> Response:
    image = service.latest_ai_preview_png()
    if image is None:
        raise HTTPException(status_code=404, detail="AI preview is disabled or no preview image is available")
    return Response(content=image, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.put("/api/analyzer/frequency")
async def frequency(request: FrequencyRequest) -> dict[str, object]:
    state = await service.apply_control(center_frequency_hz=request.center_frequency_hz)
    actual = state["actual"]
    return {
        "requested_center_frequency_hz": request.center_frequency_hz,
        "actual_center_frequency_hz": actual["center_frequency_hz"],
        "start_frequency_hz": actual["start_frequency_hz"],
        "stop_frequency_hz": actual["stop_frequency_hz"],
        "actual_span_hz": actual["span_hz"],
        "actual_rbw_hz": actual["rbw_hz"],
        "point_count": actual["point_count"],
        "configuration_generation": state["configuration_generation"],
        "settings": state,
    }


@app.get("/api/analyzer/frequency-scan/status")
async def frequency_scan_status() -> dict[str, object]:
    return service.frequency_scan_payload()


@app.put("/api/analyzer/frequency-scan/config")
async def frequency_scan_config(request: FrequencyScanConfigRequest) -> dict[str, object]:
    return service.configure_frequency_scan([
        FrequencyScanEntry(
            id=entry.id,
            enabled=entry.enabled,
            center_frequency_hz=entry.center_frequency_hz,
            duration_seconds=entry.duration_seconds,
        )
        for entry in request.entries
    ])


@app.post("/api/analyzer/frequency-scan/start")
async def frequency_scan_start() -> dict[str, object]:
    return await service.start_frequency_scan()


@app.post("/api/analyzer/frequency-scan/stop")
async def frequency_scan_stop() -> dict[str, object]:
    return await service.stop_frequency_scan()


@app.put("/api/analyzer/amplitude/reference-level")
async def reference_level(request: ReferenceLevelRequest) -> dict[str, object]:
    return await service.apply_control(reference_level_dbm=request.reference_level_dbm)


@app.put("/api/analyzer/amplitude/offset")
async def amplitude_offset(request: AmplitudeOffsetRequest) -> dict[str, object]:
    return await service.apply_amplitude_offset(request.amplitude_offset_db)


@app.put("/api/analyzer/amplitude/attenuation")
async def attenuation(request: AttenuationRequest) -> dict[str, object]:
    if request.mode == "manual" and request.attenuation_db is None:
        raise ControlError(ControlErrorCode.VALUE_OUT_OF_RANGE, "manual attenuation requires attenuation_db", recoverable=True)
    return await service.apply_control(attenuation_db=None if request.mode == "auto" else request.attenuation_db)


@app.put("/api/analyzer/amplitude/preamplifier")
async def preamplifier(request: ModeRequest) -> dict[str, object]:
    if request.mode not in service.capabilities_payload()["preamplifier_modes"]:
        raise ControlError(ControlErrorCode.UNSUPPORTED_SETTING, f"Unsupported preamplifier mode {request.mode!r}", requested_value=request.mode, recoverable=True)
    return await service.apply_control(preamplifier=request.mode)


@app.put("/api/analyzer/amplitude/gain-strategy")
async def gain_strategy(request: ModeRequest) -> dict[str, object]:
    if request.mode not in service.capabilities_payload()["gain_strategy_modes"]:
        raise ControlError(ControlErrorCode.UNSUPPORTED_SETTING, f"Unsupported gain strategy {request.mode!r}", requested_value=request.mode, recoverable=True)
    return await service.apply_control(gain_strategy=request.mode)


@app.put("/api/analyzer/bandwidth/rbw")
async def rbw(request: RbwRequest) -> dict[str, object]:
    mode = request.mode or ("manual" if request.rbw_hz is not None else "auto")
    if mode == "manual" and request.rbw_hz is None:
        raise ControlError(ControlErrorCode.UNSUPPORTED_RBW, "manual RBW mode requires rbw_hz", recoverable=True)
    return await service.apply_control(rbw_mode=mode, rbw_hz=request.rbw_hz if mode == "manual" else None)


@app.put("/api/analyzer/resolution-tradeoff")
async def resolution_tradeoff(request: ResolutionTradeoffRequest) -> dict[str, object]:
    return await service.apply_resolution_tradeoff(request.index)


@app.put("/api/analyzer/sweep/window")
async def window(request: WindowRequest) -> dict[str, object]:
    modes = service.capabilities_payload()["window_modes"]
    if request.window not in modes:
        raise ControlError(ControlErrorCode.UNSUPPORTED_WINDOW, f"Unsupported RTA window {request.window!r}", requested_value=request.window, recoverable=True)
    return await service.apply_control(window=request.window)


@app.put("/api/analyzer/detection/detector")
async def detector(request: DetectorRequest) -> dict[str, object]:
    modes = service.capabilities_payload()["detector_modes"]
    if request.detector not in modes:
        raise ControlError(ControlErrorCode.UNSUPPORTED_DETECTOR, f"Unsupported RTA detector {request.detector!r}", requested_value=request.detector, recoverable=True)
    return await service.apply_control(detector=request.detector)


@app.post("/api/analyzer/start")
async def start() -> dict[str, object]:
    try:
        await service.start()
        return service.status_payload()
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/analyzer/stop")
async def stop() -> dict[str, object]:
    try:
        await service.stop()
        return service.status_payload()
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/analyzer/reconnect")
async def reconnect() -> dict[str, object]:
    try:
        await service.reconnect()
        return service.status_payload()
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.websocket("/ws/analyzer")
async def analyzer_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    mailbox = service.register()
    try:
        while True:
            for message in await mailbox.take():
                await websocket.send_bytes(message)
                service.mark_sent(message)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        service.client_send_failures += 1
        raise
    finally:
        service.unregister(mailbox)
