"""Backfill historico de datasets Socrata hacia la hypertable observaciones.

Estrategia: por dataset y ventana anual, descarga CSV en streaming desde el
endpoint SODA (sin offsets profundos), normaliza con el pipeline existente
(transform.normalize_chunk -> floating_id) y carga via COPY + upsert.
Reanudable: cada (dataset, anio) queda registrado en ingest_state.

Uso:
    python -m ideam_socrata.db.backfill --dataset ia8x-22em
    python -m ideam_socrata.db.backfill --dataset all --chunksize 100000
"""

import argparse
import itertools
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from ..config import APP_TOKEN, DOMAIN, MAPEO_DEPARTAMENTOS, DATASETS_INFO, CLIENT

# Pool de App Tokens para ROTACIÓN (reparte la carga y evita re-throttlear uno
# solo). Se lee de SOCRATA_APP_TOKENS (coma-separado); si no, usa el unico.
_TOKEN_POOL = [t.strip() for t in os.getenv("SOCRATA_APP_TOKENS", "").split(",") if t.strip()]
if not _TOKEN_POOL and APP_TOKEN:
    _TOKEN_POOL = [APP_TOKEN]
_token_cycle = itertools.cycle(_TOKEN_POOL) if _TOKEN_POOL else None
_token_lock = threading.Lock()


def _next_token():
    """Devuelve el siguiente token del pool (round-robin, seguro en hilos)."""
    if not _token_cycle:
        return None
    with _token_lock:
        return next(_token_cycle)
from ..transform import deduplicate_observations, normalize_chunk
from . import state
from .connection import get_conn
from .copy_loader import load_dataframe

logger = logging.getLogger(__name__)

DATASETS_ESTANDAR = [d for d in DATASETS_INFO if d.get("tipo") == "estandar"]

# Orden de backfill (re-priorizado 2026-06-04): precipitacion es el dataset
# insignia del proyecto -> va apenas termine velocidad del viento, para tener
# los datos mas valiosos disponibles antes. Humedad (grande) cierra.
_RANGO_TAMANO = {
    "ia8x-22em": 0,    # Nivel del Mar (completo)
    "kiw7-v9ta": 1,    # Direccion Viento (completo)
    "sgfv-3yp8": 2,    # Velocidad Viento (en curso)
    "s54a-sgyg": 3,    # PRECIPITACION (282M) - priorizada
    # resto (presion, niveles de rio/mar, temperaturas): rango 40 por defecto
    "uext-mhny": 90,   # Humedad (87M) al final
}

# variante -> canonico (normalize_chunk lo aplica con normalize_label)
DICT_REEMPLAZO = {
    variante: canonico
    for canonico, variantes in MAPEO_DEPARTAMENTOS.items()
    for variante in variantes
}


def _retry(func, descripcion, max_intentos=5):
    """Reintentos con backoff (replica core.intentar sin dependencias de UI)."""
    for i in range(max_intentos):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001
            espera = (i + 1) * 5 if "429" in str(exc).lower() else 2 ** i
            logger.warning("Error en %s (intento %s/%s): %s", descripcion, i + 1, max_intentos, exc)
            if i == max_intentos - 1:
                raise
            time.sleep(espera)


def year_range(dataset_id, col_fecha):
    """Descubre el rango de anios disponible en Socrata para el dataset."""
    rows = _retry(
        lambda: CLIENT.get(
            dataset_id, select=f"min({col_fecha}) AS mn, max({col_fecha}) AS mx", limit=1
        ),
        f"rango {dataset_id}",
    )
    mn, mx = rows[0].get("mn"), rows[0].get("mx")
    if not mn or not mx:
        return []
    return list(range(int(mn[:4]), int(mx[:4]) + 1))


