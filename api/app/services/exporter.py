"""Generación de exports: CSV/JSON/Parquet por (departamento, municipio) y ZIP final.

Reglas de producto (website/AGENTS.md):
- ZIP: variable_DDMMYYYY.zip
- Jerarquía interna: variable/departamento/municipio/formato/archivo
- Archivo: variable_departamento_municipio_HHMM_DDMMYY.fmt
- Formatos csv/json/parquet; si Parquet falla, fallback a CSV.
- Si no hay filas: ZIP con evidencia "sin_datos".

Los datos se streamean desde Postgres con cursor de servidor (RAM acotada).
"""

import csv
import json
import logging
import shutil
import time
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from ..db import pool
from ..models import QueryPayload
from ..normalize import build_filters
from ..settings import settings

logger = logging.getLogger(__name__)

EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="export-job")

ROW_COLUMNS = [
    "source_dataset_id", "codigoestacion", "codigosensor", "fechaobservacion",
    "valorobservado", "nombreestacion", "departamento", "municipio",
    "zonahidrografica", "latitud", "longitud", "descripcionsensor", "unidadmedida",
]

_FLOAT_COLUMNS = {"valorobservado", "latitud", "longitud"}

PARQUET_SCHEMA = pa.schema(
    [
        pa.field(col, pa.float64() if col in _FLOAT_COLUMNS else pa.string())
        for col in ROW_COLUMNS
    ]
)

BATCH_SIZE = 50_000
VALID_FORMATS = ("csv", "json", "parquet")


class ExportTooLargeError(Exception):
    """El ZIP superó EXPORT_MAX_BYTES durante la escritura: se aborta el job."""


def _zip_bytes_written(zf, fallback_path):
    """Bytes escritos hasta ahora en el ZIP (candado de tamaño en disco)."""
    fp = getattr(zf, "fp", None)
    if fp is not None:
        try:
            return fp.tell()
        except (OSError, ValueError):
            pass
    try:
        return fallback_path.stat().st_size
    except OSError:
        return 0


def slug(value):
    text = "" if value is None else str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    out = "".join(ch if ch.isalnum() else "_" for ch in text)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_") or "na"


def file_stem(dataset_name, canonicals, when):
    deps = "_".join(slug(c) for c in canonicals[:2]) + ("_varios" if len(canonicals) > 2 else "")
    return f"{slug(dataset_name)}_{deps}_{when.strftime('%H%M_%d%m%y')}"


def zip_file_name(dataset_name, when):
    return f"{slug(dataset_name)}_{when.strftime('%d%m%Y')}.zip"


def _update(job_id, **fields):
    sets = ", ".join(f"{k} = %({k})s" for k in fields)
    with pool.connection() as conn:
        conn.execute(
            f"UPDATE export_jobs SET {sets}, updated_at = now() WHERE job_id = %(job_id)s",
            {**fields, "job_id": job_id},
        )


def _fecha_str(value):
    return value.strftime("%Y-%m-%dT%H:%M:%S") if value is not None else None


def _serialize(row):
    record = dict(zip(ROW_COLUMNS, row))
    record["fechaobservacion"] = _fecha_str(record["fechaobservacion"])
    return record


