"""Temporal Data Format (TDF) hashing.

Produces a deterministic SHA-256 fingerprint of a node's canonical
temporal-spatial-content fields.  Used as a content-addressable key for
deduplication, change detection, and data-integrity verification.
"""

import hashlib
import json


_TDF_FIELDS = (
    "year", "month", "day", "time",
    "country", "region", "city", "slug",
    "name", "one_liner",
)


def compute_tdf_hash(attrs: dict) -> str:
    """Return a hex SHA-256 digest over the canonical TDF fields in *attrs*.

    Missing or ``None`` values are normalised to empty strings so the hash
    is stable regardless of which optional keys the caller supplies.
    """
    payload = {
        k: str(attrs.get(k) or "").lower().strip()
        for k in _TDF_FIELDS
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
