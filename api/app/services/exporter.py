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
import threading
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

from ..caggs import cagg_filters, can_use_cagg
from ..db import pool
from ..models import QueryPayload
from ..normalize import (
    build_filters,
    department_variants,
    expand_station_codes,
    get_dataset,
    validate_required_departments,
)
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

# Vía rápida CSV: PostgreSQL genera el CSV (COPY) y Python solo canaliza bytes
# al ZIP. Benchmark 2026-06-07 (Barranquilla, 484K filas): el escaneo+CSV en PG
# toma ~2-6s; el cuello real eran los ~5K filas/s del bucle Python fila a fila.
# La fecha se formatea en SQL para producir EXACTAMENTE el mismo texto que
# _fecha_str() (ISO sin zona, en hora de la sesión America/Bogota).
_COPY_COLUMNS = ", ".join(
    "to_char(fechaobservacion, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS fechaobservacion"
    if col == "fechaobservacion" else col
    for col in ROW_COLUMNS
)


def _copy_select_for(where):
    """SELECT del COPY de la vía rápida. El ORDER BY estación+fecha coincide
    con el layout físico de la compresión (segmentby estación, orderby fecha):
    PostgreSQL streamea sin sort externo."""
    return (
        f"SELECT {_COPY_COLUMNS} FROM observaciones WHERE {where} "
        "ORDER BY codigoestacion, fechaobservacion"
    )


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


# --- Reconciliación de jobs huérfanos (hallazgo de auditoría) -----------------
# El EXECUTOR vive en memoria de UN proceso uvicorn: tras un deploy/crash, los
# jobs 'queued' jamás corren y los 'planning'/'processing' quedan colgados para
# siempre (spinner infinito en el front).

_RECONCILER_STARTED = threading.Event()
_RECONCILER_STOP = threading.Event()
_reconciler_thread = None
# Clave del advisory lock: solo UN proceso uvicorn ejecuta cada barrido/reencole
# (los 2 workers arrancan a la vez; sin esto encolaban 2N tareas redundantes).
_RECONCILE_LOCK_KEY = 0x1DEA0001

# planning/processing: 20 min de gracia (un job vivo refresca updated_at; el peor
# caso legítimo es el sort inicial, statement_timeout 900s). queued: 30 min (puede
# esperar slot legítimamente, pero con cap de 4 jobs y rate limit, un queued tan
# viejo es huérfano de un proceso muerto → spinner infinito si no se barre).
_STALE_SQL = (
    "UPDATE export_jobs SET status = 'failed', "
    "error = 'La exportacion se interrumpio por un reinicio del servidor. Genera una nueva.', "
    "finished_at = now(), updated_at = now(), current_stage = 'Fallido' "
    "WHERE (status IN ('planning', 'processing') AND updated_at < now() - interval '20 minutes') "
    "   OR (status = 'queued' AND updated_at < now() - interval '30 minutes')"
)


def reconcile_on_startup():
    """Reencola los jobs 'queued' de un proceso anterior, bajo advisory lock para
    que solo UN worker lo haga (el claim atómico de _run_job ya evita la doble
    ejecución; el lock evita además el doble submit y las queries redundantes)."""
    try:
        with pool.connection() as conn:
            got = conn.execute("SELECT pg_try_advisory_lock(%s)", (_RECONCILE_LOCK_KEY,)).fetchone()[0]
            if not got:
                return  # otro worker se encarga
            try:
                rows = conn.execute("SELECT job_id FROM export_jobs WHERE status = 'queued'").fetchall()
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s)", (_RECONCILE_LOCK_KEY,))
        for (job_id,) in rows:
            submit_job(job_id)
        if rows:
            logger.info("Reencolados %s export jobs 'queued' tras reinicio", len(rows))
    except Exception:  # noqa: BLE001 - no impedir el arranque de la API
        logger.exception("No se pudieron reencolar jobs pendientes")


def start_reconciler():
    """Arranca el barrido periódico (1/min) de jobs huérfanos."""
    global _reconciler_thread
    if _RECONCILER_STARTED.is_set():
        return
    _RECONCILER_STARTED.set()
    _RECONCILER_STOP.clear()
    _reconciler_thread = threading.Thread(target=_reconcile_loop, name="export-reconciler", daemon=True)
    _reconciler_thread.start()


def stop_reconciler():
    """Para el barrido limpio antes de cerrar el pool (evita UPDATE a medias)."""
    _RECONCILER_STOP.set()
    if _reconciler_thread is not None:
        _reconciler_thread.join(timeout=5)
    _RECONCILER_STARTED.clear()


