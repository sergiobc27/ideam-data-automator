from datetime import datetime, timezone

from fastapi import APIRouter, Query

from ..catalog import CATALOG_FILTERS, DATASETS, DEPARTMENT_MAP
from ..db import pool
from ..normalize import department_variants, get_dataset, validate_required_departments
from ..settings import settings

router = APIRouter()


@router.get("/api/health")
def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


def _data_freshness():
    # Frescura del espejo desde ingest_state (high-water mark del delta):
    # instantáneo, sin tocar la hypertable. Es informativo: si la DB no
    # responde, /api/meta sigue funcionando con valores nulos.
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "SELECT max(hwm_fecha), max(updated_at) FROM ingest_state "
                "WHERE grain = 'delta' AND status = 'done'"
            ).fetchone()
        return {
            "latestObservation": row[0].isoformat() if row and row[0] else None,
            "lastSync": row[1].isoformat() if row and row[1] else None,
        }
    except Exception:
        return {"latestObservation": None, "lastSync": None}


@router.get("/api/meta")
def meta():
    return {
        "datasets": [
            {"id": d["id"], "name": d["name"], "category": d["category"], "dateColumn": d["dateColumn"]}
            for d in DATASETS
        ],
        "departments": sorted(DEPARTMENT_MAP.keys()),
        "previewLimit": settings.preview_limit,
        "exportPageSize": settings.export_page_size,
        "maxExportRows": settings.export_max_rows,
        "catalogFilters": CATALOG_FILTERS,
        "dataFreshness": _data_freshness(),
    }


@router.get("/api/date-range")
def date_range(datasetId: str):
    dataset = get_dataset(datasetId)
    # min/max desde obs_diario (agregado continuo): instantáneo. Sobre la
    # hypertable cruda, los datasets que terminaron en el pasado (los de mar,
    # hasta 2020) obligaban a un ChunkAppend hacia atrás desde 2026 saltando
    # ~6 años de chunks vacíos -> timeout de 30s. obs_diario ya tiene el rango.
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT min(dia), max(dia) FROM obs_diario WHERE source_dataset_id = %s",
            (dataset["id"],),
        ).fetchone()
    start, end = row
    return {
        "datasetId": dataset["id"],
        "dateColumn": dataset["dateColumn"],
        "startDate": start.date().isoformat() if start else None,
        "endDate": end.date().isoformat() if end else None,
        "startYear": start.year if start else None,
        "endYear": end.year if end else None,
        "cachedAt": datetime.now(timezone.utc).isoformat(),
        "cacheTtlSeconds": 0,
    }


@router.get("/api/municipalities")
def municipalities(department: list[str] = Query(default=[])):
    canonicals = validate_required_departments(department)
    variants = set()
    for canonical in canonicals:
        variants.update(department_variants(canonical))
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT municipio FROM mv_catalogo "
            "WHERE upper(departamento) = ANY(%s) AND municipio IS NOT NULL ORDER BY municipio",
            (sorted(variants),),
        ).fetchall()
    return {"municipalities": [r[0] for r in rows]}
