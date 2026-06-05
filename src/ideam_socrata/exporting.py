import re
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import EXCEL_MAX_ROWS


def safe_path_part(value, fallback="SIN_DATO"):
    """Create a Windows-safe folder/file segment while preserving readable names."""
    text = fallback if value is None or str(value).strip() == "" else str(value).strip()
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    return text.strip("._ ") or fallback


def export_timestamp(now=None):
    """Return hhmm_ddmmyy timestamp for exported filenames."""
    return (now or datetime.now()).strftime("%H%M_%d%m%y")


def split_csv_by_excel_limit(df, output_base_path, max_rows=EXCEL_MAX_ROWS):
    """Write CSV files split below Excel's row limit. Header counts as one row."""
    max_data_rows = max(1, max_rows - 1)
    output_paths = []

    for idx, start in enumerate(range(0, len(df), max_data_rows), start=1):
        suffix = "" if idx == 1 else f"_{idx}"
        output_path = output_base_path.with_name(f"{output_base_path.stem}{suffix}{output_base_path.suffix}")
        # date_format sin la 'T': Excel lo reconoce como fecha y permite
        # filtrar/ordenar cronologicamente (no como texto).
        df.iloc[start:start + max_data_rows].to_csv(
            output_path, index=False, encoding="utf-8-sig",
            date_format="%Y-%m-%d %H:%M:%S",
        )
        output_paths.append(output_path)

    return output_paths


def write_coverage_report(df, variable_name, base_dir, date_column=None,
                          query_info=None, duplicates=0, timestamp=None):
    """Escribe RESUMEN_<variable>_<stamp>.txt con la cobertura real de la descarga.

    Incluye rango real de fechas, filas por estación con primera/última
    observación y completitud mensual (% de meses del rango con >=1 dato).
    Responde de antemano preguntas tipo '¿por qué solo hay datos desde 2016?':
    la cobertura depende de cuándo se instalaron las estaciones automáticas.
    """
    base_path = Path(base_dir)
    base_path.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or export_timestamp()
    variable_part = safe_path_part(variable_name, "variable").lower()
    report_path = base_path / f"RESUMEN_{variable_part}_{stamp}.txt"

    lineas = [
        "=" * 78,
        f"RESUMEN DE DESCARGA — {variable_name}",
        f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')} · IDEAM Data Automator",
        "=" * 78,
        "",
    ]
    for clave, valor in (query_info or {}).items():
        lineas.append(f"{clave}: {valor}")

    lineas.append(f"Filas únicas: {len(df):,}"
                  + (f"  ({duplicates:,} duplicados depurados)" if duplicates else ""))

    fechas = None
    if date_column and date_column in df.columns:
        fechas = pd.to_datetime(df[date_column], errors="coerce")
        if fechas.notna().any():
            lineas.append(
                f"Rango real de los datos: {fechas.min():%Y-%m-%d} — {fechas.max():%Y-%m-%d}")

    lineas.append("")
    if "codigoestacion" in df.columns and fechas is not None and fechas.notna().any():
        lineas += ["COBERTURA POR ESTACIÓN", "-" * 78]
        grupo = df.assign(_fecha=fechas).groupby("codigoestacion", dropna=False)
        for codigo, g in grupo:
            nombre = str(g["nombreestacion"].iloc[0])[:30] if "nombreestacion" in g.columns else ""
            muni = str(g["municipio"].iloc[0])[:18] if "municipio" in g.columns else ""
            f = g["_fecha"].dropna()
            if f.empty:
                lineas.append(f"{codigo} | {nombre:30} | {muni:18} | {len(g):>10,} filas | sin fechas")
                continue
            meses_con_dato = f.dt.to_period("M").nunique()
            meses_rango = max(1, (f.max().to_period("M") - f.min().to_period("M")).n + 1)
            completitud = 100.0 * meses_con_dato / meses_rango
            lineas.append(
                f"{codigo} | {nombre:30} | {muni:18} | {len(g):>10,} filas | "
                f"{f.min():%Y-%m-%d} → {f.max():%Y-%m-%d} | {completitud:5.1f}% de meses con dato"
            )
        lineas += [
            "-" * 78,
            "Nota: la cobertura inicia cuando se instaló cada estación automática;",
            "la data histórica de estaciones convencionales no está en datos.gov.co (vive en DHIME).",
        ]

    report_path.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return str(report_path)


def export_by_department_municipality(
    df,
    variable_name,
    base_dir="data",
    include_csv=False,
    timestamp=None,
    max_csv_rows=EXCEL_MAX_ROWS,
):
    """Export rows under data/departamento/municipio with deterministic names."""
    base_path = Path(base_dir)
    stamp = timestamp or export_timestamp()
    outputs = []

    if df.empty:
        return outputs

    dept_col = "departamento" if "departamento" in df.columns else None
    muni_col = "municipio" if "municipio" in df.columns else None

    group_cols = [col for col in (dept_col, muni_col) if col]
    grouped = [((), df)] if not group_cols else df.groupby(group_cols, dropna=False, sort=True)

    for keys, group_df in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)

        department = keys[0] if dept_col else "SIN_DEPARTAMENTO"
        municipality = keys[1] if len(keys) > 1 else "SIN_MUNICIPIO"

        department_part = safe_path_part(department, "SIN_DEPARTAMENTO")
        municipality_part = safe_path_part(municipality, "SIN_MUNICIPIO")
        variable_part = safe_path_part(variable_name, "variable").lower()

        folder = base_path / department_part / municipality_part
        folder.mkdir(parents=True, exist_ok=True)

        filename_base = f"{variable_part}_{department_part.lower()}_{municipality_part.lower()}_{stamp}"
        parquet_path = folder / f"{filename_base}.parquet"
        group_df.to_parquet(parquet_path, index=False)

        csv_paths = []
        if include_csv:
            csv_paths = split_csv_by_excel_limit(group_df, folder / f"{filename_base}.csv", max_csv_rows)

        outputs.append(
            {
                "department": str(department),
                "municipality": str(municipality),
                "rows": len(group_df),
                "parquet": str(parquet_path),
                "csv": [str(path) for path in csv_paths],
            }
        )

    return outputs
