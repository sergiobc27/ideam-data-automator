"""Endpoints de analítica/dashboard. Usan los continuous aggregates cuando los
filtros lo permiten (dataset/departamento/municipio/estación) y la hypertable
cruda cuando hay filtros finos (zona, nombre de estación).

A diferencia de exports/preview, la analítica agregada permite consultas SIN
departamentos (alcance nacional): corre sobre los caggs, donde el país entero
del dataset más grande resuelve en <1s. Las vistas mensuales/anuales y los
rankings usan obs_mensual (~24x más rápido que obs_diario a escala nacional);
solo la serie diaria usa obs_diario y esa sí exige departamentos."""

import math
import statistics
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..caggs import cagg_filters as _cagg_filters, can_use_cagg as _can_use_cagg
from ..catalog import DATASETS
from ..db import pool
from ..models import HistogramPayload, QueryPayload, SpiPayload, TimeseriesPayload
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
            headers={"Retry-After": str(max(retry, 60))},
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
        # Excepción: con estaciones concretas (hietogramas) el escaneo diario
        # es trivial aunque no haya departamento.
        if payload.interval == "day":
            if not payload.departments and not (payload.catalogFilters or {}).get("stations"):
                raise HTTPException(
                    400, "La serie diaria requiere un departamento o estaciones concretas; usa month o year para el país completo."
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


# --- Hidrología: períodos de retorno, SPI, histograma -------------------------

_PRECIP_DATASET = "s54a-sgyg"
_EULER_MASCHERONI = 0.5772156649015329


def _require_single_station(payload):
    stations = (payload.catalogFilters or {}).get("stations") or []
    if len(stations) != 1:
        raise HTTPException(400, "Selecciona exactamente una estación para este análisis.")


@router.post("/return-periods")
def return_periods(payload: QueryPayload):
    """Períodos de retorno de la precipitación máxima diaria anual.

    Método: serie de máximos anuales (máximo del ACUMULADO diario valor_sum,
    solo años con >=300 días de datos) + ajuste Gumbel por método de momentos
    (Chow, Maidment & Mays, 'Applied Hydrology'): beta = s*sqrt(6)/pi,
    mu = media - 0.5772*beta; x_T = mu - beta*ln(-ln(1 - 1/T)). Las posiciones
    de graficación empíricas usan Weibull p = m/(n+1).
    """
    _require_single_station(payload)
    if payload.datasetId != _PRECIP_DATASET:
        raise HTTPException(400, "Los períodos de retorno aplican a precipitación (máxima diaria anual).")

    where, params, _dataset = _cagg_filters(payload)
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT extract(year FROM (dia AT TIME ZONE 'UTC'))::int AS anio, "
            "max(valor_sum) AS maximo, count(*) AS dias "
            f"FROM obs_diario WHERE {where} GROUP BY 1 ORDER BY 1",
            params,
        ).fetchall()

    valid_years = [
        {"year": r[0], "maximum": round(float(r[1]), 1), "days": r[2]}
        for r in rows
        if r[1] is not None and r[2] >= 300
    ]
    discarded = len(rows) - len(valid_years)
    n = len(valid_years)

    warnings = []
    if discarded:
        warnings.append(f"{discarded} año(s) descartado(s) por tener menos de 300 días de datos.")
    if n < 15:
        warnings.append("Registro corto (<15 años válidos): estimación de BAJA confianza.")
    elif n < 30:
        warnings.append("Registro de menos de 30 años: usa con cautela los Tr altos (50-100 años).")

    if n < 5:
        return {"stationYears": valid_years, "n": n, "warnings": warnings, "gumbel": None, "quantiles": [], "empirical": []}

    maxima = [y["maximum"] for y in valid_years]
    mean = statistics.fmean(maxima)
    std = statistics.stdev(maxima)
    beta = std * math.sqrt(6) / math.pi
    mu = mean - _EULER_MASCHERONI * beta

    quantiles = [
        {"returnPeriod": t, "value": round(mu - beta * math.log(-math.log(1 - 1 / t)), 1)}
        for t in (2, 5, 10, 25, 50, 100)
    ]
    # Posiciones de Weibull sobre los máximos observados (para graficar).
    ranked = sorted(maxima, reverse=True)
    empirical = [
        {"returnPeriod": round((n + 1) / (rank + 1), 2), "value": value}
        for rank, value in enumerate(ranked)
    ]

    return {
        "datasetId": payload.datasetId,
        "stationYears": valid_years,
        "n": n,
        "mean": round(mean, 1),
        "std": round(std, 1),
        "gumbel": {"mu": round(mu, 2), "beta": round(beta, 2)},
        "quantiles": quantiles,
        "empirical": empirical,
        "warnings": warnings,
        "method": "Gumbel por método de momentos sobre máximos anuales de precipitación diaria",
    }


_SPI_CATEGORIES = [
    (-2.0, "Sequía extrema"),
    (-1.5, "Sequía severa"),
    (-1.0, "Sequía moderada"),
    (1.0, "Normal"),
    (1.5, "Moderadamente húmedo"),
    (2.0, "Muy húmedo"),
]


