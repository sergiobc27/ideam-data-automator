import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from psycopg.types.json import Jsonb

from ..db import pool
from ..models import CreateJobPayload, ExportPagePayload, QueryPayload
from ..normalize import build_filters, normalize_label
from ..db import check_rate_limit as check_rate_limit_pg
from ..services import exporter
from ..caggs import cagg_filters as _cagg_filters, can_use_cagg as _can_use_cagg
from ..settings import settings

router = APIRouter()


def _client_ip(request: Request):
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def _export_rate(request: Request):
    # Contador en Postgres (atómico, compartido entre los 2 workers de uvicorn
    # y sobrevive reinicios): en memoria el tope real era x2 y volátil
    # (hallazgo de auditoría). Las lecturas siguen en memoria (frecuencia alta,
    # costo de un 429 de menos = nulo).
    ok, _remaining, retry = check_rate_limit_pg(
        "export", _client_ip(request), settings.rate_limit_export_per_hour
    )
    if not ok:
        raise HTTPException(
            429,
            f"Limite de exportaciones alcanzado. Intenta de nuevo en {max(retry // 60, 1)} minuto(s).",
            headers={"Retry-After": str(max(retry, 60))},
        )


def _enforce_row_cap(row_count):
    """Candado anti-DoS/costo: rechaza exports gigantes ANTES de generar."""
    if row_count > settings.export_max_rows:
        raise HTTPException(
            413,
            f"La consulta selecciona {row_count:,} filas y supera el limite de "
            f"{settings.export_max_rows:,} filas por exportacion. Acota el rango de "
            "fechas, los departamentos o las estaciones e intenta de nuevo.".replace(",", "."),
        )


def _estimate_row_count(payload):
    """Filas estimadas para el candado anti-costo y la planificación.

    El count(*) directo sobre la hypertable cruda supera el statement_timeout
    de 30s con selecciones grandes (p.ej. un departamento de precipitación con
    todo el rango) y tumbaba /api/jobs con 500. Cuando los filtros lo permiten
    se suma obs_diario (instantáneo; puede variar ±1 día en los bordes, lo cual
    es irrelevante para el tope de 5M). Con filtros finos (zona, nombre de
    estación) cae a la cruda con un timeout más holgado SOLO en esa transacción.
    El conteo exacto definitivo lo recalcula el worker del job en background.
    """
    if _can_use_cagg(payload):
        where, params, _dataset = _cagg_filters(payload)
        with pool.connection() as conn:
            value = conn.execute(
                f"SELECT coalesce(sum(n), 0) FROM obs_diario WHERE {where}", params
            ).fetchone()[0]
        return int(value)
    where, params, _dataset, _canonicals = build_filters(payload)
    with pool.connection() as conn:
        # 85s: por debajo del techo (~100s) del Worker de Cloudflare, para que
        # el usuario reciba el error de la API y no un 524 opaco del proxy.
        conn.execute("SET LOCAL statement_timeout = '85s'")
        return conn.execute(
            f"SELECT count(*) FROM observaciones WHERE {where}", params
        ).fetchone()[0]


@router.post("/api/export-plan")
def export_plan(payload: QueryPayload, request: Request):
    _export_rate(request)
    t0 = time.time()
    _where, _params, dataset, canonicals = build_filters(payload)
    row_count = _estimate_row_count(payload)
    _enforce_row_cap(row_count)

    page_size = settings.export_page_size
    total_pages = max(math.ceil(row_count / page_size), 1) if row_count else 0
    now = datetime.now(timezone.utc)
    return {
        "datasetId": dataset["id"],
        "fileStem": exporter.file_stem(dataset["name"], canonicals, now),
        "rowCount": row_count,
        "pageSize": page_size,
        "totalPages": total_pages,
        "queryPlans": 1,
        "stationPoolSize": len((payload.catalogFilters or {}).get("stations") or []),
        "replacements": {normalize_label(c): c for c in canonicals},
        "planPages": [
            {"planIndex": 0, "where": None, "rowCount": row_count, "pageCount": total_pages}
        ],
        "processingMs": int((time.time() - t0) * 1000),
    }


