import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from ..catalog import CATALOG_FILTERS_BY_KEY
from ..db import pool
from ..ratelimit import check_rate_limit
from ..models import CatalogBundlePayload, CatalogOptionsPayload, QueryPayload
from ..normalize import (
    build_filters,
    department_variants,
    get_dataset,
    normalize_label,
    validate_required_departments,
)
from ..settings import settings

router = APIRouter()

BUNDLE_COLUMNS = ["departamento", "municipio", "zonahidrografica", "codigoestacion", "nombreestacion", "total"]


def _client_ip(request: Request):
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def _catalog_rate(request: Request):
    ok, _remaining, retry = check_rate_limit(
        "catalogo", _client_ip(request), settings.rate_limit_catalog_per_hour
    )
    if not ok:
        raise HTTPException(
            429,
            f"Limite de consultas de catalogo alcanzado. Intenta de nuevo en {max(retry // 60, 1)} minuto(s).",
        )


def _now():
    return datetime.now(timezone.utc).isoformat()


def _mv_filter(payload):
    """WHERE para mv_catalogo (vista materializada, instantánea) desde el payload:
    dataset + departamentos + filtros de catálogo que viven en la vista. Evita el
    GROUP BY sobre la hypertable cruda (764M filas) que daba timeout de 30s en los
    desplegables de departamentos grandes."""
    dataset = get_dataset(payload.datasetId)
    canonicals = validate_required_departments(payload.departments)
    variants = set()
    for canonical in canonicals:
        variants.update(department_variants(canonical))
    clauses = ["source_dataset_id = %(dataset_id)s", "upper(departamento) = ANY(%(deps)s)"]
    params = {"dataset_id": dataset["id"], "deps": sorted(variants)}
    filters = getattr(payload, "catalogFilters", None) or {}
    if filters.get("municipalities"):
        clauses.append("upper(municipio) = ANY(%(municipios)s)")
        params["municipios"] = [str(m).upper() for m in filters["municipalities"]]
    if filters.get("hydrologicZones"):
        clauses.append("upper(zonahidrografica) = ANY(%(zonas)s)")
        params["zonas"] = [str(z).upper() for z in filters["hydrologicZones"]]
    return " AND ".join(clauses), params, dataset


@router.post("/api/catalog-bundle")
def catalog_bundle(payload: CatalogBundlePayload, request: Request):
    _catalog_rate(request)
    dataset = get_dataset(payload.datasetId)
    canonicals = validate_required_departments(payload.departments)
    variants = set()
    for canonical in canonicals:
        variants.update(department_variants(canonical))

    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT departamento, municipio, zonahidrografica, codigoestacion, nombreestacion, "
            "       sum(total)::bigint AS total "
            "FROM mv_catalogo WHERE source_dataset_id = %s AND upper(departamento) = ANY(%s) "
            "GROUP BY 1,2,3,4,5 ORDER BY 1,2,4",
            (dataset["id"], sorted(variants)),
        ).fetchall()

    return {
        "datasetId": dataset["id"],
        "departments": canonicals,
        "columns": BUNDLE_COLUMNS,
        "rows": [dict(zip(BUNDLE_COLUMNS, r)) for r in rows],
        "cachedAt": _now(),
        "cacheTtlSeconds": 0,
        "x-ideam-cache": "DB",
    }


@router.post("/api/catalog-options")
def catalog_options(payload: CatalogOptionsPayload, request: Request):
    _catalog_rate(request)
    definition = CATALOG_FILTERS_BY_KEY.get(payload.attributeKey)
    if not definition:
        raise HTTPException(400, "attributeKey invalido.")

    where, params, _dataset = _mv_filter(payload)
    column = definition["column"]
    label_column = definition.get("labelColumn")

    select = f"{column} AS value"
    group = column
    if label_column:
        select += f", max({label_column}) AS label"

    with pool.connection() as conn:
        rows = conn.execute(
            f"SELECT {select}, sum(total)::bigint AS total FROM mv_catalogo "
            f"WHERE {where} AND {column} IS NOT NULL GROUP BY {group} ORDER BY {group} LIMIT 5000",
            params,
        ).fetchall()

    options = []
    for row in rows:
        if label_column:
            options.append({"value": row[0], "label": row[1], "total": row[2]})
        else:
            options.append({"value": row[0], "total": row[1]})

    return {
        "attributeKey": payload.attributeKey,
        "options": options,
        "cachedAt": _now(),
        "cacheTtlSeconds": 0,
    }


@router.post("/api/stations-helper")
def stations_helper(payload: QueryPayload, request: Request):
    _catalog_rate(request)
    where, params, _dataset = _mv_filter(payload)
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT codigoestacion, max(nombreestacion), max(departamento), max(municipio), "
            "       max(zonahidrografica), sum(total)::bigint "
            f"FROM mv_catalogo WHERE {where} GROUP BY codigoestacion "
            "ORDER BY 2 NULLS LAST LIMIT 500",
            params,
        ).fetchall()
    return {
        "stations": [
            {
                "code": r[0],
                "name": r[1] or r[0],
                "department": r[2] or "",
                "municipality": r[3] or "",
                "zone": r[4] or "",
                "entity": f"{r[5]:,} filas".replace(",", "."),
            }
            for r in rows
        ]
    }


@router.post("/api/coverage")
def coverage(payload: QueryPayload, request: Request):
    _catalog_rate(request)
    t0 = time.time()
    dataset = get_dataset(payload.datasetId)
    canonicals = validate_required_departments(payload.departments)

    reports = []
    total_matched = 0
    with pool.connection() as conn:
        for canonical in canonicals:
            variants = department_variants(canonical)
            rows = conn.execute(
                "SELECT departamento, sum(total)::bigint FROM mv_catalogo "
                "WHERE source_dataset_id = %s AND upper(departamento) = ANY(%s) GROUP BY 1",
                (dataset["id"], variants),
            ).fetchall()
            matched = [
                {"departamento": r[0], "normalized": normalize_label(r[0]), "total": r[1]}
                for r in rows
            ]
            matched_rows = sum(m["total"] for m in matched)
            total_matched += matched_rows
            reports.append(
                {
                    "department": canonical,
                    "configured_variants": variants,
                    "matched": matched,
                    "matched_rows": matched_rows,
                    "unmatched_rows": 0,
                    "unmatched_discovered": [],
                }
            )

    return {
        "datasetId": dataset["id"],
        "reports": reports,
        "stationPoolSize": 0,
        "queryPlans": 1,
        "totalMatchedRows": total_matched,
        "totalUnmatchedRows": 0,
        "processingMs": int((time.time() - t0) * 1000),
    }


@router.get("/api/catalog-status")
def catalog_status():
    with pool.connection() as conn:
        populated = conn.execute(
            "SELECT relispopulated FROM pg_class WHERE relname = 'mv_catalogo'"
        ).fetchone()
        stats = conn.execute(
            "SELECT count(*), coalesce(sum(total),0) FROM mv_catalogo"
        ).fetchone() if populated and populated[0] else (0, 0)
    return {
        "cacheVersion": "postgres-mv",
        "populated": bool(populated and populated[0]),
        "catalogRows": stats[0],
        "observationsCovered": int(stats[1]),
        "checkedAt": _now(),
    }