def csv_chunks_for_window(dataset_id, col_fecha, start_iso, end_iso, chunksize):
    """Stream CSV de Socrata para una ventana temporal, en chunks de pandas.

    dtype=str es OBLIGATORIO: conserva ceros a la izquierda en codigoestacion/
    codigosensor para que el floating_id sea identico al de la ruta JSON.
    SIN $order: ordenar fuerza a Socrata a preparar todo antes de streamear
    (>10 min en anios grandes -> read timeout); el upsert no necesita orden.
    """
    where = f"{col_fecha} >= '{start_iso}' AND {col_fecha} < '{end_iso}'"
    params = {"$where": where, "$limit": 500000000}
    headers = {"X-App-Token": APP_TOKEN} if APP_TOKEN else {}
    domain = DOMAIN if DOMAIN.startswith("http") else f"https://{DOMAIN}"
    resp = requests.get(
        f"{domain}/resource/{dataset_id}.csv",
        params=params,
        headers=headers,
        stream=True,
        timeout=(30, 600),
    )
    resp.raise_for_status()
    resp.raw.decode_content = True
    return pd.read_csv(resp.raw, dtype=str, chunksize=chunksize)


def backfill_window(conn, dataset_id, col_fecha, start_iso, end_iso, chunksize):
    rows_loaded = 0
    try:
        reader = csv_chunks_for_window(dataset_id, col_fecha, start_iso, end_iso, chunksize)
    except pd.errors.EmptyDataError:
        return 0
    for chunk in reader:
        if chunk.empty:
            continue
        df = normalize_chunk(chunk, dataset_id, col_fecha, DICT_REEMPLAZO)
        df, _dups = deduplicate_observations(df, col_fecha)
        rows_loaded += load_dataframe(conn, df, mode="insert")
    return rows_loaded


RAW_DIR = Path(os.getenv("BACKFILL_RAW_DIR", "/opt/ideam/raw"))
# Exports masivos (.csv.gz, guardados SIN descomprimir: 6.8x menos disco) que
# alimentan la carga local sin red. Ver split_bulk_local().
BULK_DIR = Path(os.getenv("BACKFILL_BULK_DIR", "/opt/ideam/bulk"))


