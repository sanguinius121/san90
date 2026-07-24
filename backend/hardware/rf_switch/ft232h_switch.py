"""FT232H asynchronous-bitbang driver for the external 8-way RF switch."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from .base import RfSwitch
from .errors import RfSwitchBusy, RfSwitchPermissionDenied, RfSwitchReadbackMismatch, RfSwitchUnavailable
from .models import ADDRESS_TO_PATH, PATH_TO_ADDRESS, RfPath

logger = logging.getLogger("san90.rf_switch.ft232h")

FTDI_URL = "ftdi://ftdi:232h/1"
AD4 = 1 << 4
AD5 = 1 << 5
AD6 = 1 << 6
CONTROL_MASK = AD4 | AD5 | AD6
FT232H_VENDOR_ID = 0x0403
FT232H_PRODUCT_ID = 0x6014


def address_to_gpio_value(address: int) -> int:
    if not isinstance(address, int) or not 0 <= address <= 7:
        raise ValueError("RF switch address must be between 0 and 7")
    return address << 4


def gpio_value_to_address(value: int) -> int:
    return (value & CONTROL_MASK) >> 4


def ft232h_hardware_present() -> bool:
    """Probe USB enumeration without claiming the PyFtdi interface."""
    try:
        import usb.core
        return usb.core.find(idVendor=FT232H_VENDOR_ID, idProduct=FT232H_PRODUCT_ID) is not None
    except Exception:
        return False


def flush_ftdi_usb_cache() -> None:
    """Discard stale PyFtdi enumeration objects after USB replug.

    PyFtdi explicitly requires this after hotplug; otherwise a device that
    reappears at a new USB address can repeatedly fail with errno 19.
    """
    try:
        from pyftdi.usbtools import UsbTools
        UsbTools.flush_cache()
    except ImportError as error:
        raise RfSwitchUnavailable(
            "pyftdi is not installed; install backend/requirements.txt"
        ) from error


def _translate_transport_error(error: Exception) -> RfSwitchUnavailable:
    text = str(error)
    lowered = text.lower()
    if "permission" in lowered or "access denied" in lowered:
        return RfSwitchPermissionDenied(text)
    if "busy" in lowered or "claimed" in lowered:
        return RfSwitchBusy(text)
    return RfSwitchUnavailable(text)


class Ft232hRfSwitch(RfSwitch):
    def __init__(
        self,
        url: str = FTDI_URL,
        *,
        settle_s: float = 0.005,
        controller_factory: Callable[[], Any] | None = None,
        cache_flusher: Callable[[], None] = flush_ftdi_usb_cache,
    ) -> None:
        if not 0 <= settle_s <= 0.1:
            raise ValueError("settle_s must be between 0 and 0.1 seconds")
        self.url = url
        self.settle_s = settle_s
        self._controller_factory = controller_factory
        self._cache_flusher = cache_flusher
        self._controller: Any | None = None
        self._raw_gpio_value: int | None = None
        self._lock = threading.RLock()

    @property
    def raw_gpio_value(self) -> int | None:
        return self._raw_gpio_value

    def is_hardware_present(self) -> bool:
        return ft232h_hardware_present()

    def _new_controller(self) -> Any:
        if self._controller_factory is not None:
            return self._controller_factory()
        try:
            from pyftdi.gpio import GpioAsyncController
        except ImportError as error:
            raise RfSwitchUnavailable(
                "pyftdi is not installed; install backend/requirements.txt"
            ) from error
        return GpioAsyncController()

    def open(self) -> None:
        with self._lock:
            if self._controller is not None:
                return
            self._cache_flusher()
            controller = self._new_controller()
            try:
                controller.configure(self.url, direction=CONTROL_MASK, initial=0x70)
                self._controller = controller
                self.set_path(RfPath.RF8_WIDEBAND_ANTENNA)
            except RfSwitchReadbackMismatch:
                try:
                    controller.close()
                finally:
                    self._controller = None
                raise
            except Exception as error:
                try:
                    controller.close()
                except Exception:
                    pass
                self._controller = None
                raise _translate_transport_error(error) from error
            logger.info("FT232H device opened url=%s mask=0x%02x", self.url, CONTROL_MASK)

    def _require_controller(self) -> Any:
        if self._controller is None:
            raise RfSwitchUnavailable("FT232H RF switch is not open")
        return self._controller

    def _read_raw(self) -> int:
        controller = self._require_controller()
        try:
            value = int(controller.read()) & CONTROL_MASK
        except Exception as error:
            raise _translate_transport_error(error) from error
        self._raw_gpio_value = value
        return value

    def set_path(self, path: RfPath) -> None:
        if not isinstance(path, RfPath):
            raise ValueError("path must be an RfPath")
        address = PATH_TO_ADDRESS[path]
        gpio_value = address_to_gpio_value(address)
        with self._lock:
            controller = self._require_controller()
            try:
                # AD4..AD6 are the only output bits in direction, so unrelated
                # pins remain inputs. One write updates all address bits.
                controller.write(gpio_value)
            except Exception as error:
                raise _translate_transport_error(error) from error
            if self.settle_s:
                time.sleep(self.settle_s)
            raw = self._read_raw()
            reported = gpio_value_to_address(raw)
            if reported != address:
                raise RfSwitchReadbackMismatch(
                    f"requested {path.value} address={address:03b}, read back address={reported:03b} raw=0x{raw:02x}"
                )

    def get_path(self) -> RfPath:
        with self._lock:
            return ADDRESS_TO_PATH[gpio_value_to_address(self._read_raw())]

    def close(self) -> None:
        with self._lock:
            controller = self._controller
            if controller is None:
                return
            try:
                try:
                    self.set_path(RfPath.RF8_WIDEBAND_ANTENNA)
                    logger.info("RF switch returned to wideband fail-safe")
                except Exception:
                    logger.exception("Unable to verify wideband fail-safe during FT232H shutdown")
                if self.settle_s:
                    time.sleep(self.settle_s)
            finally:
                try:
                    controller.close()
                finally:
                    self._controller = None
                    self._raw_gpio_value = None
                    logger.info("FT232H device closed")
