"""Motor de descarga NO interactivo (para la TUI y scripts).

Replica la lógica de core.descargar_estandar_por_meses / descargar_especial_directo
pero sin prompts ni salida rich: recibe las tareas/filtros ya construidos, reporta
avance por callback y devuelve un resumen. Reusa intentar(), normalize_chunk(),
deduplicate_observations() y export_by_department_municipality() — el mismo
comportamiento del asistente clásico, solo que silencioso.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import CLIENT, LIMIT, MAX_WORKERS
from .core import intentar
from .exporting import export_by_department_municipality
from .transform import deduplicate_observations, normalize_chunk


def _bajar_bloque(dataset_id, col_fecha, anio, mes, filtros, descripcion):
    """Descarga un bloque (año/mes) paginando; devuelve lista de filas o None si falla."""
    f = list(filtros)
    if anio and mes:
        sig_a, sig_m = (anio, mes + 1) if mes < 12 else (anio + 1, 1)
        f.append(f"{col_fecha} >= '{anio}-{mes:02d}-01T00:00:00.000'")
        f.append(f"{col_fecha} < '{sig_a}-{sig_m:02d}-01T00:00:00.000'")
    elif anio and not mes:
        f.append(f"{col_fecha} >= '{anio}-01-01T00:00:00.000'")
        f.append(f"{col_fecha} < '{anio + 1}-01-01T00:00:00.000'")
    where = " AND ".join(f) if f else None

    filas, offset = [], 0
    while True:
        data = intentar(
            lambda: CLIENT.get(dataset_id, where=where, limit=LIMIT, offset=offset, order=":id"),
            descripcion,
        )
        if data is None:
            return None
        filas.extend(data)
        if len(data) < LIMIT:
            return filas
        offset += LIMIT


def descargar(
    dataset_id, col_fecha, tareas, dict_reemplazo, var_nombre,
    base_dir="data", include_csv=False, on_progress=None,
):
    """Descarga (estándar o especial) según las tareas dadas y exporta por carpetas.

    tareas: lista de (anio|None, mes|None, filtros_list). Para datasets especiales
    sin fecha, usar (None, None, filtros). Devuelve un dict de resumen.
    on_progress(bloques_hechos, total_bloques, filas_brutas) por cada bloque.
    """
    t0 = time.time()
    resultados = []
    total = len(tareas)
    hechos = 0
    filas_brutas = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futuros = {
            pool.submit(_bajar_bloque, dataset_id, col_fecha, t[0], t[1], t[2], var_nombre): t
            for t in tareas
        }
        for fut in as_completed(futuros):
            data = fut.result()
            if data is None:
                raise RuntimeError(f"Fallo crítico descargando {var_nombre}")
            resultados.extend(data)
            filas_brutas += len(data)
            hechos += 1
            if on_progress:
                on_progress(hechos, total, filas_brutas)

    if not resultados:
        return {"rows": 0, "raw_rows": 0, "duplicates": 0,
                "files_parquet": 0, "files_csv": 0,
                "output_dir": base_dir, "seconds": round(time.time() - t0, 1)}

    df = normalize_chunk(resultados, dataset_id, col_fecha or "fechaobservacion", dict_reemplazo)
    raw = len(df)
    df, dups = deduplicate_observations(df, col_fecha or "fechaobservacion")
    outputs = export_by_department_municipality(df, var_nombre, base_dir=base_dir, include_csv=include_csv)
    total_csv = sum(len(o["csv"]) for o in outputs)

    return {
        "rows": len(df),
        "raw_rows": raw,
        "duplicates": dups,
        "files_parquet": len(outputs),
        "files_csv": total_csv,
        "output_dir": base_dir,
        "seconds": round(time.time() - t0, 1),
    }