@router.post("/api/export-page")
def export_page(payload: ExportPagePayload, request: Request):
    # Mismas guardias que el resto del flujo de export: sin esto era una
    # puerta lateral sin rate limit ni candado de filas (hallazgo de auditoría).
    _export_rate(request)
    if payload.offset >= settings.export_max_rows:
        raise HTTPException(
            413,
            f"El offset supera el limite de {settings.export_max_rows:,} filas "
            "por exportacion.".replace(",", "."),
        )
    # El `where` del cliente se ignora: los filtros se reconstruyen server-side.
    base = QueryPayload(
        datasetId=payload.datasetId,
        departments=payload.departments,
        catalogFilters=payload.catalogFilters,
        startDate=payload.startDate,
        endDate=payload.endDate,
    )
    where, params, dataset, _canonicals = build_filters(base)
    limit = min(max(payload.limit, 1), settings.export_page_size)
    cols = ", ".join(exporter.ROW_COLUMNS)
    with pool.connection() as conn:
        # OFFSET profundo es costoso en la cruda; timeout holgado solo aquí,
        # por debajo del techo (~100s) del Worker de Cloudflare.
        conn.execute("SET LOCAL statement_timeout = '85s'")
        rows = conn.execute(
            f"SELECT {cols} FROM observaciones WHERE {where} "
            "ORDER BY fechaobservacion DESC OFFSET %(offset)s LIMIT %(page_limit)s",
            {**params, "offset": max(payload.offset, 0), "page_limit": limit},
        ).fetchall()
    return {
        "datasetId": dataset["id"],
        "planIndex": payload.planIndex,
        "offset": payload.offset,
        "returnedRows": len(rows),
        "rows": [exporter._serialize(r) for r in rows],
    }


@router.post("/api/export")
def export_legacy():
    raise HTTPException(
        410,
        "La exportacion sincronica fue deshabilitada. Usa /api/jobs para exportaciones "
        "comprimidas y asincronas.",
    )


def _job_response(row):
    (job_id, status, created, started, finished, updated, dataset_id, dataset_name,
     selected, effective, file_stem, row_count, total_pages, completed_pages,
     processed_rows, current_stage, retry_count, error, warnings, parts, metrics) = row

    now = datetime.now(timezone.utc)
    elapsed = ((finished or now) - (started or created)).total_seconds()
    progress = (completed_pages / total_pages * 100) if total_pages else (100 if status == "completed" else 0)
    rows_per_second = processed_rows / elapsed if elapsed > 0 else 0
    remaining = None
    if status == "processing" and rows_per_second > 0 and row_count > processed_rows:
        remaining = round((row_count - processed_rows) / rows_per_second)

    return {
        "jobId": str(job_id),
        "status": status,
        "createdAt": created.isoformat(),
        "startedAt": started.isoformat() if started else None,
        "finishedAt": finished.isoformat() if finished else None,
        "updatedAt": updated.isoformat(),
        "datasetId": dataset_id,
        "datasetName": dataset_name,
        "fileStem": file_stem,
        "warnings": warnings or [],
        "error": error,
        "retryCount": retry_count,
        "retryLimit": 3,
        "lastErrorAt": None,
        "selectedFormats": selected or [],
        "effectiveFormats": effective or [],
        "rowCount": row_count,
        "totalPages": total_pages,
        "completedPages": completed_pages,
        "processedRows": processed_rows,
        "currentPage": completed_pages,
        "pageSize": settings.export_page_size,
        "currentStage": current_stage,
        "progressPercent": round(min(progress, 100), 1),
        "elapsedSeconds": round(elapsed),
        "rowsPerSecond": round(rows_per_second),
        "estimatedRemainingSeconds": remaining,
        "queryPlans": 1,
        "stationPoolSize": 0,
        "parts": parts or [],
        "metrics": metrics,
    }


