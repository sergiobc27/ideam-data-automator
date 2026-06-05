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

from .config import CATALOG_DATASET_ID, CLIENT, LIMIT, MAX_WORKERS
from .core import intentar
from .exporting import export_by_department_municipality, write_coverage_report
from .transform import deduplicate_observations, normalize_chunk

# Atributos de filtro avanzado: etiqueta -> columna en la observación.
# (la columna en el CATÁLOGO se traduce con _a_catalogo)
ATRIBUTOS_AVANZADOS = {
    "Zona Hidrográfica": "zonahidrografica",
    "Categoría": "categoria",
    "Tecnología": "tecnologia",
    "Estado": "estado",
    "Corriente": "corriente",
    "Entidad": "entidad",
    "Municipio": "municipio",
}


def _a_catalogo(clausula: str) -> str:
    """Traduce nombres de columna de observación a los del catálogo hp9r-jxuu."""
    return clausula.replace("zonahidrografica", "zona_hidrografica").replace(
        "codigoestacion", "codigo"
    )


def catalogo_valores(attr_col: str, filtros_dep: list[str]) -> list[str]:
    """Valores distintos de un atributo en el catálogo, dados los filtros de depto."""
    c_cat = attr_col.replace("zonahidrografica", "zona_hidrografica")
    where = " AND ".join(_a_catalogo(f) for f in filtros_dep) or None
    rows = intentar(
        lambda: CLIENT.get(CATALOG_DATASET_ID, select=c_cat, where=where, group=c_cat, limit=50000),
        f"catalogo {attr_col}",
    )
    return sorted(str(r.get(c_cat)) for r in (rows or []) if r.get(c_cat))


def cobertura_filtro(dataset_id: str, col_fecha: str, filtros_dep: list[str]) -> dict:
    """Sondea la cobertura REAL para el filtro elegido, antes de descargar.

    - Estaciones del catálogo que cumplen el filtro (total y activas): rápido.
    - Rango min/max de fechas CON el filtro aplicado: 1 solo intento con timeout
      corto (en datasets gigantes Socrata no alcanza a responder; se omite).
    Devuelve {'estaciones', 'activas', 'ini', 'fin'} con None donde no hubo dato.
    """
    import re

    from sodapy import Socrata

    from .config import APP_TOKEN, DOMAIN

    info = {"estaciones": None, "activas": None, "ini": None, "fin": None}
    try:
        where = " AND ".join(_a_catalogo(f) for f in filtros_dep) or None
        rows = CLIENT.get(CATALOG_DATASET_ID, select="estado, count(*) AS n",
                          where=where, group="estado", limit=50)
        info["estaciones"] = sum(int(r["n"]) for r in rows)
        info["activas"] = sum(int(r["n"]) for r in rows
                              if str(r.get("estado", "")).strip().upper().startswith("ACTIVA"))
    except Exception:  # noqa: BLE001
        pass
    try:
        probe = Socrata(DOMAIN, APP_TOKEN, timeout=25)
        where = " AND ".join(filtros_dep) or None
        r = probe.get(dataset_id, select=f"min({col_fecha}) AS mn, max({col_fecha}) AS mx",
                      where=where, limit=1)
        if r:
            mn, mx = str(r[0].get("mn")), str(r[0].get("mx"))
            if re.search(r"\d{4}", mn) and re.search(r"\d{4}", mx):
                info["ini"], info["fin"] = mn[:10], mx[:10]
    except Exception:  # noqa: BLE001
        pass
    return info


def resolver_pool_estaciones(filtros_dep: list[str], avanzados: dict[str, list[str]]) -> set[str]:
    """Resuelve el conjunto de codigos de estacion que cumplen los filtros avanzados."""
    clauses = [_a_catalogo(f) for f in filtros_dep]
    for attr_col, vals in avanzados.items():
        if not vals:
            continue
        c_cat = attr_col.replace("zonahidrografica", "zona_hidrografica")
        quoted = ", ".join("'" + str(v).upper() + "'" for v in vals)
        clauses.append(f"upper({c_cat}) IN ({quoted})")
    where = " AND ".join(clauses) or None
    rows = intentar(
        lambda: CLIENT.get(CATALOG_DATASET_ID, select="codigo", where=where, limit=50000),
        "pool estaciones",
    )
    return {r["codigo"] for r in (rows or []) if r.get("codigo")}


def construir_tareas(anio_ini, anio_fin, filtros_base, estaciones_pool, col_fecha):
    """Replica main.py paso 4: chunks de codigos (500) x años -> lista de tareas."""
    est_norm = []
    for c in estaciones_pool:
        est_norm.append(f"'{c}'")
        if len(str(c)) == 8:
            est_norm.append(f"'00{c}'")

    if est_norm:
        filtros_api = []
        for i in range(0, len(est_norm), 500):
            chunk = est_norm[i:i + 500]
            f_set = list(filtros_base) + [f"codigoestacion IN ({', '.join(chunk)})"]
            filtros_api.append(f_set)
    else:
        filtros_api = [list(filtros_base)] if filtros_base else [[]]

    if col_fecha and anio_ini and anio_fin:
        return [(a, None, f) for a in range(anio_ini, anio_fin + 1) for f in filtros_api]
    return [(None, None, f) for f in filtros_api]


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
    base_dir="data", include_csv=False, on_progress=None, query_info=None,
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
    # Algunos datasets especiales nombran distinto las columnas geográficas;
    # se crea el alias para que el export por carpetas (depto/municipio) funcione.
    for destino, alternos in (("departamento", ("nombre_del_departamento",)),
                              ("municipio", ("nombre_del_municipio",))):
        if destino not in df.columns:
            for alt in alternos:
                if alt in df.columns:
                    df[destino] = df[alt]
                    break
    raw = len(df)
    df, dups = deduplicate_observations(df, col_fecha or "fechaobservacion")
    outputs = export_by_department_municipality(df, var_nombre, base_dir=base_dir, include_csv=include_csv)
    total_csv = sum(len(o["csv"]) for o in outputs)
    reporte = write_coverage_report(
        df, var_nombre, base_dir, date_column=col_fecha,
        query_info=query_info, duplicates=dups,
    )

    return {
        "rows": len(df),
        "raw_rows": raw,
        "duplicates": dups,
        "files_parquet": len(outputs),
        "files_csv": total_csv,
        "output_dir": base_dir,
        "report": reporte,
        "seconds": round(time.time() - t0, 1),
    }
