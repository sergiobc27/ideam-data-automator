"""Lote 2.1 — precálculo del semáforo de fiabilidad por estación.

Recorre las estaciones con IDF (idf_estado) y, sobre el AGREGADO DIARIO, calcula
exactamente los mismos máximos anuales / estacionariedad / fiabilidad que el
semáforo on-the-fly de /return-periods (mismo SQL, mismos umbrales, mismas
funciones puras `stationarity_report` + `reliability_report`), guardando el
resultado en `estacion_fiabilidad`. Así la LISTA y el DETALLE coinciden y la
lista no recalcula nada (solo lee).

Idempotente (UPSERT). Carga trivial: ~247 consultas al cagg diario.

Uso en el box:  /opt/ideam/venv/bin/python -m app.services.fiabilidad_batch
"""

import json

from .. import reliability, stationarity
from ..db import pool
from ..normalize import expand_station_codes

_PRECIP_DATASET = "s54a-sgyg"
_MAX_PRECIP_DIARIA_MM = 1800.0   # techo de plausibilidad física (idéntico a /return-periods)
_DIAS_MIN_ANIO = 300             # año "válido" si tiene >=300 días con dato

# Máximos diarios anuales (con días válidos), idéntico al de /return-periods.
_MAXIMA_SQL = (
    "SELECT extract(year FROM (dia AT TIME ZONE 'UTC'))::int AS anio, "
    "max(valor_sum) FILTER (WHERE n_validos > 0 AND valor_sum >= 0 "
    "AND valor_sum <= %(max_precip)s) AS maximo, "
    "count(*) FILTER (WHERE n_validos > 0) AS dias_validos "
    "FROM obs_diario "
    "WHERE source_dataset_id = %(dataset)s AND codigoestacion = ANY(%(codes)s) "
    "GROUP BY 1 ORDER BY 1"
)

_UPSERT = (
    "INSERT INTO estacion_fiabilidad "
    "(codigoestacion, level, n, completeness, stationary, reasons, computed_at) "
    "VALUES (%(codigo)s, %(level)s, %(n)s, %(completeness)s, %(stationary)s, %(reasons)s::jsonb, now()) "
    "ON CONFLICT (codigoestacion) DO UPDATE SET "
    "level = EXCLUDED.level, n = EXCLUDED.n, completeness = EXCLUDED.completeness, "
    "stationary = EXCLUDED.stationary, reasons = EXCLUDED.reasons, computed_at = now()"
)


def _valid_years(conn, codigo):
    rows = conn.execute(
        _MAXIMA_SQL,
        {
            "max_precip": _MAX_PRECIP_DIARIA_MM,
            "dataset": _PRECIP_DATASET,
            "codes": expand_station_codes([codigo]),
        },
    ).fetchall()
    return [
        {"year": r[0], "maximum": round(float(r[1]), 1), "days": r[2]}
        for r in rows
        if r[1] is not None and r[1] >= 0 and r[2] >= _DIAS_MIN_ANIO
    ]


def compute_report(conn, codigo):
    """Calcula el informe de fiabilidad de una estación (mismo resultado que el
    semáforo del detalle). Devuelve el dict de reliability_report."""
    vy = _valid_years(conn, codigo)
    maxima = [y["maximum"] for y in vy]
    strep = stationarity.stationarity_report(maxima)
    return reliability.reliability_report(vy, strep)


def run(min_anios=0):
    """Recalcula la fiabilidad de todas las estaciones de idf_estado."""
    pool.open()
    with pool.connection() as conn:
        codes = [
            r[0]
            for r in conn.execute(
                "SELECT codigoestacion FROM idf_estado WHERE anios_validos >= %s "
                "ORDER BY codigoestacion",
                (min_anios,),
            ).fetchall()
        ]
    print(f"[fiabilidad] {len(codes)} estaciones a procesar")
    procesadas = 0
    for i, codigo in enumerate(codes, 1):
        with pool.connection() as conn:
            rep = compute_report(conn, codigo)
            conn.execute(
                _UPSERT,
                {
                    "codigo": codigo,
                    "level": rep["level"],
                    "n": rep["n"],
                    "completeness": rep["completeness"],
                    "stationary": rep["stationary"],
                    "reasons": json.dumps(rep["reasons"], ensure_ascii=False),
                },
            )
        procesadas += 1
        if i % 25 == 0 or i == len(codes):
            print(f"[fiabilidad] {i}/{len(codes)}")
    print(f"[fiabilidad] listo: {procesadas} estaciones actualizadas")
    return procesadas


if __name__ == "__main__":
    run()
