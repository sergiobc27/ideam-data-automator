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
        "maxExportRows": None,
        "catalogFilters": CATALOG_FILTERS,
    }


@router.get("/api/date-range")
def date_range(datasetId: str):
    dataset = get_dataset(datasetId)
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT min(fechaobservacion), max(fechaobservacion) "
            "FROM observaciones WHERE source_dataset_id = %s",
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