def download_bulk_csv(dataset_id, attempts=3):
    """Descarga el export masivo COMPLETO a disco con curl (lectura continua).

    Clave del diseno: el descargador lee el socket a maxima velocidad SIN
    pausas de procesamiento -> Socrata no corta la conexion por ociosidad
    (que era la causa real de los IncompleteRead). Igual que un navegador.
    Si el archivo ya existe (pre-descargado), se reusa.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"{dataset_id}.csv"
    if dest.exists() and dest.stat().st_size > 0:
        logger.info("Bulk %s ya descargado (%.1f GB)", dataset_id, dest.stat().st_size / 1e9)
        return dest

    domain = DOMAIN if DOMAIN.startswith("http") else f"https://{DOMAIN}"
    url = f"{domain}/api/views/{dataset_id}/rows.csv?accessType=DOWNLOAD"
    part = dest.with_suffix(".part")
    # --compressed: gzip en transito (no documentado pero funciona) -> el archivo
    # viaja 5-8x mas chico y la conexion termina antes del timeout del servidor.
    # --max-time generoso (12h): seguro final contra esperas infinitas del
    # primer byte; el export completo de precipitacion puede tomar horas.
    cmd = ["curl", "-sS", "--fail", "--compressed", "--connect-timeout", "30",
           "--max-time", "43200",
           "--speed-limit", "1000", "--speed-time", "120", "-o", str(part), url]
    if APP_TOKEN:
        cmd[1:1] = ["-H", f"X-App-Token: {APP_TOKEN}"]

    for i in range(attempts):
        t0 = time.time()
        try:
            part.unlink(missing_ok=True)
            subprocess.run(cmd, check=True)
            part.rename(dest)
            gb = dest.stat().st_size / 1e9
            logger.info("Bulk %s descargado: %.2f GB en %.0f min", dataset_id, gb, (time.time() - t0) / 60)
            print(f"  {dataset_id}: CSV masivo descargado ({gb:.2f} GB)", flush=True)
            return dest
        except subprocess.CalledProcessError as exc:
            logger.warning("Descarga bulk %s fallo (intento %s/%s): %s", dataset_id, i + 1, attempts, exc)
            if i == attempts - 1:
                raise
            time.sleep(30 * (i + 1))


def _load_csv_file(conn, dataset, path, chunksize, report_label=None):
    """Procesa un CSV YA descargado: sin esperas de red, solo CPU+COPY."""
    dataset_id, col_fecha = dataset["id"], dataset["fecha_col"]
    rows_loaded = 0
    t0 = time.time()
    next_report = 2_000_000
    try:
        reader = pd.read_csv(path, dtype=str, chunksize=chunksize)
    except pd.errors.EmptyDataError:
        return 0
    for chunk in reader:
        chunk.columns = [str(c).strip().lower() for c in chunk.columns]
        if col_fecha in chunk.columns:
            chunk[col_fecha] = _parse_bulk_dates(chunk[col_fecha])
        df = normalize_chunk(chunk, dataset_id, col_fecha, DICT_REEMPLAZO)
        df, _dups = deduplicate_observations(df, col_fecha)
        rows_loaded += load_dataframe(conn, df, mode="insert")
        if report_label and rows_loaded >= next_report:
            rate = rows_loaded / max(time.time() - t0, 1)
            print(f"  {report_label}: {rows_loaded:,} filas ({rate:,.0f}/s)", flush=True)
            next_report += 2_000_000
    return rows_loaded


def process_csv_file(conn, dataset, path, chunksize):
    return _load_csv_file(conn, dataset, path, chunksize, report_label=f"{dataset['id']} disco")


def download_window_csv(dataset_id, col_fecha, start_iso, end_iso, attempts=3):
    """Descarga UNA ventana temporal a disco desde /resource/ (SODA).

    OJO (verificado 2026-06-04): el endpoint export rows.csv IGNORA $where en
    silencio (devuelve el dataset completo con HTTP 200). El unico que filtra
    de verdad es /resource/{id}.csv, que exige $limit explicito (default 1000).
    Se usa con gzip (--compressed) y descarga continua a disco; la unidad de
    reintento es la ventana completa (no hay HTTP Range).
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"{dataset_id}_{start_iso[:10]}.csv"
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    domain = DOMAIN if DOMAIN.startswith("http") else f"https://{DOMAIN}"
    where = f"{col_fecha} >= '{start_iso}' AND {col_fecha} < '{end_iso}'"
    part = dest.with_suffix(".part")
    # --max-time es el seguro final: --speed-limit solo corta DURANTE la
    # transferencia; si el servidor acepta la conexion y nunca envia el primer
    # byte, curl espera infinito (cuelgue real de 7h visto el 2026-06-05).
    # 6h es holgado: la ventana mas pesada (precipitacion-anio) toma ~3h.
    cmd = ["curl", "-sS", "--fail", "--compressed", "-G",
           "--connect-timeout", "30", "--max-time", "21600",
           "--speed-limit", "500", "--speed-time", "300",
           "--data-urlencode", f"$where={where}",
           "--data-urlencode", "$limit=500000000",
           "-o", str(part),
           f"{domain}/resource/{dataset_id}.csv"]
    tok = _next_token()
    if tok:
        cmd[1:1] = ["-H", f"X-App-Token: {tok}"]

    for i in range(attempts):
        try:
            part.unlink(missing_ok=True)
            subprocess.run(cmd, check=True)
            part.rename(dest)
            return dest
        except subprocess.CalledProcessError as exc:
            logger.warning("Ventana %s %s fallo (intento %s/%s): %s",
                           dataset_id, start_iso[:10], i + 1, attempts, exc)
            if i == attempts - 1:
                raise
            time.sleep(20 * (i + 1))


