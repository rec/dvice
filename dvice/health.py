"""Discovery observations and supervisor health, not audio-stream health."""

from enum import StrEnum, auto

from pydantic import BaseModel

from .device import DeviceDict


class DiscoveryHealth(StrEnum):
    idle = auto()
    starting = auto()
    healthy = auto()
    refreshing = auto()
    retrying = auto()
    stopped = auto()


class DiscoveryFailure(StrEnum):
    spawn = auto()
    exited = auto()
    stalled = auto()
    protocol = auto()
    reader = auto()
    cleanup = auto()


class DiscoveryStatus(BaseModel, frozen=True):
    devices: list[DeviceDict] | None = None
    sequence: int = 0
    observed_at: float | None = None
    generation: int = 0
    health: DiscoveryHealth = DiscoveryHealth.idle
    failure: DiscoveryFailure | None = None
    next_retry: float | None = None
