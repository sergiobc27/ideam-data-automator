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
from datetime import date, timezone

import psycopg

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import hydrostats
from .. import reliability
from .. import stationarity
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
            stations = (payload.catalogFilters or {}).get("stations") or []
            if not payload.departments and not stations:
                # Excepción nacional: la diaria de TODO el país se permite solo si
                # la ventana está acotada a ≤ 1 año (366 días). Es un escaneo
                # acotado de obs_diario (un año nacional ~365 buckets), sin riesgo
                # del barrido nacional completo que motivó el candado (auditoría #4).
                ventana_dias = None
                if payload.startDate and payload.endDate:
                    try:
                        ventana_dias = (
                            date.fromisoformat(str(payload.endDate)) - date.fromisoformat(str(payload.startDate))
                        ).days
                    except ValueError:
                        ventana_dias = None
                if ventana_dias is None or ventana_dias < 0 or ventana_dias > 366:
                    raise HTTPException(
                        400,
                        "La serie diaria nacional requiere acotar la ventana a 1 año o menos (startDate y endDate); "
                        "para rangos mayores usa month o year, o filtra por departamento/estaciones.",
                    )
            # Sin departamento, la serie diaria solo se permite para POCAS
            # estaciones (hietogramas): cota anti-DoS (auditoría #4).
            if not payload.departments and len(stations) > 10:
                raise HTTPException(
                    400, "La serie diaria por estaciones admite máximo 10 a la vez; reduce la selección o usa month/year."
                )
            table, time_col = "obs_diario", "dia"
        else:
            table, time_col = "obs_mensual", "mes"
        where, params, dataset = _cagg_filters(payload, time_col)
        # Precip: excluir acumulados físicamente imposibles (corrupción residual
        # multi-sensor/centinelas) para que la lámina (metric='sum') y el heatmap
        # no muestren picos absurdos. Techo por bucket de origen: mensual 2.500,
        # diario 1.800. Saneo NO destructivo; el de origen va en el Fix #2.
        if _es_precip(dataset):
            ceiling = _MAX_PRECIP_MENSUAL_MM if table == "obs_mensual" else _MAX_PRECIP_DIARIA_MM
            where = f"({where}) AND valor_sum <= %(max_precip_bucket)s"
            params = {**params, "max_precip_bucket": ceiling}
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


# Estadísticas que NO requieren ordenar (un solo barrido): baratas a cualquier
# escala. Los percentiles SÍ exigen ordenar todas las filas y son el cuello de
# botella en selecciones enormes.
_STATS_BASE = (
    "count(*), count(valorobservado), avg(valorobservado), "
    "stddev(valorobservado), min(valorobservado), max(valorobservado), "
    "count(DISTINCT codigoestacion), min(fechaobservacion), max(fechaobservacion)"
)
_STATS_PCT = (
    "percentile_cont(0.5) WITHIN GROUP (ORDER BY valorobservado), "
    "percentile_cont(0.95) WITHIN GROUP (ORDER BY valorobservado)"
)


@router.post("/summary-stats")
def summary_stats(payload: QueryPayload):
    where, params, dataset, _canonicals = build_filters(payload)
    note = None
    try:
        with pool.connection() as conn:
            row = conn.execute(
                f"SELECT {_STATS_BASE}, {_STATS_PCT} FROM observaciones WHERE {where}",
                params,
            ).fetchone()
        (n, n_valid, avg, std, mn, mx, stations, start, end, p50, p95) = row
    except psycopg.errors.QueryCanceled:
        # Selección demasiado grande: los percentiles exactos obligan a ordenar
        # TODAS las filas y no caben en el statement_timeout. Reintentamos sin
        # percentiles (un solo barrido, barato) para devolver igual el resto de
        # estadísticas. Sacar TODOS los datos sigue disponible sin límite por el
        # Extractor; aquí solo se omite el percentil exacto en línea.
        try:
            with pool.connection() as conn:
                row = conn.execute(
                    f"SELECT {_STATS_BASE} FROM observaciones WHERE {where}",
                    params,
                ).fetchone()
            (n, n_valid, avg, std, mn, mx, stations, start, end) = row
            p50 = p95 = None
            note = (
                "La selección es demasiado grande para calcular percentiles exactos "
                "en línea (requieren ordenar todas las filas). Se muestran las demás "
                "estadísticas; para un análisis sin límite, descarga los datos desde "
                "el Extractor."
            )
        except psycopg.errors.QueryCanceled:
            raise HTTPException(
                status_code=413,
                detail=(
                    "La selección es demasiado grande para estadísticas en línea. "
                    "Acota el rango o los filtros, o descarga los datos desde el "
                    "Extractor para analizarlos sin límite."
                ),
            )
    fmt = lambda v: float(v) if v is not None else None  # noqa: E731
    result = {
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
    if note:
        result["note"] = note
    return result


# Para precipitación, el "promedio por lectura" (sum/n_validos) no tiene sentido
# físico (sale ~0,05 mm/lectura de 10 min). La métrica correcta es la LÁMINA
# MENSUAL (mm/mes) = media del acumulado mensual por estación: avg(valor_sum)
# sobre las filas (estación, mes) de obs_mensual. Se expone en campos NUEVOS
# (monthlyDepth*) SIN tocar `mean`, porque otros consumidores (bento del
# dashboard, anomalías) siguen usando `mean` como avg-por-lectura → intensidad.


def _es_precip(dataset):
    return dataset["id"] == _PRECIP_DATASET


@router.post("/by-region")
def by_region(payload: QueryPayload):
    where, params, dataset = _cagg_filters(payload, "mes")
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT departamento, sum(n)::bigint, sum(valor_sum) / nullif(sum(n_validos), 0), "
            "count(DISTINCT codigoestacion), "
            "avg(valor_sum) FILTER (WHERE valor_sum <= %(max_mensual)s) FROM obs_mensual "
            f"WHERE {where} GROUP BY departamento ORDER BY 2 DESC",
            {**params, "max_mensual": _MAX_PRECIP_MENSUAL_MM},
        ).fetchall()
    precip = _es_precip(dataset)
    return {
        "datasetId": dataset["id"],
        "regions": [
            {"department": r[0], "rowCount": r[1], "mean": float(r[2]) if r[2] is not None else None,
             "stationCount": r[3],
             "monthlyDepth": float(r[4]) if (precip and r[4] is not None) else None}
            for r in rows
        ],
    }


