"""Sample source file for AST parser tests."""

import os
import json
from pathlib import Path
from typing import Optional, List

GLOBAL_CONFIG: dict = {"debug": True}
MAX_RETRIES: int = 3


def process_data(data: List[dict], prefix: str = "item") -> dict:
    """Process a list of data items."""
    result: dict = {}
    for item in data:
        key = f"{prefix}_{item['id']}"
        result[key] = item
    return result


def validate_input(payload: dict, strict: bool = True) -> dict:
    """Validate and normalize input payload."""
    user_id: Optional[int] = payload.get("user_id")
    if user_id is None:
        raise ValueError("user_id must not be None")
    name: str = payload.get("name", "unknown")
    return {"user_id": user_id, "name": name}


class DataProcessor:
    """A sample data processor class."""

    def __init__(self, config: dict) -> None:
        self.config: dict = config
        self._cache: dict = {}

    def run(self, items: List[dict]) -> List[dict]:
        """Run the processor on a list of items."""
        results: List[dict] = []
        for item in items:
            processed = self._process_item(item)
            results.append(processed)
        return results

    def _process_item(self, item: dict) -> dict:
        """Process a single item."""
        key: str = str(item.get("id", ""))
        if key in self._cache:
            return self._cache[key]
        result: dict = {"id": key, "processed": True}
        self._cache[key] = result
        return result
