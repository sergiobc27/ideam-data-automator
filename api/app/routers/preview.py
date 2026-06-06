import time

from fastapi import APIRouter, HTTPException, Request

from ..db import pool
from ..models import QueryPayload
from ..normalize import build_filters
from ..ratelimit import check_rate_limit
from ..settings import settings

router = APIRouter()


def _client_ip(request: Request):
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


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

    if payload.startDate:
        clauses.append("dia >= %(start)s")
        params["start"] = f"{payload.startDate}"
    if payload.endDate:
        clauses.append("dia <= %(end)s")
        params["end"] = f"{payload.endDate}"

    where = " AND ".join(clauses)
    fila = conn.execute(
        "SELECT coalesce(sum(n),0)::bigint, count(DISTINCT codigoestacion), "
        "       count(DISTINCT municipio), count(DISTINCT departamento), "
        "       min(dia), max(dia), array_agg(DISTINCT codigoestacion) "
        f"FROM obs_diario WHERE {where}",
        params,
    ).fetchone()
    row_count, stations, municipalities, departments, start, end, codigos_res = fila
    zones = 0
    if codigos_res:
        zones = conn.execute(
            "SELECT count(DISTINCT zona_hidrografica) FROM estaciones "
            "WHERE codigoestacion = ANY(%(c)s) AND zona_hidrografica IS NOT NULL",
            {"c": codigos_res},
        ).fetchone()[0]
    return row_count, stations, municipalities, departments, zones, start, end


@router.post("/api/preview")
def preview(payload: QueryPayload, request: Request):
    _lectura_rate(request)
    t0 = time.time()
    where, params, dataset, _canonicals = build_filters(payload)
    cols = ", ".join(ROW_COLUMNS)

    with pool.connection() as conn:
        (row_count, stations, municipalities, departments, zones,
         start, end) = _resumen_desde_agregado(conn, payload, dataset)
        rows = conn.execute(
            f"SELECT {cols} FROM observaciones WHERE {where} "
            "ORDER BY fechaobservacion DESC LIMIT %(limit)s",
            {**params, "limit": settings.preview_limit},
        ).fetchall()
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