_JOB_SELECT = (
    "SELECT job_id, status, created_at, started_at, finished_at, updated_at, dataset_id, "
    "dataset_name, selected_formats, effective_formats, file_stem, row_count, total_pages, "
    "completed_pages, processed_rows, current_stage, retry_count, error, warnings, parts, metrics "
    "FROM export_jobs WHERE job_id = %s"
)


@router.post("/api/jobs", status_code=202)
def create_job(payload: CreateJobPayload, request: Request):
    _export_rate(request)

    # Tope GLOBAL de exportaciones simultáneas: la cola del executor es
    # ilimitada y cada job retiene conexión/CPU/disco; sin esto, N IPs
    # podían encolar trabajo sin límite (hallazgo de auditoría).
    with pool.connection() as conn:
        active = conn.execute(
            "SELECT count(*) FROM export_jobs WHERE status IN ('queued', 'planning', 'processing')"
        ).fetchone()[0]
    if active >= settings.export_max_active_jobs:
        raise HTTPException(
            429,
            "El servidor esta procesando el maximo de exportaciones simultaneas. "
            "Intenta de nuevo en unos minutos.",
        )

    _where, _params, dataset, _canonicals = build_filters(payload)
    # Candado anti-DoS/costo: estima filas y rechaza ANTES de encolar el job.
    row_count = _estimate_row_count(payload)
    _enforce_row_cap(row_count)

    selected = [f for f in (payload.formats or []) if f in exporter.VALID_FORMATS]
    effective = selected or ["csv"]

    job_id = uuid.uuid4()
    with pool.connection() as conn:
        conn.execute(
            "INSERT INTO export_jobs (job_id, dataset_id, dataset_name, payload, "
            "selected_formats, effective_formats) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                job_id,
                dataset["id"],
                dataset["name"],
                Jsonb(payload.model_dump(exclude={"formats", "exportPlan"})),
                selected,
                effective,
            ),
        )
    exporter.submit_job(job_id)

    with pool.connection() as conn:
        row = conn.execute(_JOB_SELECT, (job_id,)).fetchone()
    return _job_response(row)


@router.get("/api/jobs/{job_id}")
def job_status(job_id: uuid.UUID):
    with pool.connection() as conn:
        row = conn.execute(_JOB_SELECT, (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job no encontrado.")
    return _job_response(row)


@router.get("/api/jobs/{job_id}/manifest")
def job_manifest(job_id: uuid.UUID):
    return job_status(job_id)


@router.get("/api/jobs/{job_id}/parts/{part_index}")
def job_part(job_id: uuid.UUID, part_index: int):
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT parts, dataset_name, status FROM export_jobs WHERE job_id = %s", (job_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Job no encontrado.")
    parts, dataset_name, status = row
    if status != "completed" or not parts or part_index >= len(parts):
        raise HTTPException(404, "El archivo no esta disponible.")

    zip_path = Path(settings.exports_dir) / f"{job_id}.zip"
    if not zip_path.exists():
        raise HTTPException(410, "El archivo expiro. Genera una nueva exportacion.")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=parts[part_index]["fileName"],
        headers={"cache-control": "no-store", "x-robots-tag": "noindex"},
    )


@router.delete("/api/jobs/{job_id}/parts/{part_index}")
def job_part_delete(job_id: uuid.UUID, part_index: int):
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT parts FROM export_jobs WHERE job_id = %s", (job_id,)
        ).fetchone()
    expires = None
    if row and row[0] and part_index < len(row[0]):
        expires = row[0][part_index].get("expiresAt")
    return {
        "ok": True,
        "deleted": False,
        "partIndex": part_index,
        "expiresAt": expires,
        "message": "El archivo permanece disponible hasta que expire la ventana temporal.",
    }
