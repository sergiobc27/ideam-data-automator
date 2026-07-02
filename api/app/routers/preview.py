import time
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request

from ..db import pool, read_with_retry
from ..http_utils import client_ip as _client_ip
from ..models import QueryPayload
from ..normalize import build_filters
from ..ratelimit import check_rate_limit
from ..settings import settings

router = APIRouter()


def _lectura_rate(request: Request):
    ok, _remaining, retry = check_rate_limit(
        "lectura", _client_ip(request), settings.rate_limit_catalog_per_hour
    )
    if not ok:
        raise HTTPException(
            429,
            f"Limite de consultas alcanzado. Intenta de nuevo en {max(retry // 60, 1)} minuto(s).",
        )

ROW_COLUMNS = [
    "source_dataset_id", "codigoestacion", "codigosensor", "fechaobservacion",
    "valorobservado", "nombreestacion", "departamento", "municipio",
    "zonahidrografica", "latitud", "longitud", "descripcionsensor", "unidadmedida",
]


def _serialize(row):
    record = dict(zip(ROW_COLUMNS, row))
    fecha = record.get("fechaobservacion")
    if fecha is not None:
        record["fechaobservacion"] = fecha.strftime("%Y-%m-%dT%H:%M:%S")
    return record


def _preview_techo_clause(end, params):
    """Cláusula y param del techo de fecha para acotar el ORDER BY ... DESC del
    preview (Fix #3).

    En datasets que terminaron en el pasado (p.ej. mar, hasta 2020) el
    ChunkAppend arranca en "hoy" y recorre años de chunks vacíos hacia atrás
    antes de juntar las filas del LIMIT → timeout. Acotar con el techo real del
    dataset (max de obs_diario) hace que el scan empiece en el chunk correcto.

    Se OMITE el techo solo cuando ya hay una cota superior:
      - el usuario dio endDate → build_filters puso 'end' en params (su rango
        acota), o
      - no hay datos (end is None) → no hay nada que acotar.
    El caso COMÚN (hay filas pero el usuario no acotó endDate) SÍ recibe el techo.

    Devuelve (techo_sql | "", extra_params_dict)."""
    if end is not None and "end" not in params:
        return " AND fechaobservacion < %(preview_techo)s", {"preview_techo": end + timedelta(days=1)}
    return "", {}


