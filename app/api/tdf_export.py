from timepoint_tdf import TDFRecord, TDFProvenance
from datetime import datetime, timezone


def node_to_tdf_record(node_id: str, attrs: dict) -> TDFRecord:
    """Convert a clockchain node to a TDF record for export."""
    return TDFRecord(
        id=attrs.get("path") or node_id,
        source="clockchain",
        timestamp=datetime.fromisoformat(attrs["created_at"]) if "created_at" in attrs else datetime.now(timezone.utc),
        provenance=TDFProvenance(
            generator="timepoint-clockchain",
            flash_id=attrs.get("flash_timepoint_id"),
            confidence=attrs.get("confidence"),
        ),
        payload={k: v for k, v in attrs.items()
                 if k not in ("path", "id", "created_at", "updated_at", "flash_timepoint_id", "confidence")},
    )
