"""A shared daily cap on AI requests, so a public demo link cannot run up an unlimited API bill."""
from __future__ import annotations

import json
import logging
import threading
from datetime import date
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


class DailyLimit:
    """Counts requests per calendar day in a small JSON file. A limit of 0 means unlimited."""

    def __init__(self, path: Path, limit: int, today: Callable[[], date] = date.today):
        self.path = Path(path)
        self.limit = limit
        self.today = today
        self._lock = threading.Lock()  # Streamlit serves every visitor from one process

    def _read(self) -> int:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 0
        return int(data.get("count", 0)) if data.get("date") == self.today().isoformat() else 0

    def used(self) -> int:
        with self._lock:
            return self._read()

    def remaining(self) -> int | None:
        return None if self.limit <= 0 else max(self.limit - self.used(), 0)

    def try_use(self) -> bool:
        """Record one request if today's limit allows it. Returns False when the limit is reached."""
        with self._lock:
            count = self._read()
            if self.limit > 0 and count >= self.limit:
                return False
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({"date": self.today().isoformat(), "count": count + 1}),
                                     encoding="utf-8")
            except OSError:
                log.exception("Could not save usage count")  # never block users over a disk problem
            return True