def _reconcile_loop():
    # Event.wait en vez de sleep: despierta de inmediato al apagar.
    while not _RECONCILER_STOP.wait(60):
        try:
            with pool.connection() as conn:
                # Advisory lock por barrido: serializa entre los 2 workers sin
                # un líder permanente. Si otro lo tiene, este ciclo se salta.
                got = conn.execute("SELECT pg_try_advisory_lock(%s)", (_RECONCILE_LOCK_KEY,)).fetchone()[0]
                if not got:
                    continue
                try:
                    conn.execute(_STALE_SQL)
                finally:
                    conn.execute("SELECT pg_advisory_unlock(%s)", (_RECONCILE_LOCK_KEY,))
        except Exception:  # noqa: BLE001
            logger.exception("Barrido de jobs huérfanos falló")


def _catalog_where(payload):
    """WHERE/params sobre mv_catalogo con TODOS los filtros del payload (la
    vista tiene depto/municipio/zona/estación/nombre y los códigos coinciden
    EXACTO con la cruda porque se deriva de observaciones)."""
    dataset = get_dataset(payload.datasetId)
    canonicals = validate_required_departments(payload.departments)
    variants = set()
    for canonical in canonicals:
        variants.update(department_variants(canonical))
    clauses = ["source_dataset_id = %(dataset_id)s", "upper(departamento) = ANY(%(deps)s)"]
    params = {"dataset_id": dataset["id"], "deps": sorted(variants)}
    filters = payload.catalogFilters or {}
    if filters.get("municipalities"):
        clauses.append("upper(municipio) = ANY(%(municipios)s)")
        params["municipios"] = [str(m).upper() for m in filters["municipalities"]]
    if filters.get("hydrologicZones"):
        clauses.append("upper(zonahidrografica) = ANY(%(zonas)s)")
        params["zonas"] = [str(z).upper() for z in filters["hydrologicZones"]]
    if filters.get("stations"):
        clauses.append("codigoestacion = ANY(%(estaciones)s)")
        params["estaciones"] = expand_station_codes(filters["stations"])
    if filters.get("stationNames"):
        clauses.append("upper(nombreestacion) = ANY(%(nombres)s)")
        params["nombres"] = [str(n).upper() for n in filters["stationNames"]]
    return " AND ".join(clauses), params


