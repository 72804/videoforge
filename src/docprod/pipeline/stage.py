from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from docprod.storage.hashing import content_hash


class PipelineStage(ABC):
    """Minimal contract for a future idempotent pipeline stage.

    Not a workflow engine. Concrete stages will hash inputs, skip when unchanged,
    and write typed JSON artifacts.
    """

    name: str

    def compute_input_hash(self, payload: Any) -> str:
        return content_hash(payload)

    @abstractmethod
    def run(self, payload: Any) -> Any:
        raise NotImplementedError
