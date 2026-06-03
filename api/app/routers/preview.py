import time

from fastapi import APIRouter

from ..db import pool
from ..models import QueryPayload
from ..normalize import build_filters
from ..settings import settings

router = APIRouter()

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


@router.post("/api/preview")
def preview(payload: QueryPayload):
    t0 = time.time()
    where, params, dataset, _canonicals = build_filters(payload)
    cols = ", ".join(ROW_COLUMNS)

    with pool.connection() as conn:
        summary_row = conn.execute(
            "SELECT count(*), count(DISTINCT codigoestacion), count(DISTINCT municipio), "
            "       count(DISTINCT departamento), count(DISTINCT zonahidrografica), "
            "       min(fechaobservacion), max(fechaobservacion) "
            f"FROM observaciones WHERE {where}",
            params,
        ).fetchone()
        rows = conn.execute(
            f"SELECT {cols} FROM observaciones WHERE {where} "
            "ORDER BY fechaobservacion DESC LIMIT %(limit)s",
            {**params, "limit": settings.preview_limit},
        ).fetchall()

    (row_count, stations, municipalities, departments, zones, start, end) = summary_row
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
