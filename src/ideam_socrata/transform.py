import hashlib
import logging
import unicodedata

import pandas as pd

logger = logging.getLogger(__name__)


def dataframe_memory_mb(df):
    """Return the deep memory footprint of a dataframe in MiB."""
    return float(df.memory_usage(deep=True).sum() / (1024 * 1024))


def _stable_hash(parts):
    raw = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_label(value):
    """Normalize labels for case/accent-insensitive comparisons."""
    text = "" if value is None else str(value).strip().upper()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def add_floating_id(df, dataset_id, col_fecha):
    """Add a deterministic upsert key independent of Socrata source row ids."""
    if df.empty:
        df["floating_id"] = []
        return df

    codigo = df["codigoestacion"].astype(str) if "codigoestacion" in df.columns else pd.Series([""] * len(df), index=df.index)
    sensor = df["codigosensor"].astype(str) if "codigosensor" in df.columns else pd.Series([""] * len(df), index=df.index)
    if col_fecha in df.columns:
        serie_fecha = df[col_fecha]
        if pd.api.types.is_datetime64_any_dtype(serie_fecha):
            # Mismo formato ISO-T que producia la version string: los hashes
            # historicos (DB) dependen de el y NO debe cambiar.
            fecha = serie_fecha.dt.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            fecha = serie_fecha.astype(str)
    else:
        fecha = pd.Series([""] * len(df), index=df.index)
    df["floating_id"] = [
        _stable_hash((dataset_id, codigo, cod_sensor, fecha_obs))
        for codigo, cod_sensor, fecha_obs in zip(codigo, sensor, fecha)
    ]
    return df


def normalize_chunk(data, dataset_id, col_fecha="fechaobservacion", dict_reemplazo=None):
    """Normalize one Socrata page into typed, payload-ready dataframe rows.

    Accepts a list of records (JSON path) or an existing DataFrame (CSV path).
    """
    df = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame.from_records(data)
    if df.empty:
        return df

    if ":id" in df.columns:
        df.drop(columns=[":id"], inplace=True)

    if dict_reemplazo and "departamento" in df.columns:
        normalized_replacements = {
            normalize_label(key): value for key, value in dict_reemplazo.items()
        }
        df["departamento"] = df["departamento"].apply(
            lambda value: normalized_replacements.get(normalize_label(value), value)
        )

    for col in ("valorobservado", "latitud", "longitud"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if col_fecha and col_fecha in df.columns:
        # Fecha REAL (datetime64), no texto: Parquet guarda timestamp nativo y
        # el CSV se escribe en formato que Excel reconoce como fecha (ver exporting).
        df[col_fecha] = pd.to_datetime(df[col_fecha], errors="coerce")

    df["source_dataset_id"] = dataset_id
    add_floating_id(df, dataset_id, col_fecha)

    logger.debug(
        "Chunk normalizado dataset=%s rows=%s memory_mb=%.2f",
        dataset_id,
        len(df),
        dataframe_memory_mb(df),
    )
    return df


def parse_export_dates(serie):
    """Fechas del export masivo de Socrata (formato US, ej. 11/15/2024 10:20:00 PM).

    Parseo con formato explicito (rapido) y fallback general para valores mixtos.
    """
    parsed = pd.to_datetime(serie, format="%m/%d/%Y %I:%M:%S %p", errors="coerce")
    mask = parsed.isna() & serie.notna()
    if mask.any():
        parsed.loc[mask] = pd.to_datetime(serie.loc[mask], errors="coerce")
    return parsed


def deduplicate_observations(df, date_column):
    """Deduplicate observations with sensor-aware keys when available."""
    if "codigoestacion" not in df.columns or date_column not in df.columns:
        return df, 0

    before = len(df)
    dedup_cols = ["codigoestacion", date_column]
    if "codigosensor" in df.columns:
        dedup_cols.insert(1, "codigosensor")
    df = df.drop_duplicates(subset=dedup_cols, keep="last")
    return df, before - len(df)