def bulk_csv_chunks(dataset_id, chunksize):
    """Stream del export masivo de Socrata (rows.csv): ~15x mas rapido que
    filtrar por ventanas, porque sirve una copia ya preparada del dataset.

    Diferencias vs la API SODA que se normalizan despues:
    - encabezados en CamelCase (CodigoEstacion...) -> se pasan a minusculas.
    - fechas en formato US (11/15/2024 10:20:00 PM) -> se parsean explicito.
    """
    headers = {"X-App-Token": APP_TOKEN} if APP_TOKEN else {}
    domain = DOMAIN if DOMAIN.startswith("http") else f"https://{DOMAIN}"
    resp = requests.get(
        f"{domain}/api/views/{dataset_id}/rows.csv",
        params={"accessType": "DOWNLOAD"},
        headers=headers,
        stream=True,
        timeout=(30, 600),
    )
    resp.raise_for_status()
    resp.raw.decode_content = True
    return pd.read_csv(resp.raw, dtype=str, chunksize=chunksize)


def _parse_bulk_dates(serie):
    """Fechas del export masivo: formato US explicito (rapido), con fallback."""
    parsed = pd.to_datetime(serie, format="%m/%d/%Y %I:%M:%S %p", errors="coerce")
    mask = parsed.isna() & serie.notna()
    if mask.any():
        parsed.loc[mask] = pd.to_datetime(serie.loc[mask], errors="coerce")
    return parsed


def backfill_full(conn, dataset, chunksize):
    """Backfill de un dataset completo en un solo stream masivo (modo preferido)."""
    dataset_id, col_fecha = dataset["id"], dataset["fecha_col"]
    state.mark(conn, dataset_id, "backfill", "full", "running")
    rows_loaded = 0
    t0 = time.time()
    next_report = 1_000_000
    for chunk in bulk_csv_chunks(dataset_id, chunksize):
        chunk.columns = [str(c).strip().lower() for c in chunk.columns]
        if col_fecha in chunk.columns:
            chunk[col_fecha] = _parse_bulk_dates(chunk[col_fecha])
        df = normalize_chunk(chunk, dataset_id, col_fecha, DICT_REEMPLAZO)
        df, _dups = deduplicate_observations(df, col_fecha)
        rows_loaded += load_dataframe(conn, df, mode="insert")
        if rows_loaded >= next_report:
            rate = rows_loaded / max(time.time() - t0, 1)
            print(
                f"  {dataset_id} full: {rows_loaded:,} filas ({rate:,.0f}/s)", flush=True
            )
            state.mark(conn, dataset_id, "backfill", "full", "running", rows_loaded=rows_loaded)
            next_report += 1_000_000
    state.mark(conn, dataset_id, "backfill", "full", "done", rows_loaded=rows_loaded)
    print(
        f"  {dataset_id} full: COMPLETO {rows_loaded:,} filas en {(time.time() - t0) / 60:.1f} min",
        flush=True,
    )
    return rows_loaded


def month_windows(year):
    for month in range(1, 13):
        next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
        yield (
            f"{year}-{month:02d}-01T00:00:00.000",
            f"{next_year}-{next_month:02d}-01T00:00:00.000",
        )


def backfill_window_disk(conn, dataset, start_iso, end_iso, chunksize):
    """Ventana temporal: descarga a disco (gzip, continua) -> procesa -> borra."""
    path = download_window_csv(dataset["id"], dataset["fecha_col"], start_iso, end_iso)
    rows = _load_csv_file(conn, dataset, path, chunksize)
    path.unlink(missing_ok=True)  # solo se borra tras procesar con exito
    return rows


def backfill_year(conn, dataset, year, chunksize):
    # Preferir el recorte local del export masivo (creado por split_bulk_local):
    # carga a velocidad de COPY, sin Socrata (ni throttling) en el camino.
    local = BULK_DIR / f"{dataset['id']}_{year}.csv"
    if local.exists():
        rows = _load_csv_file(conn, dataset, local, chunksize,
                              report_label=f"{dataset['id']} {year} local")
        local.unlink(missing_ok=True)  # ya cargado; libera disco
        return rows
    return backfill_window_disk(
        conn, dataset,
        f"{year}-01-01T00:00:00.000", f"{year + 1}-01-01T00:00:00.000", chunksize,
    )