def _resumen_desde_agregado(conn, payload, dataset):
    """Resumen vía obs_diario (agregado continuo): sub-segundo donde el conteo
    directo sobre la hypertable (764M filas) tomaba minutos descomprimiendo.

    obs_diario tiene dataset/estación/departamento/municipio/día. Los filtros
    que viven solo en la fila cruda (zona hidrográfica, nombre de estación) se
    traducen a códigos de estación vía el catálogo `estaciones`.
    """
    from ..normalize import department_variants, expand_station_codes

    filters = payload.catalogFilters or {}
    clauses = ["source_dataset_id = %(dataset_id)s"]
    params = {"dataset_id": dataset["id"]}

    dep_variants = set()
    for canonical in payload.departments or []:
        dep_variants.update(department_variants(str(canonical).upper()))
    if dep_variants:
        clauses.append("upper(departamento) = ANY(%(departments)s)")
        params["departments"] = sorted(dep_variants)
    if filters.get("municipalities"):
        clauses.append("upper(municipio) = ANY(%(municipios)s)")
        params["municipios"] = [str(m).upper() for m in filters["municipalities"]]

    codigos = set()
    if filters.get("stations"):
        codigos.update(expand_station_codes(filters["stations"]))
    if filters.get("hydrologicZones"):
        rows = conn.execute(
            "SELECT codigoestacion FROM estaciones WHERE upper(zona_hidrografica) = ANY(%(z)s)",
            {"z": [str(z).upper() for z in filters["hydrologicZones"]]},
        ).fetchall()
        codigos.update(r[0] for r in rows)
    if filters.get("stationNames"):
        rows = conn.execute(
            "SELECT codigoestacion FROM estaciones WHERE upper(nombre) = ANY(%(n)s)",
            {"n": [str(n).upper() for n in filters["stationNames"]]},
        ).fetchall()
        codigos.update(r[0] for r in rows)
    if codigos:
        clauses.append("codigoestacion = ANY(%(estaciones)s)")
        params["estaciones"] = sorted(codigos)

    # Rango medio-abierto alineado a UTC: las cubetas de obs_diario están a
    # medianoche UTC (time_bucket sobre timestamptz). Comparar contra fechas
    # locales -05 desalineaba y una ventana de 1 día devolvía 0 (off-by-one).
    # [start 00:00 UTC, (end+1) 00:00 UTC) incluye la cubeta del día final.
    if payload.startDate:
        clauses.append("dia >= %(start)s")
        params["start"] = f"{payload.startDate}T00:00:00+00:00"
    if payload.endDate:
        end_excl = date.fromisoformat(str(payload.endDate)) + timedelta(days=1)
        clauses.append("dia < %(end)s")
        params["end"] = f"{end_excl.isoformat()}T00:00:00+00:00"

    where = " AND ".join(clauses)
    # Zonas en la MISMA pasada via subconsulta (auditoria 2026-07-01): antes,
    # array_agg(DISTINCT codigoestacion) materializaba todos los codigos en
    # Postgres y en Python solo para reenviarlos a una segunda query cuyo unico
    # proposito era count(DISTINCT zona_hidrografica). Ahora el conteo de zonas
    # se resuelve en SQL, sin array intermedio ni segundo round-trip.
    fila = conn.execute(
        "SELECT coalesce(sum(n),0)::bigint, count(DISTINCT codigoestacion), "
        "       count(DISTINCT municipio), count(DISTINCT departamento), "
        "       min(dia), max(dia), "
        "       (SELECT count(DISTINCT e.zona_hidrografica) FROM estaciones e "
        "        WHERE e.zona_hidrografica IS NOT NULL AND e.codigoestacion IN "
        f"       (SELECT codigoestacion FROM obs_diario WHERE {where})) "
        f"FROM obs_diario WHERE {where}",
        params,
    ).fetchone()
    row_count, stations, municipalities, departments, start, end, zones = fila
    return row_count, stations, municipalities, departments, zones or 0, start, end


@router.post("/api/preview")
def preview(payload: QueryPayload, request: Request):
    _lectura_rate(request)
    t0 = time.time()
    where, params, dataset, _canonicals = build_filters(payload)
    cols = ", ".join(ROW_COLUMNS)

    def _consulta():
        with pool.connection() as conn:
            (row_count, stations, municipalities, departments, zones,
             start, end) = _resumen_desde_agregado(conn, payload, dataset)
            # Acotar el ORDER BY ... DESC con el techo real del dataset (max de
            # obs_diario): sin esto, en datasets que terminaron en el pasado (mar,
            # hasta 2020) el ChunkAppend arrancaba en 2026 y recorría ~6 años de
            # chunks vacíos antes de juntar 200 filas -> timeout. Con el techo,
            # el scan empieza en el chunk correcto. Lógica en _preview_techo_clause.
            techo, techo_params = _preview_techo_clause(end, params)
            row_params = dict(params, limit=settings.preview_limit, **techo_params)
            rows = []
            if row_count:
                rows = conn.execute(
                    f"SELECT {cols} FROM observaciones WHERE {where}{techo} "
                    "ORDER BY fechaobservacion DESC LIMIT %(limit)s",
                    row_params,
                ).fetchall()
            return row_count, stations, municipalities, departments, zones, start, end, rows

    (row_count, stations, municipalities, departments, zones,
     start, end, rows) = read_with_retry(_consulta)
    station_filters = (payload.catalogFilters or {}).get("stations") or []

    return {
        "datasetId": dataset["id"],
        "rowCount": row_count,
        "rows": [_serialize(r) for r in rows],
        "summary": {
            "rowCount": row_count,
            "stationCount": stations,
            "municipalityCount": municipalities,
            "departmentCount": departments,
            "zoneCount": zones,
            "observedStart": start.strftime("%Y-%m-%dT%H:%M:%S") if start else None,
            "observedEnd": end.strftime("%Y-%m-%dT%H:%M:%S") if end else None,
        },
        "stationPoolSize": len(station_filters),
        "queryPlans": 1,
        "processingMs": int((time.time() - t0) * 1000),
    }
