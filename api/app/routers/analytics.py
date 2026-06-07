"""Endpoints de analítica/dashboard. Usan los continuous aggregates cuando los
filtros lo permiten (dataset/departamento/municipio/estación) y la hypertable
cruda cuando hay filtros finos (zona, nombre de estación).

A diferencia de exports/preview, la analítica agregada permite consultas SIN
departamentos (alcance nacional): corre sobre los caggs, donde el país entero
del dataset más grande resuelve en <1s. Las vistas mensuales/anuales y los
rankings usan obs_mensual (~24x más rápido que obs_diario a escala nacional);
solo la serie diaria usa obs_diario y esa sí exige departamentos."""

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from ..caggs import cagg_filters as _cagg_filters, can_use_cagg as _can_use_cagg
from ..catalog import DATASETS
from ..db import pool
from ..models import QueryPayload, TimeseriesPayload
from ..normalize import build_filters
from ..ratelimit import check_rate_limit
from ..settings import settings


def _client_ip(request: Request):
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def analytics_rate(request: Request):
    """Dependencia a nivel de router: limita TODAS las rutas de analítica."""
    ok, _remaining, retry = check_rate_limit(
        "lectura", _client_ip(request), settings.rate_limit_catalog_per_hour
    )
    if not ok:
        raise HTTPException(
            429,
            f"Limite de consultas alcanzado. Intenta de nuevo en {max(retry // 60, 1)} minuto(s).",
        )


router = APIRouter(prefix="/api/analytics", dependencies=[Depends(analytics_rate)])

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


def _bucket_date(value):
    """Los caggs están alineados a UTC pero la sesión corre en America/Bogota:
    .date() directo regresaría el día/mes/año ANTERIOR. Se convierte a UTC."""
    return value.astimezone(timezone.utc).date()


# _can_use_cagg / _cagg_filters viven en app.caggs (compartidos con export);
# los alias del import preservan los nombres históricos de este módulo.


@router.post("/timeseries")
def timeseries(payload: TimeseriesPayload):
    if payload.interval not in _INTERVALS:
        raise HTTPException(400, "interval debe ser day | month | year.")
    if payload.metric not in _METRICS_CAGG:
        raise HTTPException(400, "metric debe ser avg | sum | min | max | count.")
    bucket = _INTERVALS[payload.interval]

    if _can_use_cagg(payload):
        # month/year salen de obs_mensual (rápido incluso a escala nacional);
        # day necesita obs_diario y a nivel nacional sería demasiado pesado.
        if payload.interval == "day":
            if not payload.departments:
                raise HTTPException(
                    400, "La serie diaria requiere al menos un departamento; usa month o year para el país completo."
                )
            table, time_col = "obs_diario", "dia"
        else:
            table, time_col = "obs_mensual", "mes"
        where, params, dataset = _cagg_filters(payload, time_col)
        metric_sql = _METRICS_CAGG[payload.metric]
        sql = (
            f"SELECT time_bucket('{bucket}', {time_col}) AS bucket, {metric_sql} AS value, "
            f"sum(n)::bigint AS n FROM {table} "
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
            {"bucket": _bucket_date(r[0]).isoformat(), "value": float(r[1]) if r[1] is not None else None, "n": r[2]}
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
    where, params, dataset = _cagg_filters(payload, "mes")
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT departamento, sum(n)::bigint, sum(valor_sum) / nullif(sum(n_validos), 0), "
            "count(DISTINCT codigoestacion) FROM obs_mensual "
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
    where, params, dataset = _cagg_filters(payload, "mes")
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT codigoestacion, max(municipio), max(departamento), sum(n)::bigint, "
            "sum(valor_sum) / nullif(sum(n_validos), 0), min(mes), max(mes) FROM obs_mensual "
            f"WHERE {where} GROUP BY codigoestacion ORDER BY 4 DESC LIMIT 100",
            params,
        ).fetchall()
    return {
        "datasetId": dataset["id"],
        "stations": [
            {
                "code": r[0], "municipality": r[1], "department": r[2], "rowCount": r[3],
                "mean": float(r[4]) if r[4] is not None else None,
                "firstObservation": _bucket_date(r[5]).isoformat() if r[5] else None,
                "lastObservation": _bucket_date(r[6]).isoformat() if r[6] else None,
            }
            for r in rows
        ],
    }


@router.post("/monthly-climatology")
def monthly_climatology(payload: QueryPayload):
    where, params, dataset = _cagg_filters(payload, "mes")
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT extract(month FROM (mes AT TIME ZONE 'UTC'))::int AS mes_num, "
            "sum(valor_sum) / nullif(sum(n_validos), 0) AS media, "
            "min(valor_min), max(valor_max), sum(n)::bigint FROM obs_mensual "
            f"WHERE {where} GROUP BY mes_num ORDER BY mes_num",
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
            "min(mes), max(mes) FROM obs_mensual GROUP BY 1"
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
                "firstObservation": _bucket_date(r[3]).isoformat() if r and r[3] else None,
                "lastObservation": _bucket_date(r[4]).isoformat() if r and r[4] else None,
            }
        )
    return {"datasets": overview}