@router.post("/by-station")
def by_station(payload: QueryPayload):
    where, params, dataset = _cagg_filters(payload, "mes")
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT codigoestacion, max(municipio), max(departamento), sum(n)::bigint, "
            "sum(valor_sum) / nullif(sum(n_validos), 0), min(mes), max(mes), "
            "avg(valor_sum) FILTER (WHERE valor_sum <= %(max_mensual)s) FROM obs_mensual "
            f"WHERE {where} GROUP BY codigoestacion ORDER BY 4 DESC LIMIT 100",
            {**params, "max_mensual": _MAX_PRECIP_MENSUAL_MM},
        ).fetchall()
    precip = _es_precip(dataset)
    return {
        "datasetId": dataset["id"],
        "stations": [
            {
                "code": r[0], "municipality": r[1], "department": r[2], "rowCount": r[3],
                "mean": float(r[4]) if r[4] is not None else None,
                "firstObservation": _bucket_date(r[5]).isoformat() if r[5] else None,
                "lastObservation": _bucket_date(r[6]).isoformat() if r[6] else None,
                "monthlyDepth": float(r[7]) if (precip and r[7] is not None) else None,
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
            "min(valor_min), max(valor_max), sum(n)::bigint, "
            "avg(valor_sum) FILTER (WHERE valor_sum <= %(max_mensual)s), "
            "min(valor_sum) FILTER (WHERE valor_sum <= %(max_mensual)s), "
            "max(valor_sum) FILTER (WHERE valor_sum <= %(max_mensual)s) FROM obs_mensual "
            f"WHERE {where} GROUP BY mes_num ORDER BY mes_num",
            {**params, "max_mensual": _MAX_PRECIP_MENSUAL_MM},
        ).fetchall()
    precip = _es_precip(dataset)
    # Para precip, min/max climatológicos son del ACUMULADO mensual (mes más seco /
    # más lluvioso del histórico), no del extremo de una lectura suelta de 10 min.
    return {
        "datasetId": dataset["id"],
        "months": [
            {"month": r[0], "mean": float(r[1]) if r[1] is not None else None,
             "min": float(r[2]) if r[2] is not None else None,
             "max": float(r[3]) if r[3] is not None else None, "n": r[4],
             "monthlyDepth": float(r[5]) if (precip and r[5] is not None) else None,
             "monthlyDepthMin": float(r[6]) if (precip and r[6] is not None) else None,
             "monthlyDepthMax": float(r[7]) if (precip and r[7] is not None) else None}
            for r in rows
        ],
    }


# --- Hidrología: períodos de retorno, SPI, histograma -------------------------

_PRECIP_DATASET = "s54a-sgyg"
_EULER_MASCHERONI = 0.5772156649015329
# Techo físico para precipitación diaria: el récord mundial en 24 h es ~1825 mm
# (Foc-Foc, Reunión, 1966). Un valor por encima es casi seguro un sentinel/error
# de la fuente IDEAM; lo avisamos (NO lo borramos) porque contamina los ajustes.
_MAX_PRECIP_DIARIA_MM = 1800.0
# Techo físico para la LÁMINA MENSUAL (acumulado por estación-mes). El mes más
# lluvioso jamás registrado en Colombia (Chocó/Lloró) ronda ~2.000 mm; 2.500 mm
# deja margen y aun así excluye SOLO ~0,7% de los meses-estación del espejo, que
# son corrupción residual (sensores de muestreo sub-10-min cuya suma se infla,
# y centinelas): sin este techo, 180 meses imposibles (hasta 302.267 mm en una
# sola estación) envenenan la media (Valle del Cauca superaba a Chocó). Es un
# saneo NO destructivo en lectura; la limpieza de origen va en el saneo de
# ingesta (Fix #2). Auditoría de datos 2026-06-15.
_MAX_PRECIP_MENSUAL_MM = 2500.0


def _aviso_plausibilidad_precip(valores):
    """Devuelve un warning si algún valor de precipitación diaria (mm) supera el
    techo físico (~récord mundial 24 h); None si todos son plausibles."""
    if any(v is not None and v > _MAX_PRECIP_DIARIA_MM for v in valores):
        return (
            f"Hay valores de precipitación diaria por encima de {_MAX_PRECIP_DIARIA_MM:.0f} mm "
            "(cercano al récord mundial en 24 h, ~1825 mm): posible dato anómalo de la fuente "
            "IDEAM; revisa la serie antes de usar estos cuantiles."
        )
    return None


def _aviso_exclusion_precip(n_excluidos):
    """Aviso cuando se EXCLUYEN del ajuste valores de precipitación diaria
    físicamente imposibles (>techo). Saneo NO destructivo: los datos originales
    del IDEAM no se modifican, solo se omiten al calcular."""
    if n_excluidos <= 0:
        return None
    return (
        f"Se excluyeron {n_excluidos} registro(s) de precipitación diaria físicamente "
        f"imposible(s) (>{_MAX_PRECIP_DIARIA_MM:.0f} mm) del ajuste; los datos originales "
        "no se modifican."
    )


def _require_single_station(payload):
    stations = (payload.catalogFilters or {}).get("stations") or []
    if len(stations) != 1:
        raise HTTPException(400, "Selecciona exactamente una estación para este análisis.")


def build_return_periods_payload(valid_years, n_boot=400):
    """Arma el cuerpo de /return-periods desde los años válidos.

    Contrato ADITIVO y no-rompedor: 'quantiles' y 'goodnessOfFit' reflejan la
    distribución RECOMENDADA por AIC; 'gumbel {mu,beta}' se sigue calculando
    siempre (continuidad de la web actual). Se agregan 'recommended' y
    'distributions[]' con las tres candidatas autocontenidas, para que el
    usuario pueda elegir cualquiera sin recálculo."""
    maxima = [y["maximum"] for y in valid_years]
    g = hydrostats.fit_gumbel(maxima) if len(maxima) >= 4 else None
    gumbel = ({"mu": round(g["params"]["mu"], 2), "beta": round(g["params"]["beta"], 2)}
              if g else None)
    fit = hydrostats.fit_all(maxima, goodness=True, bands=True, n_boot=n_boot) if len(maxima) >= 5 else \
        {"recommended": None, "distributions": []}

    rec_name = fit["recommended"]
    rec = next((d for d in fit["distributions"] if d["name"] == rec_name), None)
    quantiles = rec["quantiles"] if rec else []
    # goodnessOfFit de nivel superior = KS-Lilliefors de la recomendada, con la
    # MISMA forma que consume la web hoy (test/statistic/critical/alpha/passes).
    gof = None
    if rec and rec.get("goodnessOfFit") and rec["goodnessOfFit"].get("ks"):
        ks = rec["goodnessOfFit"]["ks"]
        gof = {"test": "Kolmogorov-Smirnov (Lilliefors, bootstrap)",
               "statistic": ks["statistic"], "critical": ks["critical"],
               "alpha": ks["alpha"], "passes": ks["passes"], "pValue": ks["pValue"]}

    # Posiciones de Weibull (graficar) — igual que antes.
    ranked = sorted(maxima, reverse=True)
    n = len(maxima)
    empirical = [{"returnPeriod": round((n + 1) / (rank + 1), 2), "value": value}
                 for rank, value in enumerate(ranked)]

    strep = stationarity.stationarity_report(maxima)
    return {
        "stationYears": valid_years,
        "n": n,
        "mean": round(statistics.fmean(maxima), 1) if maxima else None,
        "std": round(statistics.stdev(maxima), 1) if n >= 2 else None,
        "gumbel": gumbel,
        "quantiles": quantiles,
        "empirical": empirical,
        "goodnessOfFit": gof,
        "recommended": rec_name,
        "distributions": fit["distributions"],
        "method": ("Ajuste de Gumbel, GEV y Log-Pearson III sobre máximos anuales; "
                   "recomendación por AIC; bondad por Anderson-Darling y KS-Lilliefors "
                   "(bootstrap). La recomendación es un valor por defecto: el usuario "
                   "puede elegir cualquier distribución."),
        "stationarityTests": strep,
        "reliability": reliability.reliability_report(valid_years, strep),
    }


@router.post("/return-periods")
def return_periods(payload: QueryPayload):
    """Períodos de retorno de la precipitación máxima diaria anual.

    Ajusta Gumbel, GEV y Log-Pearson III (L-momentos / momentos de logs) sobre la
    serie de máximos anuales y recomienda una por AIC; la bondad se mide por
    Anderson-Darling y KS-Lilliefors (bootstrap). Las posiciones de graficación
    empíricas usan Weibull p = m/(n+1).

    Saneo (auditoría #4): se descartan máximos no finitos o negativos (centinelas
    tipo -9999 del IDEAM contaminarían la curva), y la completitud se mide por
    días con n_validos>0, no por buckets existentes.
    """
    _require_single_station(payload)
    if payload.datasetId != _PRECIP_DATASET:
        raise HTTPException(400, "Los períodos de retorno aplican a precipitación (máxima diaria anual).")

    where, params, _dataset = _cagg_filters(payload)
    with pool.connection() as conn:
        # Saneo de cordura (no destructivo): el máximo anual IGNORA los días con
        # precipitación físicamente imposible (>techo); así un día corrupto no
        # envenena el ajuste, pero se conserva el año (recupera el mayor día
        # válido restante). Se cuentan los días excluidos para avisar.
        rows = conn.execute(
            "SELECT extract(year FROM (dia AT TIME ZONE 'UTC'))::int AS anio, "
            "max(valor_sum) FILTER (WHERE n_validos > 0 AND valor_sum >= 0 "
            "AND valor_sum <= %(max_precip)s) AS maximo, "
            "count(*) FILTER (WHERE n_validos > 0) AS dias_validos, "
            "count(*) FILTER (WHERE n_validos > 0 AND valor_sum > %(max_precip)s) AS dias_imposibles "
            f"FROM obs_diario WHERE {where} GROUP BY 1 ORDER BY 1",
            {**params, "max_precip": _MAX_PRECIP_DIARIA_MM},
        ).fetchall()

    valid_years = [
        {"year": r[0], "maximum": round(float(r[1]), 1), "days": r[2]}
        for r in rows
        if r[1] is not None and math.isfinite(r[1]) and r[1] >= 0 and r[2] >= 300
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
    aviso_excl = _aviso_exclusion_precip(sum(r[3] for r in rows))
    if aviso_excl:
        warnings.append(aviso_excl)

    payload_out = build_return_periods_payload(valid_years)
    warnings.extend(payload_out["stationarityTests"]["warnings"])
    aviso = _aviso_plausibilidad_precip(
        [y["maximum"] for y in valid_years] + [q["value"] for q in payload_out["quantiles"]]
    )
    if aviso:
        warnings.append(aviso)
    payload_out["datasetId"] = payload.datasetId
    payload_out["warnings"] = warnings
    return payload_out


_IDF_RETURN_PERIODS = (2, 5, 10, 25, 50, 100)


def _gumbel_quantiles(maxima, return_periods):
    """Ajuste Gumbel por método de momentos y cuantiles para cada Tr.
    Devuelve (params, {Tr: valor}) o (None, {}) si n<5."""
    n = len(maxima)
    if n < 5:
        return None, {}
    mean = statistics.fmean(maxima)
    std = statistics.stdev(maxima)
    if std <= 0:
        return None, {}
    beta = std * math.sqrt(6) / math.pi
    mu = mean - _EULER_MASCHERONI * beta
    quantiles = {t: mu - beta * math.log(-math.log(1 - 1 / t)) for t in return_periods}
    return {"mu": round(mu, 2), "beta": round(beta, 2)}, quantiles


def _gumbel_ks_test(maxima, mu, beta, alpha=0.05):
    """Prueba de bondad de ajuste Kolmogorov-Smirnov del Gumbel ajustado.

    Compara la CDF empírica de los máximos anuales con la teórica de Gumbel
    F(x)=exp(-exp(-(x-mu)/beta)); el estadístico D es la máxima diferencia.
    Si D < valor crítico (≈1.36/√n para α=0.05), NO se rechaza el ajuste. El
    Manual INVÍAS exige este contraste (Smirnov-Kolmogorov o Chi-cuadrado)
    antes de aceptar la distribución de extremos. Implementación pura."""
    n = len(maxima)
    if n < 5 or beta <= 0:
        return None
    ordered = sorted(maxima)
    d = 0.0
    for i, x in enumerate(ordered, start=1):
        f_teo = math.exp(-math.exp(-(x - mu) / beta))
        d = max(d, abs(f_teo - i / n), abs(f_teo - (i - 1) / n))
    d_crit = 1.36 / math.sqrt(n)  # aproximación asintótica, α=0.05
    return {
        "test": "Kolmogorov-Smirnov",
        "statistic": round(d, 4),
        "critical": round(d_crit, 4),
        "alpha": alpha,
        "passes": bool(d < d_crit),
    }


def _fit_idf_equation(samples):
    """Ajusta I = K * T^m / D^n por mínimos cuadrados log-lineal (forma de
    Vargas & Díaz-Granados, estándar en Colombia). samples: lista de
    (Tr_años, D_min, I_mm_h). Regresión de log I = b0 + m*log T - n*log D
    resuelta con ecuaciones normales 3x3 (sin dependencias externas).
    Devuelve {K, m, n, r2} o None si no hay datos suficientes."""
    pts = [(math.log(t), math.log(d), math.log(i)) for t, d, i in samples if i > 0 and t > 0 and d > 0]
    if len(pts) < 6:
        return None
    # Diseño: y = b0 + b1*x1 + b2*x2 (x1=lnT, x2=lnD; n = -b2, m = b1).
    n_obs = len(pts)
    sx1 = sum(p[0] for p in pts); sx2 = sum(p[1] for p in pts); sy = sum(p[2] for p in pts)
    sx1x1 = sum(p[0] * p[0] for p in pts); sx2x2 = sum(p[1] * p[1] for p in pts)
    sx1x2 = sum(p[0] * p[1] for p in pts)
    sx1y = sum(p[0] * p[2] for p in pts); sx2y = sum(p[1] * p[2] for p in pts)
    # Sistema normal A·b = c con A 3x3 simétrica.
    a = [[n_obs, sx1, sx2], [sx1, sx1x1, sx1x2], [sx2, sx1x2, sx2x2]]
    c = [sy, sx1y, sx2y]
    sol = _solve_3x3(a, c)
    if sol is None:
        return None
    b0, b1, b2 = sol
    # R² del ajuste en ESPACIO LOG (no es la bondad en mm/h; rotularlo así en la
    # UI — auditoría #5 #3).
    mean_y = sy / n_obs
    ss_tot = sum((p[2] - mean_y) ** 2 for p in pts)
    ss_res = sum((p[2] - (b0 + b1 * p[0] + b2 * p[1])) ** 2 for p in pts)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    K, m, n, r2log = math.exp(b0), b1, -b2, r2
    # Un ajuste degenerado puede dar inf/nan -> el token JSON `Infinity`/`NaN`
    # rompe response.json() en el navegador (auditoría #5 #6). Devolver None.
    if not all(math.isfinite(v) for v in (K, m, n, r2log)):
        return None
    return {"K": round(K, 3), "m": round(m, 3), "n": round(n, 3), "r2": round(r2log, 3), "r2Space": "log"}


def _solve_3x3(a, c):
    """Eliminación de Gauss para un sistema 3x3. None si es singular."""
    m = [row[:] + [c[i]] for i, row in enumerate(a)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(3):
            if r != col:
                factor = m[r][col] / m[col][col]
                for k in range(col, 4):
                    m[r][k] -= factor * m[col][k]
    return [m[i][3] / m[i][i] for i in range(3)]


def build_idf_curves(by_duration, durations, return_periods, n_boot=400):
    """Construye las curvas IDF eligiendo por AIC la distribución de CADA
    duración. Si la mezcla rompe la monotonicidad (intensidad no decreciente
    con la duración para algún Tr), repliega a una sola distribución global
    (mejor AIC total) y avisa. Devuelve curvas, distribución por duración y
    warnings de método. No incluye bootstrap (costo)."""
    # 1) Ajustar UNA vez por duración; cachear las candidatas por nombre y la
    # recomendada (menor AIC). aic_by_name acumula el AIC para el repliegue.
    fits, chosen, aic_by_name = {}, {}, {}
    for dur in durations:
        fit = hydrostats.fit_all(by_duration[dur], return_periods=return_periods,
                                 goodness=False, bands=True, n_boot=n_boot)
        if not fit["distributions"]:
            continue
        chosen[dur] = fit["distributions"][0]["name"]
        fits[dur] = {d["name"]: d for d in fit["distributions"]}
        for d in fit["distributions"]:
            aic_by_name[d["name"]] = aic_by_name.get(d["name"], 0.0) + d["aic"]

    def quantiles_for(dur, name):
        cand = fits.get(dur, {}).get(name)
        return {q["returnPeriod"]: q for q in cand["quantiles"]} if cand else {}

    def assemble(name_for_dur):
        curves, samples = [], []
        for tr in return_periods:
            points = []
            for dur in durations:
                if dur not in name_for_dur:
                    continue
                qe = quantiles_for(dur, name_for_dur[dur]).get(tr)
                if qe is None or qe["value"] < 0:
                    continue
                factor = dur / 60.0
                intensity = qe["value"] / factor
                point = {"durMin": dur, "depthMm": round(qe["value"], 1),
                         "intensityMmH": round(intensity, 1)}
                if "lower" in qe and "upper" in qe:
                    point["lowerMmH"] = round(qe["lower"] / factor, 1)
                    point["upperMmH"] = round(qe["upper"] / factor, 1)
                points.append(point)
                samples.append((tr, dur, intensity))
            if points:
                curves.append({"returnPeriod": tr, "points": points})
        return curves, samples

    def is_monotonic(curves):
        for curve in curves:
            intens = [p["intensityMmH"] for p in curve["points"]]
            if intens != sorted(intens, reverse=True):
                return False
        return True

    warnings = []
    curves, samples = assemble(chosen)
    if curves and not is_monotonic(curves):
        # repliegue a una sola distribución global (mejor AIC agregado)
        global_name = min(aic_by_name, key=aic_by_name.get) if aic_by_name else "Gumbel"
        chosen = {dur: global_name for dur in fits}
        curves, samples = assemble(chosen)
        if is_monotonic(curves):
            warnings.append(
                f"Curvas IDF no monótonas al mezclar distribuciones; se unificó a "
                f"{global_name} (mejor AIC agregado) para mantener coherencia.")
        else:
            warnings.append(
                f"Curvas IDF no monótonas; se unificó a {global_name} (mejor AIC agregado) "
                f"para reducir inconsistencias, pero persisten irregularidades por la "
                f"variabilidad del registro entre duraciones.")

    aviso = _aviso_plausibilidad_precip([p["depthMm"] for c in curves for p in c["points"]])
    if aviso:
        warnings.append(aviso)

    summary = None
    serie_1440 = by_duration.get(1440)
    if serie_1440 and len(serie_1440) >= 10:
        summary = stationarity.stationarity_report(serie_1440)
        if summary["stationary"] is False:
            warnings.append(
                "La serie diaria (1440 min) de esta estación no parece estacionaria "
                "(tendencia o cambio de régimen); las curvas IDF asumen estacionariedad "
                "— interpreta con cautela.")

    return {"curves": curves, "fitSamples": samples, "chosenByDuration": chosen,
            "warnings": warnings, "stationaritySummary": summary}


@router.post("/idf")
def idf(payload: QueryPayload):
    """Curvas IDF (Intensidad-Duración-Frecuencia) REALES por estación.

    Lee los máximos anuales móviles PRECOMPUTADOS (idf_max_anual; ventanas de
    10/20/30/60/120/180/360/720/1440 min sobre los datos de 10-min del IDEAM),
    elige por AIC entre Gumbel/GEV/Log-Pearson III en cada duración (con
    repliegue a una sola distribución si las curvas no resultan monótonas) y
    convierte a intensidad (mm/h = lámina / (D/60)). Ajusta además la ecuación
    I = K·T^m/D^n (Vargas & Díaz-Granados). Si la estación no está
    precomputada, lo indica.
    """
    from ..normalize import expand_station_codes

    _require_single_station(payload)
    if payload.datasetId != _PRECIP_DATASET:
        raise HTTPException(400, "Las curvas IDF aplican a precipitación.")
    code = (payload.catalogFilters or {}).get("stations", [None])[0]
    # Expandir el código (ceros a la izquierda) y match por ANY, igual que el
    # resto de endpoints: sin esto, estaciones con formato distinto entre la
    # tabla IDF y la de estaciones daban falso "no precomputada" (auditoría #5 #1).
    codes = expand_station_codes([code]) if code else []

    with pool.connection() as conn:
        estado = conn.execute(
            "SELECT anios_validos FROM idf_estado WHERE codigoestacion = ANY(%s)",
            (codes,),
        ).fetchone()
        rows = conn.execute(
            "SELECT dur_min, anio, max_mm FROM idf_max_anual "
            "WHERE codigoestacion = ANY(%s) ORDER BY dur_min, anio",
            (codes,),
        ).fetchall()

    if not rows:
        return {
            "available": False,
            "message": (
                "Esta estación aún no tiene curvas IDF precomputadas (puede no ser "
                "pluviográfica o estar en cola de cálculo)."
            ),
            "durations": [], "returnPeriods": list(_IDF_RETURN_PERIODS), "curves": [],
            "equation": None, "warnings": [],
        }

    # Saneo de cordura (no destructivo): se omiten láminas físicamente imposibles
    # (>techo) al armar las series por duración; la tabla precalculada solo guarda
    # el máximo por duración/año, así que aquí se descarta ese punto contaminado.
    by_duration = {}
    excluidos_idf = 0
    for dur, _anio, value in rows:
        v = float(value)
        if v > _MAX_PRECIP_DIARIA_MM:
            excluidos_idf += 1
            continue
        by_duration.setdefault(dur, []).append(v)

    durations = sorted(by_duration)
    n_years = estado[0] if estado else max((len(v) for v in by_duration.values()), default=0)
    warnings = []
    if n_years < 15:
        warnings.append(f"Registro corto ({n_years} años): IDF de baja confianza, evita extrapolar a Tr altos.")
    elif n_years < 25:
        warnings.append(f"{n_years} años de registro: usa con cautela los Tr de 50-100 años.")
    aviso_excl_idf = _aviso_exclusion_precip(excluidos_idf)
    if aviso_excl_idf:
        warnings.append(aviso_excl_idf)

    built = build_idf_curves(by_duration, durations, _IDF_RETURN_PERIODS)
    curves = built["curves"]
    fit_samples = built["fitSamples"]
    warnings.extend(built["warnings"])

    # Hay filas precomputadas pero <5 años válidos → Gumbel no ajusta y no hay
    # curvas: NO es "disponible", es registro insuficiente (auditoría #5 — evita
    # mostrar "disponible" con gráfico vacío).
    if not curves:
        return {
            "available": False,
            "message": (
                f"Registro insuficiente para IDF ({n_years} año(s) completo(s); "
                "se requieren al menos 5)."
            ),
            "durations": durations, "returnPeriods": list(_IDF_RETURN_PERIODS),
            "curves": [], "equation": None, "nYears": n_years, "warnings": warnings,
        }

    return {
        "available": True,
        "datasetId": payload.datasetId,
        "nYears": n_years,
        "durations": durations,
        "returnPeriods": list(_IDF_RETURN_PERIODS),
        "curves": curves,
        "chosenByDuration": built["chosenByDuration"],
        "stationaritySummary": built["stationaritySummary"],
        "equation": _fit_idf_equation(fit_samples),
        "warnings": warnings,
        "method": (
            "Máximos anuales móviles por duración (datos 10-min); por cada duración se "
            "elige Gumbel/GEV/Log-Pearson III por AIC (con repliegue a una sola "
            "distribución si las curvas no resultan monótonas); ecuación I=K·T^m/D^n por "
            "mínimos cuadrados log-lineal"
        ),
    }


@router.get("/idf-stations")
def idf_stations():
    """Estaciones con curvas IDF USABLES (>=5 años válidos ya precomputados).

    El cálculo IDF es por estación y solo una parte de la red lo tiene listo
    (estaciones pluviográficas con registro suficiente; el resto está en cola o
    no es apto). Sin esta lista, el usuario tendría que adivinar qué código
    consultar y casi siempre caería en "no disponible". Aquí devolvemos las que
    SÍ están listas, con su metadata, para poblar el selector de Hidrología.

    El ltrim(...,'0') reconcilia el formato del código entre idf_estado y
    estaciones (ceros a la izquierda; misma razón que expand_station_codes). El
    umbral 5 coincide con el mínimo que exige el endpoint /idf para ajustar
    Gumbel y emitir curvas."""
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ON (ltrim(s.codigoestacion, '0')) "
            "       e.codigoestacion, e.nombre, e.municipio, e.departamento_norm, s.anios_validos, "
            "       e.zona_hidrografica, e.corriente, "
            "       f.level, f.n, f.completeness, f.stationary, f.reasons "
            "FROM idf_estado s "
            "JOIN estaciones e ON ltrim(e.codigoestacion, '0') = ltrim(s.codigoestacion, '0') "
            "LEFT JOIN estacion_fiabilidad f ON ltrim(f.codigoestacion, '0') = ltrim(s.codigoestacion, '0') "
            "WHERE s.anios_validos >= 5 "
            "ORDER BY ltrim(s.codigoestacion, '0'), e.codigoestacion"
        ).fetchall()
    stations = [
        {
            "codigo": r[0],
            "nombre": r[1] or r[0],
            "municipio": r[2] or "N/D",
            "departamento": r[3] or "N/D",
            "aniosValidos": r[4],
            "zonaHidrografica": r[5],
            "corriente": r[6],
            # Semáforo precalculado (Lote 2.1); null si aún no se ha calculado.
            "fiabilidad": None if r[7] is None else {
                "level": r[7],
                "n": r[8],
                "completeness": r[9],
                "stationary": r[10],
                "reasons": r[11] or [],
            },
        }
        for r in rows
    ]
    stations.sort(key=lambda s: (s["departamento"], s["municipio"], s["nombre"]))
    # La lista crece a medida que el batch precomputa más estaciones; 30 min de
    # cache en el borde es buen balance entre frescura y carga.
    return JSONResponse(
        {"stations": stations, "count": len(stations)},
        headers={"cache-control": "public, max-age=1800, stale-while-revalidate=1800"},
    )


def _haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0  # radio medio terrestre (km)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


@router.get("/idf-nearest")
def idf_nearest(departamento: str = "", municipio: str = ""):
    """Sugiere la(s) estación(es) con IDF disponible MÁS CERCANAS a un municipio.

    Pensado para quien no sabe qué estación elegir: dado un municipio, ubica su
    centro (centroide de las estaciones IDEAM de ese municipio, única fuente de
    coordenadas) y rankea por distancia las estaciones con análisis disponible
    (idf_estado.anios_validos >= 5). Devuelve la distancia en km para que el
    usuario juzgue la representatividad (a más distancia / terreno distinto,
    menos). Las curvas IDF siguen siendo de punto: esto solo recomienda cuál."""
    from ..normalize import canonical_department, department_variants

    municipio = (municipio or "").strip()
    if not municipio:
        raise HTTPException(400, "Indica un municipio.")
    canonical = canonical_department(departamento) if departamento else None
    variants = [v.upper() for v in department_variants(canonical)] if canonical else []

    with pool.connection() as conn:
        # Centro del municipio = promedio de coordenadas de SUS estaciones.
        # Match insensible a may/min Y a tildes (translate): el municipio del
        # dropdown viene de mv_catalogo y el centroide se calcula en estaciones;
        # si difieren en una tilde, igual debe casar.
        mun_norm = "translate(upper(municipio), 'ÁÉÍÓÚÜÑ', 'AEIOUUN')"
        where = (
            f"{mun_norm} = translate(upper(%(mun)s), 'ÁÉÍÓÚÜÑ', 'AEIOUUN') "
            "AND latitud BETWEEN -5 AND 14 AND longitud BETWEEN -82 AND -66"
        )
        params = {"mun": municipio}
        if variants:
            where += " AND upper(departamento_norm) = ANY(%(dep)s)"
            params["dep"] = variants
        # avg(altitud) = altura media del municipio, para la Δaltitud (en zona de
        # montaña pesa más que la distancia horizontal: distinto piso térmico).
        loc = conn.execute(
            f"SELECT avg(latitud), avg(longitud), count(*), avg(altitud) FROM estaciones WHERE {where}",
            params,
        ).fetchone()
        if not loc or not loc[2] or loc[0] is None:
            return {
                "located": False, "municipio": municipio, "departamento": departamento, "stations": [],
                "message": "No pudimos ubicar ese municipio en el catálogo; usa la lista de estaciones.",
            }
        clat, clon = float(loc[0]), float(loc[1])
        calt = float(loc[3]) if loc[3] is not None else None
        rows = conn.execute(
            "SELECT DISTINCT ON (ltrim(s.codigoestacion, '0')) "
            "       e.codigoestacion, e.nombre, e.municipio, e.departamento_norm, "
            "       e.latitud, e.longitud, e.altitud, s.anios_validos "
            "FROM idf_estado s "
            "JOIN estaciones e ON ltrim(e.codigoestacion, '0') = ltrim(s.codigoestacion, '0') "
            "WHERE s.anios_validos >= 5 "
            "AND e.latitud BETWEEN -5 AND 14 AND e.longitud BETWEEN -82 AND -66 "
            "ORDER BY ltrim(s.codigoestacion, '0'), e.codigoestacion"
        ).fetchall()

    ranked = []
    for r in rows:
        d = _haversine_km(clat, clon, float(r[4]), float(r[5]))
        st_alt = float(r[6]) if r[6] is not None else None
        alt_diff = round(st_alt - calt) if (st_alt is not None and calt is not None) else None
        ranked.append({
            "codigo": r[0],
            "nombre": r[1] or r[0],
            "municipio": r[2] or "N/D",
            "departamento": r[3] or "N/D",
            "aniosValidos": r[7],
            "distanceKm": round(d, 1),
            "altDiffM": alt_diff,
            "sameMunicipio": (r[2] or "").strip().upper() == municipio.upper(),
        })
    ranked.sort(key=lambda x: x["distanceKm"])
    return JSONResponse(
        {"located": True, "municipio": municipio, "departamento": departamento, "stations": ranked[:5]},
        headers={"cache-control": "public, max-age=1800, stale-while-revalidate=1800"},
    )


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
            # NO se hace coalesce(valor_sum,0): un mes presente pero sin medición
            # válida (n_validos=0 → valor_sum NULL) es un HUECO, no "0 mm de lluvia".
            # Tratarlo como 0 sesgaba el SPI hacia falsas sequías. Los huecos se
            # saltan abajo y las ventanas que los tocan quedan invalidadas.
            "SELECT (mes AT TIME ZONE 'UTC')::date AS mes, valor_sum "
            f"FROM obs_mensual WHERE {where} ORDER BY 1",
            params,
        ).fetchall()

    if len(rows) < payload.scale + 12:
        return {"scale": payload.scale, "points": [], "latest": None,
                "warnings": ["Registro mensual insuficiente para calcular el SPI."]}

    # Serie mensual CONTIGUA: los huecos invalidan las ventanas que los tocan.
    # Un mes con valor_sum NULL (presente pero sin medición válida) se SALTA → se
    # comporta como hueco, no como 0 mm (evita falsas sequías en el SPI).
    monthly = {(r[0].year, r[0].month): float(r[1]) for r in rows if r[1] is not None}
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
    # Techo del SPI no-paramétrico: con m años de historia el percentil se acota
    # a [1/2m, 1-1/2m] (Hazen), así que |SPI| no puede superar este valor; con
    # registros cortos las categorías extremas son INALCANZABLES (artefacto
    # conocido, no error). Se expone para honestidad metodológica.
    min_history = min((len(v) for v in by_calendar_month.values()), default=0)
    spi_ceiling = round(abs(normal.inv_cdf(1 / (2 * max(min_history, 1)))), 2) if min_history else None
    for year, month, total in windows:
        history = by_calendar_month[month]
        m = len(history)
        if m < 3:
            # Historia insuficiente: el SPI no es interpretable (sale ~0 siempre).
            warnings.add("Algunos meses tienen <3 años de historia: SPI no calculable en ellos.")
            points.append({
                "month": f"{year:04d}-{month:02d}",
                "precipitation": round(total, 1),
                "spi": None,
                "category": "No calculable",
            })
            continue
        if m < 15:
            warnings.add("Algunos meses tienen menos de 15 años de historia: SPI menos confiable en ellos.")
        # Percentil empírico con corrección de bordes (Hazen) para evitar +-inf.
        rank = sum(1 for value in history if value <= total)
        p = min(max(rank / (m + 1), 1 / (2 * m)), 1 - 1 / (2 * m))
        z = round(normal.inv_cdf(p), 2)
        points.append({
            "month": f"{year:04d}-{month:02d}",
            "precipitation": round(total, 1),
            "spi": z,
            "category": _spi_category(z),
        })

    if spi_ceiling is not None and spi_ceiling < 2:
        warnings.add(
            f"Con el registro disponible, |SPI| no supera ±{spi_ceiling}: las categorías "
            "extremas (±2) no son alcanzables (limitación del método no-paramétrico)."
        )

    latest = next((p for p in reversed(points) if p["spi"] is not None), points[-1] if points else None)
    return {
        "scale": payload.scale,
        "points": points,
        "latest": latest,
        "spiCeiling": spi_ceiling,
        "warnings": sorted(warnings),
        "method": "SPI no-paramétrico (percentil empírico Hazen -> inversa normal) sobre acumulados móviles",
    }


@router.post("/histogram")
def histogram(payload: HistogramPayload):
    """Histograma de acumulados diarios de precipitación (días secos aparte)."""
    _require_single_station(payload)
    if payload.datasetId != _PRECIP_DATASET:
        raise HTTPException(400, "El histograma de acumulados diarios aplica a precipitación.")
    where, params, _dataset = _cagg_filters(payload)
    with pool.connection() as conn:
        # Día seco = MEDIDO y sin lluvia (n_validos>0). Un bucket con todas las
        # lecturas NULL es "sin dato", NO un día seco (auditoría #4): contarlo
        # como seco sesgaba el histograma hacia falsas sequías. dias/wet/max en
        # una sola pasada con FILTER (antes 2 escaneos).
        bounds = conn.execute(
            "SELECT count(*) FILTER (WHERE n_validos > 0 AND valor_sum > 0), "
            "count(*) FILTER (WHERE n_validos > 0 AND coalesce(valor_sum, 0) = 0), "
            "count(*) FILTER (WHERE n_validos IS NULL OR n_validos = 0), "
            "max(valor_sum) FILTER (WHERE n_validos > 0) "
            f"FROM obs_diario WHERE {where}",
            params,
        ).fetchone()
        wet_days, dry_days, no_data_days, max_value = bounds[0], bounds[1], bounds[2], float(bounds[3] or 0)
        buckets = []
        if wet_days and max_value > 0:
            buckets = conn.execute(
                f"SELECT width_bucket(valor_sum, 0, %(h_max)s, %(h_bins)s) AS bucket, count(*) "
                f"FROM obs_diario WHERE {where} AND n_validos > 0 AND valor_sum > 0 GROUP BY 1 ORDER BY 1",
                {**params, "h_max": max_value + 1e-9, "h_bins": payload.bins},
            ).fetchall()

    width = (max_value + 1e-9) / payload.bins if max_value > 0 else 0
    counts = {b[0]: b[1] for b in buckets}
    return {
        "dryDays": dry_days,
        "wetDays": wet_days,
        "noDataDays": no_data_days,
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
