"""Small shared helpers."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone


def now_iso() -> str:
    """ISO-8601 UTC timestamp, e.g. ``2026-06-04T09:14:22Z`` (ledger convention)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short_hash(*parts: object, length: int = 16) -> str:
    """Stable hex digest over ``parts`` (used for ids and fingerprints)."""
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]
