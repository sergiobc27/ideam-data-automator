import logging

from .extract import iter_socrata_pages
from .load import build_payload, upsert_to_socrata
from .query_validation import date_window_clauses
from .transform import dataframe_memory_mb, deduplicate_observations, normalize_chunk

logger = logging.getLogger(__name__)

SYNC_IDEAM_TO_SOCRATA_SCHEMA = {
    "name": "sync_ideam_to_socrata",
    "description": (
        "Extract IDEAM observations from Datos.gov.co, normalize/validate rows, "
        "and upsert them into a Socrata sink dataset."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "source_dataset_id": {"type": "string"},
            "sink_dataset_id": {"type": "string"},
            "date_column": {"type": "string", "default": "fechaobservacion"},
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"},
            "where_filters": {"type": "array", "items": {"type": "string"}},
            "dry_run": {"type": "boolean", "default": True},
        },
        "required": ["source_dataset_id", "sink_dataset_id", "start_date", "end_date"],
    },
}


def sync_ideam_to_socrata(
    source_dataset_id,
    sink_dataset_id,
    start_date,
    end_date,
    retry_func,
    date_column="fechaobservacion",
    where_filters=None,
    dry_run=True,
):
    """Extract, normalize, validate, and upsert IDEAM records into a Socrata sink.

    This function is intentionally shaped as an LLM-agent tool: inputs are primitive
    JSON-compatible values, side effects are explicit through dry_run, and the return
    value is a compact execution summary.
    """
    filters = list(where_filters or [])
    filters.extend(date_window_clauses(date_column, start_date, end_date))
    where_str = " AND ".join(filters)

    summary = {
        "source_dataset_id": source_dataset_id,
        "sink_dataset_id": sink_dataset_id,
        "dry_run": dry_run,
        "read_rows": 0,
        "validated_rows": 0,
        "uploaded_rows": 0,
        "rejected_rows": 0,
        "chunks": 0,
        "max_chunk_memory_mb": 0.0,
    }

    for data in iter_socrata_pages(source_dataset_id, retry_func, where_str=where_str, order=":id"):
        df = normalize_chunk(data, source_dataset_id, date_column)
        df, _ = deduplicate_observations(df, date_column)

        chunk_memory = dataframe_memory_mb(df)
        payload = build_payload(df)
        result = upsert_to_socrata(sink_dataset_id, payload, retry_func, dry_run=dry_run)

        summary["read_rows"] += len(data)
        summary["validated_rows"] += result.get("validated_rows", 0)
        summary["uploaded_rows"] += result.get("uploaded_rows", 0)
        summary["rejected_rows"] += result.get("rejected_rows", 0)
        summary["chunks"] += max(result.get("chunks", 0), 1)
        summary["max_chunk_memory_mb"] = max(summary["max_chunk_memory_mb"], chunk_memory)

    logger.info("sync_ideam_to_socrata summary=%s", summary)
    return summary
