from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable
from core.capability.model import CapabilityRecord


@dataclass
class CliRecord:
    slug: str
    lang: str
    path: str
    bucket: Optional[str]
    project: Optional[str]
    description: str
    declared_capability: Optional[CapabilityRecord]
    source_class: Optional[str]
    source_run_id: Optional[str]


@runtime_checkable
class DiscoverySource(Protocol):
    def discover(self) -> list[CliRecord]: ...