class _GroupWriters:
    """Escritores incrementales (csv/json/parquet) para un grupo depto-municipio."""

    def __init__(self, base_dir, variable, dep, mun, when, formats):
        self.formats = list(formats)
        self.rows = 0
        name = f"{slug(variable)}_{slug(dep)}_{slug(mun)}_{when.strftime('%H%M_%d%m%y')}"
        root = Path(base_dir) / slug(variable) / slug(dep) / slug(mun)
        self.paths = {}
        self._csv_file = self._json_file = self._pq_writer = None
        self._json_first = True

        if "csv" in self.formats:
            path = root / "csv" / f"{name}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            self._csv_file = open(path, "w", newline="", encoding="utf-8")
            self._csv = csv.writer(self._csv_file)
            self._csv.writerow(ROW_COLUMNS)
            self.paths["csv"] = path
        if "json" in self.formats:
            path = root / "json" / f"{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            self._json_file = open(path, "w", encoding="utf-8")
            self._json_file.write("[")
            self.paths["json"] = path
        if "parquet" in self.formats:
            path = root / "parquet" / f"{name}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._pq_writer = pq.ParquetWriter(path, PARQUET_SCHEMA)
                self.paths["parquet"] = path
            except Exception:  # noqa: BLE001 - fallback de producto: parquet -> csv
                logger.exception("ParquetWriter fallo; se omite parquet para %s", name)
                self._pq_writer = None

    def write_batch(self, batch):
        self.rows += len(batch)
        records = [_serialize(row) for row in batch]
        if self._csv_file:
            for row in batch:
                self._csv.writerow([_fecha_str(v) if i == 3 else v for i, v in enumerate(row)])
        if self._json_file:
            for record in records:
                if not self._json_first:
                    self._json_file.write(",\n")
                self._json_file.write(json.dumps(record, ensure_ascii=False, default=str))
                self._json_first = False
        if self._pq_writer:
            arrays = []
            for col in ROW_COLUMNS:
                values = [r[col] for r in records]
                if col in _FLOAT_COLUMNS:
                    arrays.append(pa.array(values, type=pa.float64()))
                else:
                    arrays.append(pa.array([None if v is None else str(v) for v in values], type=pa.string()))
            self._pq_writer.write_table(pa.Table.from_arrays(arrays, schema=PARQUET_SCHEMA))

    def close(self):
        if self._csv_file:
            self._csv_file.close()
        if self._json_file:
            self._json_file.write("]\n")
            self._json_file.close()
        if self._pq_writer:
            self._pq_writer.close()


def submit_job(job_id):
    EXECUTOR.submit(_run_job_safe, str(job_id))


