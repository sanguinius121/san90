"""Transport-neutral RF-switch contract."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import RfPath


class RfSwitch(ABC):
    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def set_path(self, path: RfPath) -> None: ...

    @abstractmethod
    def get_path(self) -> RfPath: ...

    @property
    @abstractmethod
    def raw_gpio_value(self) -> int | None: ...

    def is_hardware_present(self) -> bool:
        """Return whether the USB hardware is physically enumerable."""
        return False
