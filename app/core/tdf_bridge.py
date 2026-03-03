from datetime import datetime, timezone

from timepoint_tdf import TDFRecord, TDFProvenance, from_clockchain

# Fields that are provenance/meta, not payload content
_PROVENANCE_KEYS = {
    "tdf_hash",
    "confidence",
    "source_run_id",
    "flash_timepoint_id",
    "created_at",
    "published_at",
}


def make_tdf_record(
    node_id: str,
    attrs: dict,
    generator: str = "timepoint-clockchain",
) -> TDFRecord:
    """Write path: build a TDFRecord from node attrs before DB insert.

    Separates provenance fields from payload, computes tdf_hash.
    Called by add_node().
    """
    payload = {k: v for k, v in attrs.items() if k not in _PROVENANCE_KEYS}

    created_at = attrs.get("created_at")
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if created_at is None:
        created_at = datetime.now(timezone.utc)

    return TDFRecord(
        id=node_id,
        source="clockchain",
        timestamp=created_at,
        provenance=TDFProvenance(
            generator=generator,
            confidence=attrs.get("confidence"),
            run_id=attrs.get("source_run_id"),
            flash_id=attrs.get("flash_timepoint_id"),
        ),
        payload=payload,
    )


def tdf_to_node_attrs(record: TDFRecord) -> tuple[str, dict]:
    """Reverse path: extract node_id and flat attrs from a TDFRecord.

    Used by seed loader and TDF ingest endpoint.
    """
    attrs = dict(record.payload)
    # Map provenance back to clockchain columns
    if record.provenance.confidence is not None:
        attrs["confidence"] = record.provenance.confidence
    if record.provenance.run_id is not None:
        attrs["source_run_id"] = record.provenance.run_id
    if record.provenance.flash_id is not None:
        attrs["flash_timepoint_id"] = record.provenance.flash_id
    attrs["tdf_hash"] = record.tdf_hash
    attrs["created_at"] = record.timestamp.isoformat()
    return record.id, attrs


def export_node_as_tdf(node_dict: dict) -> TDFRecord:
    """Read path: convert a DB node dict to TDF for API export.

    Delegates to from_clockchain() then strips clockchain-specific
    provenance fields that the library doesn't know about.
    """
    record = from_clockchain(node_dict)
    # Map clockchain-specific fields to provenance and remove from payload
    if "source_run_id" in record.payload:
        run_id = record.payload.pop("source_run_id")
        if run_id:
            record.provenance.run_id = run_id
    record.payload.pop("tdf_hash", None)
    # Recompute hash after cleaning payload
    record.tdf_hash = record.compute_hash()
    return record
