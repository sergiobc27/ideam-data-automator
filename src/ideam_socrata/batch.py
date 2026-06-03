"""Descarga NO interactiva (scriptable) para la CLI.

Reusa la misma maquinaria del flujo interactivo (paginacion con reintentos,
normalizacion, deduplicacion y export por departamento/municipio) pero sin
prompts: pensada para automatizar descargas desde scripts o tareas programadas.

Ejemplo:
    ideam-socrata download --dataset s54a-sgyg --department ATLANTICO \
        --start-date 2024-01-01 --end-date 2024-03-01 --csv
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from .config import CLIENT, DATASETS_INFO, LIMIT, MAX_WORKERS, MAPEO_DEPARTAMENTOS, console
from .core import intentar
from .exporting import export_by_department_municipality
from .query_validation import build_department_filter
from .transform import deduplicate_observations, normalize_chunk

DATASETS_ESTANDAR = {d["id"]: d for d in DATASETS_INFO if d.get("tipo") == "estandar"}


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


def download(
    dataset_id: str,
    departments: list[str],
    start_date: str,
    end_date: str,
    include_csv: bool = False,
    base_dir: str = "data",
    workers: int | None = None,
) -> dict:
    """Descarga un dataset estandar filtrado y lo exporta organizado por carpetas."""
    dataset = DATASETS_ESTANDAR.get(dataset_id)
    if dataset is None:
        validos = ", ".join(sorted(DATASETS_ESTANDAR))
        raise SystemExit(f"Dataset '{dataset_id}' no es de tipo estandar. Validos: {validos}")
    if not departments:
        raise SystemExit("Indica al menos un departamento con --department.")

    col_fecha, nombre = dataset["fecha_col"], dataset["nombre"]
    where_deptos, replacements, _variants = build_department_filter(
        departments, MAPEO_DEPARTAMENTOS
    )
    blocks = month_blocks(start_date, end_date)
    console.print(
        f"[texto]Descargando [bold]{nombre}[/bold] ({dataset_id}) | "
        f"{', '.join(departments)} | {start_date} -> {end_date} | {len(blocks)} bloques[/texto]"
    )

    t0 = time.time()
    resultados: list[dict] = []
    max_workers = workers or min(MAX_WORKERS, 8)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_fetch_block, dataset_id, col_fecha, y, m, [where_deptos], nombre): (y, m)
            for y, m in blocks
        }
        for future in as_completed(futures):
            resultados.extend(future.result())

    if not resultados:
        console.print("[bold primario]No se obtuvieron filas en el rango seleccionado.[/bold primario]")
        return {"rows": 0, "files_parquet": 0, "files_csv": 0, "seconds": round(time.time() - t0, 1)}

    df = normalize_chunk(resultados, dataset_id, col_fecha, replacements)
    df, duplicados = deduplicate_observations(df, col_fecha)
    outputs = export_by_department_municipality(df, nombre, base_dir=base_dir, include_csv=include_csv)
    total_csv = sum(len(output["csv"]) for output in outputs)

    summary = {
        "dataset": dataset_id,
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
            console.print(f"  [bold]{d['id']}[/bold]  {d['nombre']}")
    console.print("\n[bold secundario]Datasets especiales (solo asistente interactivo):[/bold secundario]")
    for d in DATASETS_INFO:
        if d.get("tipo") == "especial":
            console.print(f"  [bold]{d['id']}[/bold]  {d['nombre']}")
