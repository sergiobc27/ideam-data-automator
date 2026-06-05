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
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

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


class SocrataError(RuntimeError):
    """La API de Socrata no respondió tras agotar los reintentos."""

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
            raise SocrataError(f"{descripcion} {year}-{month:02d}")
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
        raise SocrataError(f"{descripcion} {year}-{month:02d}")
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
    quiet: bool = False,
    on_progress=None,
) -> dict:
    """Descarga un dataset estandar filtrado y lo exporta organizado por carpetas.

    engine='rapido' (export cacheado + gzip, 5-10x mas veloz) | 'soda' (paginado clasico).
    quiet=True suprime toda salida rich (para front-ends como la TUI).
    on_progress(bloques_hechos, total_bloques, filas) se llama tras cada bloque.
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
    if not quiet:
        console.print(
            f"[texto]Descargando [bold]{nombre}[/bold] ({dataset_id}) | "
            f"{', '.join(canonicos)} | {start_date} -> {end_date} | "
            f"{len(blocks)} bloques | motor {engine}[/texto]"
        )

    t0 = time.time()
    # concurrencia conservadora con el motor rapido (doc Socrata sugiere 2-4)
    max_workers = workers or (4 if engine == "rapido" else min(MAX_WORKERS, 8))
    frames: list[pd.DataFrame] = []
    registros: list[dict] = []

    def _descargar(update):
        """Ejecuta los bloques en paralelo; update(hechos, filas) por cada uno."""
        filas = 0
        hechos = 0
        try:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                worker = _fetch_block_fast if engine == "rapido" else _fetch_block
                futures = [
                    pool.submit(worker, dataset_id, col_fecha, y, m,
                                where_deptos if engine == "rapido" else [where_deptos], nombre)
                    for y, m in blocks
                ]
                for future in as_completed(futures):
                    resultado = future.result()
                    if engine == "rapido":
                        if resultado is not None and not resultado.empty:
                            frames.append(resultado)
                            filas += len(resultado)
                    else:
                        registros.extend(resultado)
                        filas = len(registros)
                    hechos += 1
                    update(hechos, filas)
        except SocrataError as exc:
            raise SystemExit(
                f"\nNo se pudo completar la descarga: la API de Socrata no respondió "
                f"para {exc} tras varios reintentos.\n"
                "Suele ser un problema temporal del servidor de Datos Abiertos. "
                "Espera unos minutos y reintenta; si persiste, prueba con --engine soda "
                "o un rango de fechas más corto."
            ) from None

    def _update(hechos, filas):
        if on_progress:
            on_progress(hechos, len(blocks), filas)

    if quiet:
        _descargar(_update)
    else:
        with Progress(
            TextColumn("  [progress.description]{task.description}"),
            BarColumn(bar_width=None),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TextColumn("• [bold secundario]{task.fields[filas]} filas brutas"),
            console=console,
        ) as progress:
            tarea = progress.add_task("Descargando bloques", total=len(blocks), filas="0")

            def _update_rich(hechos, filas):
                progress.update(tarea, completed=hechos, filas=f"{filas:,}")
                _update(hechos, filas)

            _descargar(_update_rich)

    if engine == "rapido":
        resultados = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        vacio = resultados.empty if isinstance(resultados, pd.DataFrame) else True
    else:
        resultados = registros
        vacio = not registros

    if vacio:
        if not quiet:
            console.print(
                Panel(
                    f"[texto]La consulta fue válida pero el IDEAM no tiene registros de "
                    f"[bold]{nombre}[/bold] para [bold]{', '.join(canonicos)}[/bold] entre "
                    f"{start_date} y {end_date}.\n\n"
                    "Posibles razones:\n"
                    "  • No existen estaciones de esa variable en ese departamento.\n"
                    "  • El periodo elegido está fuera del histórico disponible.\n\n"
                    "Sugerencia: revisa la cobertura con "
                    f"[s_bold]ideam-socrata verify --department {canonicos[0]} "
                    f"--dataset-id {dataset_id}[/s_bold], o prueba otro departamento/periodo.[/texto]",
                    title="[s_bold] SIN DATOS [/s_bold]",
                    border_style="secundario",
                    expand=False,
                    padding=(1, 2),
                )
            )
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
    if not quiet:
        console.print(
            Panel(
                f"[texto]Filas únicas: [bold]{summary['rows']:,}[/bold]\n"
                f"Duplicados eliminados: {duplicados:,}\n"
                f"Archivos generados: {len(outputs)} parquet · {total_csv} csv\n"
                f"Carpeta: {base_dir}/\n"
                f"Tiempo: {summary['seconds']}s · motor {engine}[/texto]",
                title="[bold exito] DESCARGA COMPLETA [/bold exito]",
                border_style="exito",
                expand=False,
                padding=(1, 2),
            )
        )
    return summary


def list_datasets() -> None:
    """Imprime los datasets disponibles para `download` y el asistente."""
    tabla = Table(
        title="Datasets IDEAM — usables con 'download'",
        title_style="p_bold",
        header_style="s_bold",
        border_style="borde",
    )
    tabla.add_column("ID", style="bold", no_wrap=True)
    tabla.add_column("Variable")
    tabla.add_column("Tamaño aprox.", justify="right", style="texto_oscuro")
    for d in DATASETS_INFO:
        if d.get("tipo") == "estandar":
            tabla.add_row(d["id"], d["nombre"], _TAMANO_APROX.get(d["id"], "—"))
    console.print(tabla)

    especiales = Table(
        title="Datasets especiales — solo asistente interactivo",
        title_style="texto_oscuro",
        header_style="texto_oscuro",
        border_style="borde",
    )
    especiales.add_column("ID", style="bold", no_wrap=True)
    especiales.add_column("Variable")
    for d in DATASETS_INFO:
        if d.get("tipo") == "especial":
            especiales.add_row(d["id"], d["nombre"])
    console.print(especiales)
