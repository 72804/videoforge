from __future__ import annotations

from typing import Any, Protocol


class ResponsesClient(Protocol):
    def create(self, **kwargs: Any) -> Any: ...
