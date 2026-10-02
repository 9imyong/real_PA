"""Provider-neutral contracts; no engine SDK types cross this boundary."""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

ROLES = frozenset({"llm", "stt", "tts", "kws", "vad"})

class ProviderError(Exception):
    code = "provider_error"
class ConfigurationError(ProviderError):
    code = "configuration_error"
class UnsupportedCapability(ProviderError):
    code = "unsupported_capability"
class InvalidOutput(ProviderError):
    code = "invalid_output"
class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"
class ModelLoadError(ProviderError):
    code = "model_load_error"
class ResourceExhausted(ProviderError):
    code = "resource_exhausted"
class ContextCapacityExceeded(ProviderError):
    code = "context_capacity_exceeded"

@dataclass(frozen=True)
class AudioFrame:
    pcm: bytes
    sample_rate: int
    sequence: int
    timestamp: float
    channels: int = 1

    def __post_init__(self):
        if self.sample_rate <= 0 or self.channels != 1 or self.sequence < 0:
            raise ValueError("invalid mono audio metadata")
        if len(self.pcm) % 2:
            raise ValueError("PCM16 must have an even byte count")

    @property
    def sample_count(self) -> int:
        return len(self.pcm) // 2

@dataclass
class Context:
    session_id: str
    turn_id: int
    generation_id: int
    timeout: float = 30.0
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    deadline: float = field(init=False)

    def __post_init__(self):
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        self.deadline = time.monotonic() + self.timeout

    def check(self):
        if self.cancelled.is_set():
            raise asyncio.CancelledError
        if time.monotonic() >= self.deadline:
            raise TimeoutError("provider deadline exceeded")

@dataclass(frozen=True)
class Event:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class Request:
    role: str
    data: dict[str, Any]
    # Robot-local authorization/audio context; never serialized by RPC adapters.
    local: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError("unknown role")

@dataclass(frozen=True)
class Capabilities:
    role: str
    features: frozenset[str]
    languages: frozenset[str]
    sample_rates: frozenset[int] = frozenset()

    def require(self, features: set[str], language: str = "ko"):
        missing = features - self.features
        if missing or language not in self.languages:
            raise UnsupportedCapability(f"{self.role}: missing required capabilities")

class Provider(Protocol):
    capabilities: Capabilities
    async def load(self) -> None: ...
    def stream(self, request: Request, context: Context) -> AsyncIterator[Event]: ...
    async def reset(self, session_id: str) -> None: ...
    async def close(self) -> None: ...

# Role aliases share transport-neutral request/event envelopes. Semantics are
# enforced by role-specific adapters and capability negotiation.
class LlmPort(Provider, Protocol): ...
class StreamingSttPort(Provider, Protocol): ...
class TtsPort(Provider, Protocol): ...
class KwsPort(Provider, Protocol): ...
class VadPort(Provider, Protocol): ...
