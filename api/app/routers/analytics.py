"""Endpoints de analítica/dashboard. Usan los continuous aggregates cuando los
filtros lo permiten (dataset/departamento/municipio/estación) y la hypertable
cruda cuando hay filtros finos (zona, nombre de estación)."""

from fastapi import APIRouter, HTTPException

from ..catalog import DATASETS
from ..db import pool
from ..models import QueryPayload, TimeseriesPayload
from ..normalize import build_filters, department_variants, validate_required_departments

router = APIRouter(prefix="/api/analytics")

_INTERVALS = {"day": "1 day", "month": "1 month", "year": "1 year"}
_METRICS_CAGG = {
    "avg": "sum(valor_sum) / nullif(sum(n_validos), 0)",
    "sum": "sum(valor_sum)",
    "min": "min(valor_min)",
    "max": "max(valor_max)",
    "count": "sum(n)",
}
_METRICS_RAW = {
    "avg": "avg(valorobservado)",
    "sum": "sum(valorobservado)",
    "min": "min(valorobservado)",
    "max": "max(valorobservado)",
    "count": "count(*)",
}


def _can_use_cagg(payload):
    filters = payload.catalogFilters or {}
    return not filters.get("hydrologicZones") and not filters.get("stationNames")


def _cagg_filters(payload):
    """WHERE/params equivalentes a build_filters pero sobre obs_diario."""
    from ..normalize import expand_station_codes, get_dataset

    dataset = get_dataset(payload.datasetId)
    canonicals = validate_required_departments(payload.departments)
    variants = set()
    for canonical in canonicals:
        variants.update(department_variants(canonical))

    clauses = ["source_dataset_id = %(dataset_id)s", "upper(departamento) = ANY(%(departments)s)"]
    params = {"dataset_id": dataset["id"], "departments": sorted(variants)}

    filters = payload.catalogFilters or {}
    if filters.get("municipalities"):
        clauses.append("upper(municipio) = ANY(%(municipios)s)")
        params["municipios"] = [str(m).upper() for m in filters["municipalities"]]
    if filters.get("stations"):
        clauses.append("codigoestacion = ANY(%(estaciones)s)")
        params["estaciones"] = expand_station_codes(filters["stations"])
    if payload.startDate:
        clauses.append("dia >= %(start)s")
        params["start"] = payload.startDate
    if payload.endDate:
        clauses.append("dia <= %(end)s")
        params["end"] = payload.endDate
    return " AND ".join(clauses), params, dataset


@router.post("/timeseries")
def timeseries(payload: TimeseriesPayload):
    if payload.interval not in _INTERVALS:
        raise HTTPException(400, "interval debe ser day | month | year.")
    if payload.metric not in _METRICS_CAGG:
        raise HTTPException(400, "metric debe ser avg | sum | min | max | count.")
    bucket = _INTERVALS[payload.interval]

    if _can_use_cagg(payload):
        where, params, dataset = _cagg_filters(payload)
        metric_sql = _METRICS_CAGG[payload.metric]
        sql = (
            f"SELECT time_bucket('{bucket}', dia) AS bucket, {metric_sql} AS value, "
            "sum(n)::bigint AS n FROM obs_diario "
            f"WHERE {where} GROUP BY bucket ORDER BY bucket"
        )
    else:
        where, params, dataset, _canonicals = build_filters(payload)
        metric_sql = _METRICS_RAW[payload.metric]
        sql = (
            f"SELECT time_bucket('{bucket}', fechaobservacion) AS bucket, {metric_sql} AS value, "
            f"count(*)::bigint AS n FROM observaciones WHERE {where} "
            "GROUP BY bucket ORDER BY bucket"
        )

    with pool.connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {
        "datasetId": dataset["id"],
        "interval": payload.interval,
        "metric": payload.metric,
        "points": [
            {"bucket": r[0].date().isoformat(), "value": float(r[1]) if r[1] is not None else None, "n": r[2]}
            for r in rows
        ],
    }