# ============================================================
# Modo POR AÑO (carga año-a-año comprimiendo cada año al cerrarlo)
# Necesario porque los 745M descomprimidos no caben en 200GB:
# en todo momento solo 1 año queda descomprimido; al terminar
# todos los datasets de un año, ese año se comprime (rapido, sin
# el problema de insertar en chunks ya comprimidos).
# ============================================================

def _load_dataset_year(dataset, year, chunksize):
    """Descarga+carga un (dataset, año) en su PROPIA conexion (seguro en hilos)."""
    try:
        with get_conn() as conn:
            return backfill_year(conn, dataset, year, chunksize)
    except Exception as exc:  # noqa: BLE001
        logger.error("Fallo %s %s: %s", dataset["id"], year, exc)
        return -1  # marca de error sin abortar todo el año


def _split_done(conn, dataset_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ingest_state WHERE source_dataset_id=%s "
            "AND grain='split' AND status='done'",
            (dataset_id,),
        )
        return cur.fetchone() is not None


def split_bulk_local(dataset, years_needed, chunksize):
    """Parte el export masivo .csv.gz local en CSVs por año (solo años pendientes).

    Un solo pase de lectura por dataset. Las filas de años ya cargados y
    COMPRIMIDOS (2019+) se descartan aquí y nunca llegan a la base — así jamás
    se toca un chunk comprimido (la lección del 100x). Reanudable a nivel
    dataset vía ingest_state grain='split'. Conserva los valores ORIGINALES
    del export (encabezados CamelCase, fechas US): _load_csv_file ya sabe
    normalizarlos, garantizando floating_id idéntico al de las otras rutas.
    """
    dataset_id, col_fecha = dataset["id"], dataset["fecha_col"]
    src = BULK_DIR / f"{dataset_id}.csv.gz"
    if not src.exists() or src.stat().st_size == 0:
        return False
    with get_conn() as conn:
        if _split_done(conn, dataset_id):
            logger.info("Split %s: ya hecho", dataset_id)
            return True

    years = {int(y) for y in years_needed}
    # limpiar restos de un split anterior interrumpido (se regeneran completos)
    for y in years:
        (BULK_DIR / f"{dataset_id}_{y}.csv").unlink(missing_ok=True)

    creados: set[int] = set()
    escaneadas = 0
    t0 = time.time()
    next_report = 5_000_000
    for chunk in pd.read_csv(src, dtype=str, chunksize=chunksize):
        col_orig = next((c for c in chunk.columns
                         if str(c).strip().lower() == col_fecha), None)
        if col_orig is None:
            logger.error("Split %s: el bulk no tiene columna %s", dataset_id, col_fecha)
            return False
        anios = _parse_bulk_dates(chunk[col_orig]).dt.year
        escaneadas += len(chunk)
        for y, sub in chunk.groupby(anios):  # NaT queda fuera (groupby ignora NaN)
            y = int(y)
            if y not in years:
                continue
            destino = BULK_DIR / f"{dataset_id}_{y}.csv"
            sub.to_csv(destino, mode="a", header=y not in creados, index=False)
            creados.add(y)
        if escaneadas >= next_report:
            rate = escaneadas / max(time.time() - t0, 1)
            print(f"  split {dataset_id}: {escaneadas:,} filas escaneadas "
                  f"({rate:,.0f}/s)", flush=True)
            next_report += 5_000_000

    with get_conn() as conn:
        state.mark(conn, dataset_id, "split", "bulk", "done", rows_loaded=escaneadas)
    # Liberar el .csv.gz: ya cumplió su función (split done, marcado en estado).
    # Recupera disco progresivamente para que los CSV-por-año de TODOS los
    # datasets no coincidan con los 16 GB de gz en el pico (margen de disco).
    # Si el proceso muere luego, los años no cargados caen al fallback por red.
    src.unlink(missing_ok=True)
    print(f"  split {dataset_id}: COMPLETO {escaneadas:,} filas escaneadas -> "
          f"{len(creados)} años pendientes en disco (gz liberado)", flush=True)
    return True


