"""Descarga NO interactiva (scriptable) para la CLI.

Reusa la misma maquinaria del flujo interactivo (paginacion con reintentos,
normalizacion, deduplicacion y export por departamento/municipio) pero sin
prompts: pensada para automatizar descargas desde scripts o tareas programadas.

Ejemplo:
    ideam-socrata download --dataset s54a-sgyg --department ATLANTICO \
        --start-date 2024-01-01 --end-date 2024-03-01 --csv
"""

from __future__ import annotations

import difflib
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from .config import (
    APP_TOKEN,
    CLIENT,
    DATASETS_INFO,
    DOMAIN,
    LIMIT,
    MAX_WORKERS,
    MAPEO_DEPARTAMENTOS,
    console,
)
from .core import intentar
from .exporting import export_by_department_municipality
from .query_validation import build_department_filter
from .transform import deduplicate_observations, normalize_chunk, normalize_label, parse_export_dates

DATASETS_ESTANDAR = {d["id"]: d for d in DATASETS_INFO if d.get("tipo") == "estandar"}

# tamanos aproximados (medidos jun-2026) para orientar al usuario
_TAMANO_APROX = {
    "s54a-sgyg": "~282M filas", "sgfv-3yp8": "~127M filas", "kiw7-v9ta": "~110M filas",
    "uext-mhny": "~87M filas", "62tk-nxj5": "~34M filas", "ccvq-rp9s": "~27M filas",
    "afdg-3zpb": "~27M filas", "bdmn-sqnh": "~21M filas", "vfth-yucv": "~14M filas",
    "pt9a-aamx": "~12M filas", "uxy3-jchf": "~1.3M filas", "ia8x-22em": "~278K filas",
    "7z6g-yx9q": "~93K filas",
}

_CANONICO_POR_VARIANTE = {
    normalize_label(v): canonico
    for canonico, variantes in MAPEO_DEPARTAMENTOS.items()
    for v in [canonico, *variantes]
}


def _validar_departamentos(departments: list[str]) -> list[str]:
    """Valida ANTES de ir a la red; con sugerencia ante errores de escritura."""
    canonicos: list[str] = []
    for dep in departments:
        canonico = _CANONICO_POR_VARIANTE.get(normalize_label(dep))
        if canonico is None:
            cercano = difflib.get_close_matches(
                normalize_label(dep), list(_CANONICO_POR_VARIANTE), n=1, cutoff=0.6
            )
            pista = f" ¿Quisiste decir '{_CANONICO_POR_VARIANTE[cercano[0]]}'?" if cercano else ""
            raise SystemExit(
                f"Departamento no reconocido: '{dep}'.{pista}\n"
                f"Validos: {', '.join(sorted(MAPEO_DEPARTAMENTOS))}"
            )
        if canonico not in canonicos:
            canonicos.append(canonico)
    return canonicos


def _validar_fechas(start_date: str, end_date: str) -> None:
    try:
        inicio, fin = date.fromisoformat(start_date), date.fromisoformat(end_date)
    except ValueError:
        raise SystemExit(
            f"Fecha invalida: '{start_date}' / '{end_date}'. Usa el formato YYYY-MM-DD, ej: 2024-01-31."
        ) from None
    if inicio >= fin:
        raise SystemExit(
            f"Rango invalido: --start-date ({start_date}) debe ser ANTERIOR a --end-date "
            f"({end_date}). Nota: end-date es exclusivo (no se incluye ese dia)."
        )


def month_blocks(start_date: str, end_date: str):
    """Bloques (anio, mes) que cubren [start_date, end_date)."""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    blocks = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        blocks.append((year, month))
        year, month = (year, month + 1) if month < 12 else (year + 1, 1)
    return blocks


def _fetch_block(dataset_id, col_fecha, year, month, base_filters, descripcion):
    filters = list(base_filters)
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    filters.append(f"{col_fecha} >= '{year}-{month:02d}-01T00:00:00.000'")
    filters.append(f"{col_fecha} < '{next_year}-{next_month:02d}-01T00:00:00.000'")
    where = " AND ".join(filters)

    rows, offset = [], 0
    while True:
        data = intentar(
            lambda: CLIENT.get(dataset_id, where=where, limit=LIMIT, offset=offset, order=":id"),
            f"{descripcion} {year}-{month:02d} offset={offset}",
        )
        if data is None:
            raise RuntimeError(f"Fallo critico descargando {descripcion} {year}-{month:02d}")
        rows.extend(data)
        if len(data) < LIMIT:
            return rows
        offset += LIMIT