def _run_job_safe(job_id):
    try:
        _run_job(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Export job %s fallo", job_id)
        _update(job_id, status="failed", error=str(exc)[:500], finished_at=datetime.now(timezone.utc),
                current_stage="Fallido")


def _run_job(job_id):
    t0 = time.time()
    with pool.connection() as conn:
        job = conn.execute(
            "SELECT payload, effective_formats, dataset_name FROM export_jobs WHERE job_id = %s",
            (job_id,),
        ).fetchone()
    payload_raw, formats, dataset_name = job
    payload = QueryPayload(**payload_raw)
    where, params, dataset, canonicals = build_filters(payload)

    now = datetime.now(timezone.utc)
    stem = file_stem(dataset_name, canonicals, now)
    _update(job_id, status="planning", started_at=now, current_stage="Planificando", file_stem=stem)

    with pool.connection() as conn:
        row_count = conn.execute(
            f"SELECT count(*) FROM observaciones WHERE {where}", params
        ).fetchone()[0]
        groups = conn.execute(
            f"SELECT departamento, municipio FROM observaciones WHERE {where} "
            "GROUP BY 1, 2 ORDER BY 1, 2",
            params,
        ).fetchall()

    page_size = settings.export_page_size
    total_pages = max((row_count + page_size - 1) // page_size, 1)
    _update(job_id, status="processing", row_count=row_count, total_pages=total_pages,
            current_stage="Descargando datos")

    exports_dir = Path(settings.exports_dir)
    workdir = exports_dir / f"job-{job_id}"
    zip_path = exports_dir / f"{job_id}.zip"
    workdir.mkdir(parents=True, exist_ok=True)

    cols = ", ".join(ROW_COLUMNS)
    processed = 0
    stations, municipios, zonas = set(), set(), set()
    observed_start = observed_end = None

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if row_count == 0:
                evidencia = workdir / slug(dataset_name) / "sin_datos" / f"{slug(dataset_name)}_sin_datos.csv"
                evidencia.parent.mkdir(parents=True, exist_ok=True)
                evidencia.write_text(
                    "mensaje\nLa consulta no produjo filas. Ajusta los filtros e intenta de nuevo.\n",
                    encoding="utf-8",
                )
                zf.write(evidencia, evidencia.relative_to(workdir).as_posix())
            else:
                for dep, mun in groups:
                    writers = _GroupWriters(workdir, dataset_name, dep, mun, now, formats)
                    with pool.connection() as conn:
                        conn.row_factory = tuple_row
                        with conn.cursor(name=f"exp_{job_id[:8]}") as cur:
                            cur.itersize = BATCH_SIZE
                            cur.execute(
                                f"SELECT {cols} FROM observaciones WHERE {where} "
                                "AND departamento IS NOT DISTINCT FROM %(g_dep)s "
                                "AND municipio IS NOT DISTINCT FROM %(g_mun)s "
                                "ORDER BY fechaobservacion",
                                {**params, "g_dep": dep, "g_mun": mun},
                            )
                            while True:
                                batch = cur.fetchmany(BATCH_SIZE)
                                if not batch:
                                    break
                                writers.write_batch(batch)
                                processed += len(batch)
                                for row in batch:
                                    stations.add(row[1])
                                    if row[8] is not None:
                                        zonas.add(row[8])
                                    fecha = row[3]
                                    if fecha is not None:
                                        observed_start = fecha if observed_start is None else min(observed_start, fecha)
                                        observed_end = fecha if observed_end is None else max(observed_end, fecha)
                                _update(
                                    job_id,
                                    processed_rows=processed,
                                    completed_pages=min(processed // page_size, total_pages),
                                    current_stage=f"Procesando {dep or 'N/D'} / {mun or 'N/D'}",
                                )
                    writers.close()
                    if mun is not None:
                        municipios.add(mun)
                    for _fmt, path in writers.paths.items():
                        zf.write(path, path.relative_to(workdir).as_posix())
                        path.unlink()
                    # Candado anti-DoS/costo: corta si el ZIP excede el tope.
                    written = _zip_bytes_written(zf, zip_path)
                    if written > settings.export_max_bytes:
                        raise ExportTooLargeError(
                            f"La exportacion supero el limite de "
                            f"{settings.export_max_bytes:,} bytes. Acota los filtros e "
                            "intenta de nuevo.".replace(",", ".")
                        )
    except ExportTooLargeError:
        # ZIP parcial inservible: bórralo para no dejar basura en disco.
        zip_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    finished = datetime.now(timezone.utc)
    expires = finished + timedelta(seconds=settings.export_ttl_seconds)
    size = zip_path.stat().st_size
    zip_name = zip_file_name(dataset_name, finished)
    parts = [
        {
            "index": 0,
            "fileName": zip_name,
            "rowCount": processed,
            "sizeBytes": size,
            "formats": list(formats),
            "downloadPath": f"/api/jobs/{job_id}/parts/0",
            "expiresAt": expires.isoformat(),
        }
    ]
    metrics = {
        "fileName": zip_name,
        "rowCount": processed,
        "noData": row_count == 0,
        "stationCount": len(stations),
        "municipalityCount": len(municipios),
        "departmentCount": len(canonicals),
        "zoneCount": len(zonas),
        "processingMs": int((time.time() - t0) * 1000),
        "sizeBytes": size,
        "observedStart": _fecha_str(observed_start) or "",
        "observedEnd": _fecha_str(observed_end) or "",
        "queryPlans": 1,
        "stationPoolSize": len((payload.catalogFilters or {}).get("stations") or []),
        "archivePartCount": 1,
        "downloadedPages": total_pages,
    }
    _update(
        job_id,
        status="completed",
        finished_at=finished,
        completed_pages=total_pages,
        processed_rows=processed,
        current_stage="Completado",
        parts=Jsonb(parts),
        metrics=Jsonb(metrics),
    )
    logger.info("Export %s completado: %s filas, %s bytes", job_id, processed, size)