def compress_year(conn, year):
    """Comprime los chunks del año indicado (ya no recibiran mas inserts)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM (SELECT compress_chunk(c, if_not_compressed => true) "
            "FROM show_chunks('observaciones', "
            "newer_than => %s::timestamptz, older_than => %s::timestamptz) c) s",
            (f"{year}-01-01", f"{year + 1}-01-01"),
        )
        n = cur.fetchone()[0]
    conn.commit()
    return n


def _years_done(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT chunk_key FROM ingest_state WHERE grain='year' AND status='done'"
        )
        return {r[0] for r in cur.fetchall()}


def backfill_by_year(conn, datasets, chunksize, workers=4):
    """Carga año por año (descendente), comprimiendo cada año al terminarlo."""
    # rango de años por dataset (una sola consulta liviana a Socrata)
    ds_years = {}
    for d in datasets:
        years = set(year_range(d["id"], d["fecha_col"]))
        ds_years[d["id"]] = years
        logger.info("Rango %s: %s-%s (%s años)", d["id"],
                    min(years) if years else "-", max(years) if years else "-", len(years))

    all_years = sorted(set().union(*ds_years.values()), reverse=True)
    done = _years_done(conn)
    pendientes = [y for y in all_years if str(y) not in done]
    print(f"AÑOS a procesar: {len(pendientes)} (de {min(all_years)} a {max(all_years)}), "
          f"descendente, {workers} datasets en paralelo por año", flush=True)

    # Si hay exports masivos locales (.csv.gz en BULK_DIR), partirlos por año
    # UNA sola vez: la carga año-a-año consumirá archivos locales (sin red).
    con_bulk = [d for d in datasets if (BULK_DIR / f"{d['id']}.csv.gz").exists()
                and (BULK_DIR / f"{d['id']}.csv.gz").stat().st_size > 0]
    if con_bulk and pendientes:
        print(f"SPLIT local: {len(con_bulk)} datasets con export masivo en {BULK_DIR}",
              flush=True)
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="split") as pool:
            list(pool.map(lambda d: split_bulk_local(d, pendientes, chunksize), con_bulk))

    for year in pendientes:
        t0 = time.time()
        objetivos = [d for d in datasets if year in ds_years[d["id"]]]
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"y{year}") as pool:
            resultados = list(pool.map(lambda d: _load_dataset_year(d, year, chunksize), objetivos))
        filas = sum(r for r in resultados if r > 0)
        errores = sum(1 for r in resultados if r < 0)
        if errores == 0:
            # comprimir el año recien cerrado (libera disco antes del siguiente)
            comp = compress_year(conn, year)
            state.mark(conn, "__year__", "year", str(year), "done", rows_loaded=filas)
        else:
            # NO comprimir un año con fallos: el reintento debe poder escribir
            # en estos chunks (insertar en chunks comprimidos = 100x mas lento).
            comp = 0
            state.mark(conn, "__year__", "year", str(year), "error", rows_loaded=filas)
            logger.warning("Año %s con %s datasets fallidos: queda SIN comprimir "
                           "para que el reintento sea barato", year, errores)
        print(f"  AÑO {year}: {filas:,} filas, {comp} chunks comprimidos, "
              f"{errores} datasets con error, {(time.time()-t0)/60:.1f} min", flush=True)

    # Cierre automatico: si TODO el historico quedo cargado, refrescar agregados
    # (las politicas solo miran la ventana reciente: sin esto, los dashboards no
    # verian 2001-2018 pese a estar en la base).
    done_final = _years_done(conn)
    if all(str(y) in done_final for y in all_years):
        cierre_backfill(conn)


def cierre_backfill(conn):
    """Cierre tras cargar el histórico completo.

    1) Refresca los continuous aggregates en TODO el rango (las políticas solo
       refrescan la ventana reciente; sin esto los dashboards no ven 2001-2018).
       Se refresca AÑO POR AÑO con print por paso: mantiene el journal vivo
       (el watchdog reinicia si hay >60 min de silencio) y acota cada paso.
    2) ANALYZE para que el planeador conozca la distribución real.
    """
    conn.commit()
    prev_autocommit = conn.autocommit
    conn.autocommit = True  # refresh_continuous_aggregate no admite transacción
    try:
        with conn.cursor() as cur:
            # rango real desde la hypertable (rapido: exclusion por chunks)
            cur.execute("SELECT extract(year FROM min(fechaobservacion))::int, "
                        "extract(year FROM max(fechaobservacion))::int FROM observaciones")
            fila = cur.fetchone()
            y_min = min(fila[0] or 2000, 2000)
            y_max = (fila[1] or 2026) + 1
            for cagg in ("obs_diario", "obs_mensual"):
                for y in range(y_min, y_max + 1):
                    cur.execute(
                        f"CALL refresh_continuous_aggregate('{cagg}', %s, %s)",
                        (f"{y}-01-01", f"{y + 1}-01-01"),
                    )
                    print(f"CIERRE: {cagg} {y} refrescado", flush=True)
            print("CIERRE: ANALYZE observaciones/estaciones...", flush=True)
            cur.execute("ANALYZE observaciones")
            cur.execute("ANALYZE estaciones")
    finally:
        conn.autocommit = prev_autocommit
    print("CIERRE COMPLETO: agregados y estadísticas al día", flush=True)


def _process_year(dataset, year, chunksize):
    """Procesa un anio completo en su PROPIA conexion (seguro para hilos).

    Cadena de resiliencia: archivo anual -> si falla -> 12 archivos mensuales.
    """
    dataset_id = dataset["id"]
    chunk_key = str(year)
    with get_conn() as conn:
        state.mark(conn, dataset_id, "backfill", chunk_key, "running")
        t0 = time.time()
        try:
            rows = backfill_year(conn, dataset, year, chunksize)
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            # Anio demasiado grande/inestable: particionar en archivos mensuales.
            logger.warning("Anio %s de %s fallo (%s); particionando por meses", year, dataset_id, exc)
            print(f"  {dataset_id} {year}: ventana anual fallo -> particionando por meses", flush=True)
            try:
                rows = 0
                for start_iso, end_iso in month_windows(year):
                    rows += backfill_window_disk(conn, dataset, start_iso, end_iso, chunksize)
            except Exception as exc2:  # noqa: BLE001
                conn.rollback()
                state.mark(conn, dataset_id, "backfill", chunk_key, "error", error=str(exc2)[:500])
                logger.error("Anio %s de %s fallo incluso por meses: %s", year, dataset_id, exc2)
                return 0
        state.mark(conn, dataset_id, "backfill", chunk_key, "done", rows_loaded=rows)
        logger.info("  %s %s: %s filas en %.1fs", dataset_id, year, rows, time.time() - t0)
        print(f"  {dataset_id} {year}: {rows:,} filas en {time.time() - t0:.1f}s", flush=True)
        return rows


def backfill_dataset(conn, dataset, chunksize, start_year=None, end_year=None, workers=5):
    """Backfill de un dataset descargando VARIOS anios de Socrata en paralelo.

    Cada worker usa su propia conexion y staging temporal; el upsert por
    floating_id hace que el paralelismo sea seguro e idempotente.
    """
    dataset_id, col_fecha = dataset["id"], dataset["fecha_col"]
    completados = state.done_chunks(conn, dataset_id, "backfill")
    if "full" in completados:
        logger.info("Backfill %s: ya completo (full).", dataset_id)
        return 0

    # MODO PRINCIPAL: archivo COMPLETO via rows.csv + gzip (la unica via masiva
    # rapida; rows.csv ignora $where asi que solo sirve completo). Con gzip el
    # cable carga 5-8x menos -> la conexion termina antes del timeout del
    # servidor (verificado: presion 5.13GB descargo entera sin cortes).
    if not start_year and not end_year:
        try:
            full_path = RAW_DIR / f"{dataset_id}.csv"
            if not (full_path.exists() and full_path.stat().st_size > 0):
                full_path = download_bulk_csv(dataset_id)
            state.mark(conn, dataset_id, "backfill", "full", "running")
            rows = process_csv_file(conn, dataset, full_path, chunksize)
            state.mark(conn, dataset_id, "backfill", "full", "done", rows_loaded=rows)
            full_path.unlink(missing_ok=True)
            logger.info("Backfill %s completo via archivo: %s filas", dataset_id, rows)
            print(f"  {dataset_id}: COMPLETO via archivo ({rows:,} filas)", flush=True)
            return rows
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            state.mark(conn, dataset_id, "backfill", "full", "error", error=str(exc)[:500])
            logger.error("Modo archivo completo de %s fallo; cayendo a ventanas /resource: %s",
                         dataset_id, exc)

    years = year_range(dataset_id, col_fecha)
    if start_year:
        years = [y for y in years if y >= start_year]
    if end_year:
        years = [y for y in years if y <= end_year]

    pendientes = [y for y in years if str(y) not in completados]
    logger.info(
        "Backfill %s (%s): %s anios, %s pendientes, %s workers",
        dataset["nombre"], dataset_id, len(years), len(pendientes), workers,
    )
    if not pendientes:
        return 0

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"bf-{dataset_id}") as pool:
        totals = list(pool.map(lambda y: _process_year(dataset, y, chunksize), pendientes))
    return sum(totals)


def compress_eligible_chunks(conn):
    """Comprime los chunks que la politica aun no haya tomado (ahorra disco ya)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(count(*),0) FROM (SELECT compress_chunk(c, true) "
            "FROM show_chunks('observaciones', older_than => INTERVAL '30 days') c) s"
        )
        n = cur.fetchone()[0]
    conn.commit()
    return n