def _spi_category(z):
    for threshold, label in _SPI_CATEGORIES:
        if z < threshold:
            return label
    return "Extremadamente húmedo"


@router.post("/spi")
def spi(payload: SpiPayload):
    """SPI (Índice de Precipitación Estandarizada) por percentiles empíricos.

    Acumulados móviles de `scale` meses sobre obs_mensual; cada ventana se
    compara contra la distribución HISTÓRICA del mismo mes calendario y el
    percentil se transforma con la inversa de la normal (NormalDist.inv_cdf).
    Variante no-paramétrica del SPI (la canónica ajusta una gamma — WMO SPI
    User Guide); más robusta con registros imperfectos, documentada como
    aproximación.
    """
    _require_single_station(payload)
    if payload.datasetId != _PRECIP_DATASET:
        raise HTTPException(400, "El SPI se calcula sobre precipitación.")
    if payload.scale not in (3, 6, 12):
        raise HTTPException(400, "scale debe ser 3, 6 o 12 meses.")

    where, params, _dataset = _cagg_filters(payload, "mes")
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT (mes AT TIME ZONE 'UTC')::date AS mes, coalesce(valor_sum, 0) "
            f"FROM obs_mensual WHERE {where} ORDER BY 1",
            params,
        ).fetchall()

    if len(rows) < payload.scale + 12:
        return {"scale": payload.scale, "points": [], "latest": None,
                "warnings": ["Registro mensual insuficiente para calcular el SPI."]}

    # Serie mensual CONTIGUA: los huecos invalidan las ventanas que los tocan.
    monthly = {(r[0].year, r[0].month): float(r[1]) for r in rows}
    first, last = rows[0][0], rows[-1][0]

    def month_seq(start, end):
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            yield (y, m)
            m += 1
            if m == 13:
                y, m = y + 1, 1

    sequence = list(month_seq(first, last))
    windows = []  # (year, month_fin, acumulado) solo ventanas completas
    for index in range(payload.scale - 1, len(sequence)):
        window = sequence[index - payload.scale + 1 : index + 1]
        if all(key in monthly for key in window):
            year, month = sequence[index]
            windows.append((year, month, sum(monthly[key] for key in window)))

    by_calendar_month = {}
    for year, month, total in windows:
        by_calendar_month.setdefault(month, []).append(total)

    normal = statistics.NormalDist()
    points = []
    warnings = set()
    for year, month, total in windows:
        history = by_calendar_month[month]
        m = len(history)
        if m < 15:
            warnings.add("Algunos meses tienen menos de 15 años de historia: SPI menos confiable en ellos.")
        # Percentil empírico con corrección de bordes para evitar +-inf.
        rank = sum(1 for value in history if value <= total)
        p = min(max(rank / (m + 1), 1 / (2 * m)), 1 - 1 / (2 * m))
        z = round(normal.inv_cdf(p), 2)
        points.append({
            "month": f"{year:04d}-{month:02d}",
            "precipitation": round(total, 1),
            "spi": z,
            "category": _spi_category(z),
        })

    return {
        "scale": payload.scale,
        "points": points,
        "latest": points[-1] if points else None,
        "warnings": sorted(warnings),
        "method": "SPI no-paramétrico (percentil empírico -> inversa normal) sobre acumulados móviles",
    }


@router.post("/histogram")
def histogram(payload: HistogramPayload):
    """Histograma de acumulados diarios de precipitación (días secos aparte)."""
    _require_single_station(payload)
    if payload.datasetId != _PRECIP_DATASET:
        raise HTTPException(400, "El histograma de acumulados diarios aplica a precipitación.")
    where, params, _dataset = _cagg_filters(payload)
    with pool.connection() as conn:
        bounds = conn.execute(
            f"SELECT count(*), max(valor_sum) FROM obs_diario WHERE {where} AND valor_sum > 0",
            params,
        ).fetchone()
        wet_days, max_value = bounds[0], float(bounds[1] or 0)
        dry_days = conn.execute(
            f"SELECT count(*) FROM obs_diario WHERE {where} AND coalesce(valor_sum, 0) = 0",
            params,
        ).fetchone()[0]
        buckets = []
        if wet_days and max_value > 0:
            buckets = conn.execute(
                f"SELECT width_bucket(valor_sum, 0, %(h_max)s, %(h_bins)s) AS bucket, count(*) "
                f"FROM obs_diario WHERE {where} AND valor_sum > 0 GROUP BY 1 ORDER BY 1",
                {**params, "h_max": max_value + 1e-9, "h_bins": payload.bins},
            ).fetchall()

    width = (max_value + 1e-9) / payload.bins if max_value > 0 else 0
    counts = {b[0]: b[1] for b in buckets}
    return {
        "dryDays": dry_days,
        "wetDays": wet_days,
        "maxDaily": round(max_value, 1),
        "bins": [
            {
                "from": round(width * (i - 1), 1),
                "to": round(width * i, 1),
                "count": counts.get(i, 0),
            }
            for i in range(1, payload.bins + 1)
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
    # GET cacheable: el contenido solo cambia con el delta (2x/día).
    return JSONResponse(
        {"datasets": overview},
        headers={"cache-control": "public, max-age=3600, stale-while-revalidate=3600"},
    )