def _fetch_block_fast(dataset_id, col_fecha, year, month, where_deptos, descripcion):
    """Motor 'rapido': /resource (filtra de verdad) + gzip + archivo temporal.

    Hallazgos verificados (jun-2026): gzip en transito funciona aunque no este
    documentado (requests lo negocia solo); descargar a archivo con lectura
    continua evita los cortes del streaming entrelazado. OJO: el export
    rows.csv IGNORA $where (devuelve todo) -> se usa /resource, que exige
    $limit explicito. Devuelve un DataFrame en formato SODA normalizado.
    """
    next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
    where = (
        f"{where_deptos} AND {col_fecha} >= '{year}-{month:02d}-01T00:00:00.000' "
        f"AND {col_fecha} < '{next_year}-{next_month:02d}-01T00:00:00.000'"
    )
    domain = DOMAIN if DOMAIN.startswith("http") else f"https://{DOMAIN}"
    headers = {"X-App-Token": APP_TOKEN} if APP_TOKEN else {}

    def _bajar():
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with requests.get(
                f"{domain}/resource/{dataset_id}.csv",
                params={"$where": where, "$limit": 500000000},
                headers=headers,
                stream=True,
                timeout=(30, 300),
            ) as resp:
                resp.raise_for_status()
                with open(tmp_path, "wb") as fh:
                    # iter_content descomprime el gzip al vuelo; escribir a disco
                    # mantiene la lectura del socket continua (sin pausas).
                    for chunk in resp.iter_content(chunk_size=1024 * 512):
                        fh.write(chunk)
            try:
                df = pd.read_csv(tmp_path, dtype=str)
            except pd.errors.EmptyDataError:
                return pd.DataFrame()
            df.columns = [str(c).strip().lower() for c in df.columns]
            if col_fecha in df.columns:
                df[col_fecha] = parse_export_dates(df[col_fecha])
            return df
        finally:
            tmp_path.unlink(missing_ok=True)

    df = intentar(_bajar, f"{descripcion} {year}-{month:02d} (rapido)")
    if df is None:
        raise RuntimeError(f"Fallo critico descargando {descripcion} {year}-{month:02d}")
    return df


def download(
    dataset_id: str,
    departments: list[str],
    start_date: str,
    end_date: str,
    include_csv: bool = False,
    base_dir: str = "data",
    workers: int | None = None,
    engine: str = "rapido",
) -> dict:
    """Descarga un dataset estandar filtrado y lo exporta organizado por carpetas.

    engine='rapido' (export cacheado + gzip, 5-10x mas veloz) | 'soda' (paginado clasico).
    """
    dataset = DATASETS_ESTANDAR.get(dataset_id)
    if dataset is None:
        validos = "\n  ".join(
            f"{d['id']}  {d['nombre']}" for d in DATASETS_INFO if d.get("tipo") == "estandar"
        )
        raise SystemExit(
            f"Dataset '{dataset_id}' no reconocido. Datasets disponibles:\n  {validos}"
        )
    if not departments:
        raise SystemExit("Indica al menos un departamento con --department.")
    if engine not in ("rapido", "soda"):
        raise SystemExit("engine debe ser 'rapido' o 'soda'.")

    canonicos = _validar_departamentos(departments)
    _validar_fechas(start_date, end_date)

    col_fecha, nombre = dataset["fecha_col"], dataset["nombre"]
    where_deptos, replacements, _variants = build_department_filter(
        canonicos, MAPEO_DEPARTAMENTOS
    )
    blocks = month_blocks(start_date, end_date)
    console.print(
        f"[texto]Descargando [bold]{nombre}[/bold] ({dataset_id}) | "
        f"{', '.join(canonicos)} | {start_date} -> {end_date} | "
        f"{len(blocks)} bloques | motor {engine}[/texto]"
    )

    t0 = time.time()
    # concurrencia conservadora con el motor rapido (doc Socrata sugiere 2-4)
    max_workers = workers or (4 if engine == "rapido" else min(MAX_WORKERS, 8))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        if engine == "rapido":
            futures = {
                pool.submit(_fetch_block_fast, dataset_id, col_fecha, y, m, where_deptos, nombre): (y, m)
                for y, m in blocks
            }
            frames = [f.result() for f in as_completed(futures)]
            frames = [f for f in frames if f is not None and not f.empty]
            resultados = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            vacio = resultados.empty
        else:
            futures = {
                pool.submit(_fetch_block, dataset_id, col_fecha, y, m, [where_deptos], nombre): (y, m)
                for y, m in blocks
            }
            resultados = []
            for future in as_completed(futures):
                resultados.extend(future.result())
            vacio = not resultados

    if vacio:
        console.print("[bold primario]No se obtuvieron filas en el rango seleccionado.[/bold primario]")
        return {"rows": 0, "files_parquet": 0, "files_csv": 0, "seconds": round(time.time() - t0, 1)}

    df = normalize_chunk(resultados, dataset_id, col_fecha, replacements)
    df, duplicados = deduplicate_observations(df, col_fecha)
    outputs = export_by_department_municipality(df, nombre, base_dir=base_dir, include_csv=include_csv)
    total_csv = sum(len(output["csv"]) for output in outputs)

    summary = {
        "dataset": dataset_id,
        "engine": engine,
        "rows": len(df),
        "duplicates_removed": duplicados,
        "files_parquet": len(outputs),
        "files_csv": total_csv,
        "output_dir": base_dir,
        "seconds": round(time.time() - t0, 1),
    }
    console.print(
        f"[bold exito]Listo:[/bold exito] [texto]{summary['rows']:,} filas unicas "
        f"({duplicados:,} duplicados eliminados) -> {len(outputs)} parquet, {total_csv} csv "
        f"en '{base_dir}/' ({summary['seconds']}s)[/texto]"
    )
    return summary


def list_datasets() -> None:
    """Imprime los datasets disponibles para `download` y el asistente."""
    console.print("[bold secundario]Datasets estandar (usables con download):[/bold secundario]")
    for d in DATASETS_INFO:
        if d.get("tipo") == "estandar":
            tamano = _TAMANO_APROX.get(d["id"], "")
            console.print(f"  [bold]{d['id']}[/bold]  {d['nombre']:<32} [texto_oscuro]{tamano}[/texto_oscuro]")
    console.print("\n[bold secundario]Datasets especiales (solo asistente interactivo):[/bold secundario]")
    for d in DATASETS_INFO:
        if d.get("tipo") == "especial":
            console.print(f"  [bold]{d['id']}[/bold]  {d['nombre']}")
