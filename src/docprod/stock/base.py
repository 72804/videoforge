from __future__ import annotations

from typing import Protocol

from docprod.stock.models import StockSearchPage


class StockVideoProvider(Protocol):
    name: str

    def search(
        self,
        query: str,
        *,
        orientation: str = "landscape",
        size: str = "medium",
        per_page: int = 20,
        locale: str = "en-US",
        page: int = 1,
    ) -> StockSearchPage: ...

    def fetch_bytes(self, url: str) -> bytes: ...