def main():
    parser = argparse.ArgumentParser(description="Backfill historico IDEAM -> Postgres")
    parser.add_argument("--dataset", required=True, help="id Socrata (ej. ia8x-22em) o 'all'")
    parser.add_argument("--chunksize", type=int, default=100_000)
    parser.add_argument("--start-year", type=int, default=None)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--compress", action="store_true", help="comprimir chunks al terminar")
    parser.add_argument(
        "--mode", choices=["dataset", "year"], default="dataset",
        help="'year': carga año-a-año comprimiendo cada año (cabe en disco). 'dataset': por dataset.",
    )
    parser.add_argument(
        "--workers", type=int, default=int(os.getenv("BACKFILL_WORKERS", "4")),
        help="paralelismo (default 4; doc Socrata sugiere 2-4)",
    )
    args = parser.parse_args()

    # force=True: config.py ya configuró logging hacia archivo al importarse;
    # esto redirige también a stdout para que llegue al journal de systemd.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", force=True
    )

    if args.dataset == "all":
        objetivos = sorted(DATASETS_ESTANDAR, key=lambda d: _RANGO_TAMANO.get(d["id"], 40))
    else:
        objetivos = [d for d in DATASETS_ESTANDAR if d["id"] == args.dataset]
        if not objetivos:
            raise SystemExit(f"Dataset {args.dataset} no esta en DATASETS_INFO (tipo estandar).")

    with get_conn() as conn:
        if args.mode == "year":
            backfill_by_year(conn, objetivos, args.chunksize, workers=args.workers)
            print("Backfill por año finalizado.", flush=True)
            return

        gran_total = 0
        for dataset in objetivos:
            gran_total += backfill_dataset(
                conn, dataset, args.chunksize, args.start_year, args.end_year,
                workers=args.workers,
            )
            if args.compress:
                # Comprimir tras CADA dataset mantiene el disco bajo control
                # durante toda la corrida (no solo al final).
                n = compress_eligible_chunks(conn)
                print(f"  [{dataset['id']}] chunks comprimidos: {n}", flush=True)
        print(f"TOTAL filas cargadas: {gran_total:,}", flush=True)


if __name__ == "__main__":
    main()