def _run_job_safe(job_id):
    try:
        _run_job(job_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Export job %s fallo", job_id)
        _update(job_id, status="failed", error=str(exc)[:500], finished_at=datetime.now(timezone.utc),
                current_stage="Fallido")


def _run_job(job_id):
    t0 = time.time()
    # Claim ATÓMICO: solo el worker que mueva queued->planning ejecuta el job
    # (evita doble corrida cuando ambos procesos uvicorn reencolan al arrancar).
    with pool.connection() as conn:
        job = conn.execute(
            "UPDATE export_jobs SET status = 'planning', started_at = now(), updated_at = now() "
            "WHERE job_id = %s AND status = 'queued' "
            "RETURNING payload, effective_formats, dataset_name",
            (job_id,),
        ).fetchone()
    if not job:
        return  # otro worker lo reclamó, o el job ya no está 'queued'
    payload_raw, formats, dataset_name = job
    payload = QueryPayload(**payload_raw)
    where, params, dataset, canonicals = build_filters(payload)

    now = datetime.now(timezone.utc)
    stem = file_stem(dataset_name, canonicals, now)
    _update(job_id, current_stage="Planificando", file_stem=stem)

    # Planificación instantánea (hallazgo de auditoría): antes, count(*) +
    # GROUP BY sobre la cruda = minutos de "Planificando" en selecciones
    # grandes. El conteo sale del cagg y los grupos de mv_catalogo.
    cat_where, cat_params = _catalog_where(payload)
    with pool.connection() as conn:
        if can_use_cagg(payload):
            cwhere, cparams, _d = cagg_filters(payload)
            row_count = int(conn.execute(
                f"SELECT coalesce(sum(n), 0) FROM obs_diario WHERE {cwhere}", cparams
            ).fetchone()[0])
        else:
            conn.execute("SET LOCAL statement_timeout = '900s'")
            row_count = conn.execute(
                f"SELECT count(*) FROM observaciones WHERE {where}", params
            ).fetchone()[0]

    # Reaplica el candado con el dato del planner: la estimación de /api/jobs
    # pudo subestimar (hallazgo de auditoría: candado burlable).
    if row_count > settings.export_max_rows:
        raise ExportTooLargeError(
            f"La consulta selecciona {row_count:,} filas y supera el limite de "
            f"{settings.export_max_rows:,} filas por exportacion. Acota los "
            "filtros e intenta de nuevo.".replace(",", ".")
        )

    with pool.connection() as conn:
        groups = conn.execute(
            f"SELECT departamento, municipio FROM mv_catalogo WHERE {cat_where} "
            "GROUP BY 1, 2 ORDER BY 1, 2",
            cat_params,
        ).fetchall()
        # Poda de segmentos (hallazgo TOP de auditoría): la compresión está
        # segmentada por (dataset, estación); filtrar por departamento solo
        # descomprimía el dataset ENTERO (282M filas en precipitación). La
        # lista de códigos del catálogo activa el segment pruning real.
        seg = conn.execute(
            f"SELECT DISTINCT codigoestacion FROM mv_catalogo WHERE {cat_where}",
            cat_params,
        ).fetchall()
    seg_codes = [r[0] for r in seg if r[0] is not None]
    if seg_codes:
        where = f"{where} AND codigoestacion = ANY(%(_seg_codes)s)"
        params = {**params, "_seg_codes": seg_codes}

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
    last_progress = 0.0
    stations, municipios, zonas = set(), set(), set()
    observed_start = observed_end = None
    # Métricas de la vía rápida (vienen de una query agregada, no del bucle).
    station_count = zone_count = None
    fast_csv = set(formats or ()) == {"csv"}

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
            elif fast_csv:
                # VÍA RÁPIDA (solo CSV): COPY de PostgreSQL directo al ZIP,
                # sin pasar fila a fila por Python (~6-8x más rápido).
                group_where = (
                    f"{where} AND departamento IS NOT DISTINCT FROM %(g_dep)s "
                    "AND municipio IS NOT DISTINCT FROM %(g_mun)s"
                )
                written_groups = []  # group_where realmente escritos -> conteo exacto al final
                for dep, mun in groups:
                    group_params = {**params, "g_dep": dep, "g_mun": mun}
                    name = f"{slug(dataset_name)}_{slug(dep)}_{slug(mun)}_{now.strftime('%H%M_%d%m%y')}"
                    rel = f"{slug(dataset_name)}/{slug(dep)}/{slug(mun)}/csv/{name}.csv"
                    with pool.connection() as conn:
                        conn.execute("SET LOCAL statement_timeout = '900s'")
                        # Los grupos salen del catálogo (sin fechas): saltar los
                        # que no tienen filas en el rango pedido.
                        has_rows = conn.execute(
                            f"SELECT 1 FROM observaciones WHERE {group_where} LIMIT 1",
                            group_params,
                        ).fetchone()
                        if not has_rows:
                            continue
                        written_groups.append(dict(group_params))
                        zinfo = zipfile.ZipInfo(rel, date_time=now.timetuple()[:6])
                        zinfo.compress_type = zipfile.ZIP_DEFLATED
                        with zf.open(zinfo, mode="w") as dest, conn.cursor() as cur:
                            with cur.copy(
                                f"COPY ({_copy_select_for(group_where)}) "
                                "TO STDOUT WITH (FORMAT csv, HEADER)",
                                group_params,
                            ) as copy:
                                for data in copy:
                                    chunk = bytes(data)
                                    dest.write(chunk)
                                    # Progreso APROXIMADO (newlines pueden venir
                                    # embebidos en campos citados); el conteo
                                    # EXACTO sale de la agg final. El candado real
                                    # es por bytes, monotónico e inmune a eso, y
                                    # se evalúa DENTRO del COPY (no solo entre
                                    # grupos) para frenar un grupo gigante a tiempo.
                                    processed += chunk.count(b"\n")
                                    if _zip_bytes_written(zf, zip_path) > settings.export_max_bytes:
                                        raise ExportTooLargeError(
                                            f"La exportacion supero el limite de "
                                            f"{settings.export_max_bytes:,} bytes. Acota los "
                                            "filtros e intenta de nuevo.".replace(",", ".")
                                        )
                                    if time.time() - last_progress >= 2:
                                        last_progress = time.time()
                                        _update(
                                            job_id,
                                            processed_rows=max(processed - len(written_groups), 0),
                                            completed_pages=min(processed // page_size, total_pages),
                                            current_stage=f"Procesando {dep or 'N/D'} / {mun or 'N/D'}",
                                        )
                    if mun is not None:
                        municipios.add(mun)
            else:
                for dep, mun in groups:
                    writers = _GroupWriters(workdir, dataset_name, dep, mun, now, formats)
                    with pool.connection() as conn:
                        conn.row_factory = tuple_row
                        # El ORDER BY del grupo puede tardar >30s en grupos
                        # grandes; tope holgado solo en esta transacción.
                        conn.execute("SET LOCAL statement_timeout = '900s'")
                        with conn.cursor(name=f"exp_{job_id[:8]}") as cur:
                            cur.itersize = BATCH_SIZE
                            cur.execute(
                                f"SELECT {cols} FROM observaciones WHERE {where} "
                                "AND departamento IS NOT DISTINCT FROM %(g_dep)s "
                                "AND municipio IS NOT DISTINCT FROM %(g_mun)s "
                                # estación+fecha coincide con el layout físico de la
                                # compresión: evita el sort externo en grupos grandes.
                                "ORDER BY codigoestacion, fechaobservacion",
                                {**params, "g_dep": dep, "g_mun": mun},
                            )
                            while True:
                                batch = cur.fetchmany(BATCH_SIZE)
                                if not batch:
                                    break
                                writers.write_batch(batch)
                                processed += len(batch)
                                # Candado exacto durante el stream: la estimación
                                # del planner puede quedarse corta en los bordes.
                                if processed > settings.export_max_rows:
                                    raise ExportTooLargeError(
                                        f"La exportacion supero el limite de "
                                        f"{settings.export_max_rows:,} filas. Acota los "
                                        "filtros e intenta de nuevo.".replace(",", ".")
                                    )
                                for row in batch:
                                    stations.add(row[1])
                                    if row[8] is not None:
                                        zonas.add(row[8])
                                    fecha = row[3]
                                    if fecha is not None:
                                        observed_start = fecha if observed_start is None else min(observed_start, fecha)
                                        observed_end = fecha if observed_end is None else max(observed_end, fecha)
                                # Throttle del progreso: antes era un UPDATE+commit
                                # por cada batch de 50k (churn de pool y WAL).
                                if time.time() - last_progress >= 2:
                                    last_progress = time.time()
                                    _update(
                                        job_id,
                                        processed_rows=processed,
                                        completed_pages=min(processed // page_size, total_pages),
                                        current_stage=f"Procesando {dep or 'N/D'} / {mun or 'N/D'}",
                                    )
                    writers.close()
                    if writers.rows == 0:
                        # Grupo del catálogo sin filas en el rango pedido (los
                        # grupos salen de mv_catalogo, que no conoce fechas):
                        # no ensuciar el ZIP con archivos vacíos.
                        for path in writers.paths.values():
                            path.unlink(missing_ok=True)
                        continue
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

    if fast_csv and written_groups:
        # Métricas EXACTAS de la vía rápida: una query agregada restringida a
        # los grupos REALMENTE escritos (auditoría #4: el where global contaba
        # filas que ningún grupo emitió, sobreestimando el rowCount citado).
        # La igualdad NULL-aware replica el group_where del COPY.
        agg_params = dict(params)
        group_clauses = []
        for i, gp in enumerate(written_groups):
            agg_params[f"ag_dep_{i}"] = gp["g_dep"]
            agg_params[f"ag_mun_{i}"] = gp["g_mun"]
            group_clauses.append(
                f"(departamento IS NOT DISTINCT FROM %(ag_dep_{i})s "
                f"AND municipio IS NOT DISTINCT FROM %(ag_mun_{i})s)"
            )
        agg_where = f"{where} AND ({' OR '.join(group_clauses)})"
        with pool.connection() as conn:
            conn.execute("SET LOCAL statement_timeout = '900s'")
            agg = conn.execute(
                "SELECT count(*), count(DISTINCT codigoestacion), "
                "count(DISTINCT zonahidrografica), min(fechaobservacion), "
                f"max(fechaobservacion) FROM observaciones WHERE {agg_where}",
                agg_params,
            ).fetchone()
        processed = int(agg[0])
        station_count, zone_count = int(agg[1]), int(agg[2])
        observed_start, observed_end = agg[3], agg[4]
    elif fast_csv:
        processed = 0

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
        "stationCount": station_count if station_count is not None else len(stations),
        "municipalityCount": len(municipios),
        "departmentCount": len(canonicals),
        "zoneCount": zone_count if zone_count is not None else len(zonas),
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