@router.post("/summary-stats")
def summary_stats(payload: QueryPayload):
    where, params, dataset, _canonicals = build_filters(payload)
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT count(*), count(valorobservado), avg(valorobservado), "
            "stddev(valorobservado), min(valorobservado), max(valorobservado), "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY valorobservado), "
            "percentile_cont(0.95) WITHIN GROUP (ORDER BY valorobservado), "
            "count(DISTINCT codigoestacion), min(fechaobservacion), max(fechaobservacion) "
            f"FROM observaciones WHERE {where}",
            params,
        ).fetchone()
    (n, n_valid, avg, std, mn, mx, p50, p95, stations, start, end) = row
    fmt = lambda v: float(v) if v is not None else None  # noqa: E731
    return {
        "datasetId": dataset["id"],
        "rowCount": n,
        "validCount": n_valid,
        "mean": fmt(avg),
        "stddev": fmt(std),
        "min": fmt(mn),
        "max": fmt(mx),
        "median": fmt(p50),
        "p95": fmt(p95),
        "stationCount": stations,
        "observedStart": start.isoformat() if start else None,
        "observedEnd": end.isoformat() if end else None,
    }


@router.post("/by-region")
def by_region(payload: QueryPayload):
    where, params, dataset = _cagg_filters(payload)
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT departamento, sum(n)::bigint, sum(valor_sum) / nullif(sum(n_validos), 0), "
            "count(DISTINCT codigoestacion) FROM obs_diario "
            f"WHERE {where} GROUP BY departamento ORDER BY 2 DESC",
            params,
        ).fetchall()
    return {
        "datasetId": dataset["id"],
        "regions": [
            {"department": r[0], "rowCount": r[1], "mean": float(r[2]) if r[2] is not None else None, "stationCount": r[3]}
            for r in rows
        ],
    }


@router.post("/by-station")
def by_station(payload: QueryPayload):
    where, params, dataset = _cagg_filters(payload)
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT codigoestacion, max(municipio), max(departamento), sum(n)::bigint, "
            "sum(valor_sum) / nullif(sum(n_validos), 0), min(dia), max(dia) FROM obs_diario "
            f"WHERE {where} GROUP BY codigoestacion ORDER BY 4 DESC LIMIT 100",
            params,
        ).fetchall()
    return {
        "datasetId": dataset["id"],
        "stations": [
            {
                "code": r[0], "municipality": r[1], "department": r[2], "rowCount": r[3],
                "mean": float(r[4]) if r[4] is not None else None,
                "firstObservation": r[5].date().isoformat() if r[5] else None,
                "lastObservation": r[6].date().isoformat() if r[6] else None,
            }
            for r in rows
        ],
    }


@router.post("/monthly-climatology")
def monthly_climatology(payload: QueryPayload):
    where, params, dataset = _cagg_filters(payload)
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT extract(month FROM dia)::int AS mes, "
            "sum(valor_sum) / nullif(sum(n_validos), 0) AS media, "
            "min(valor_min), max(valor_max), sum(n)::bigint FROM obs_diario "
            f"WHERE {where} GROUP BY mes ORDER BY mes",
            params,
        ).fetchall()
    return {
        "datasetId": dataset["id"],
        "months": [
            {"month": r[0], "mean": float(r[1]) if r[1] is not None else None,
             "min": float(r[2]) if r[2] is not None else None,
             "max": float(r[3]) if r[3] is not None else None, "n": r[4]}
            for r in rows
        ],
    }


@router.get("/datasets-overview")
def datasets_overview():
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT source_dataset_id, sum(n)::bigint, count(DISTINCT codigoestacion), "
            "min(dia), max(dia) FROM obs_diario GROUP BY 1"
        ).fetchall()
    stats = {r[0]: r for r in rows}
    overview = []
    for dataset in DATASETS:
        r = stats.get(dataset["id"])
        overview.append(
            {
                "id": dataset["id"],
                "name": dataset["name"],
                "category": dataset["category"],
                "rowCount": r[1] if r else 0,
                "stationCount": r[2] if r else 0,
                "firstObservation": r[3].date().isoformat() if r and r[3] else None,
                "lastObservation": r[4].date().isoformat() if r and r[4] else None,
            }
        )
    return {"datasets": overview}
