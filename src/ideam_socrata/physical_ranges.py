"""Saneo físico de observaciones (auditoría de datos 2026-06-15).

Marca como RECHAZADAS las lecturas físicamente imposibles (centinelas tipo
-9999, picos absurdos, unidades fuera de escala) antes de insertarlas en
`observaciones`. NO se borra el dato en la fuente: se aparta a la tabla
`observaciones_rechazos` con su motivo, de modo que el saneo es reversible y
auditable. Es CONSERVADOR: solo descarta lo claramente imposible; un valor raro
pero plausible se conserva.

Casos especiales (hallazgos de la auditoría):
- **Presión atmosférica (62tk-nxj5):** el rango plausible DEPENDE DE LA ALTITUD.
  Una estación en Bogotá (~2.600 m) marca ~750 hPa, no ~1.013. Se compara contra
  la presión esperada por la atmósfera estándar internacional (fórmula
  barométrica) usando `estaciones.altitud` ± tolerancia. Sin altitud conocida se
  usa un rango global ancho de respaldo (alta montaña → costa).
- **Nivel de río / mar:** vienen unidades mezcladas ('mt'/'M') y picos imposibles
  (cientos de "m"). Se aplica un techo de cordura en metros; NO se convierte de
  unidad sin confirmación del IDEAM (solo se aparta lo imposible).

Pensado para usarse vectorizado sobre el dataframe de staging (un dataset por
lote), pero `reject_reason()` también sirve escalar para tests.
"""

import math

import numpy as np
import pandas as pd

PRECIP_ID = "s54a-sgyg"
PRESSURE_ID = "62tk-nxj5"
RIVER_LEVEL_IDS = frozenset({"vfth-yucv", "bdmn-sqnh", "pt9a-aamx"})
SEA_LEVEL_IDS = frozenset({"ia8x-22em", "uxy3-jchf", "7z6g-yx9q"})

# Atmósfera estándar internacional (ISA) a nivel del mar.
_P0_HPA = 1013.25
_ISA_A = 2.25577e-5  # coeficiente de la fórmula barométrica ISA
_ISA_EXP = 5.25588
# Tolerancia de presión (hPa) alrededor del valor estándar por altitud: cubre la
# variación meteorológica (~±40), la desviación ISA-vs-clima real y un margen.
# El objetivo es cazar CORRUPCIÓN (centinelas, ceros, valores a nivel del mar en
# estaciones de páramo), no rechazar lecturas reales en el borde.
_PRESSURE_TOL_HPA = 80.0
# Respaldo sin altitud: rango global ancho. 300 hPa ≈ 9.000 m (por encima de
# cualquier estación andina); 1.085 hPa ≈ récord mundial a nivel del mar.
_PRESSURE_FALLBACK = (300.0, 1085.0)

# Niveles (río y mar) en metros: techo de cordura. Un río en crecida puede llegar
# a decenas de metros de cota sobre el cero de mira; >100 m es imposible. El cero
# de mira admite lecturas ligeramente negativas (estiaje), de ahí el piso.
_LEVEL_MIN_M = -50.0
_LEVEL_MAX_M = 100.0

# Rangos físicos simples [min, max] sobre la LECTURA cruda (WMO-No.8 CIMO Guide
# + récords mundiales, con margen para no rechazar extremos reales).
_SIMPLE_RANGES = {
    PRECIP_ID: (0.0, 150.0),       # precipitación mm en el intervalo (≥0; 150 muy holgado)
    "ccvq-rp9s": (-30.0, 55.0),    # temperatura máxima del aire °C
    "afdg-3zpb": (-30.0, 55.0),    # temperatura mínima del aire °C
    "uext-mhny": (0.0, 105.0),     # humedad relativa % (>105 imposible; 100-105 por calibración)
    "sgfv-3yp8": (0.0, 120.0),     # velocidad del viento m/s (huracán cat.5 ~90 m/s)
    "kiw7-v9ta": (0.0, 360.0),     # dirección del viento °
}


def expected_pressure_hpa(altitud_m):
    """Presión esperada por la atmósfera estándar internacional a una altitud (m)."""
    return _P0_HPA * (1.0 - _ISA_A * altitud_m) ** _ISA_EXP


def pressure_bounds(altitud_m):
    """(min, max) plausible de presión en hPa para una altitud. Sin altitud
    conocida (None/NaN), devuelve el rango global de respaldo."""
    if altitud_m is None or (isinstance(altitud_m, float) and not math.isfinite(altitud_m)):
        return _PRESSURE_FALLBACK
    exp = expected_pressure_hpa(altitud_m)
    return (exp - _PRESSURE_TOL_HPA, exp + _PRESSURE_TOL_HPA)


def reject_reason(dataset_id, valor, unidad=None, altitud=None):
    """Motivo de rechazo (str) si la lectura es físicamente imposible; None si es
    aceptable. `valor=None` (sin medición) NO es rechazo: es un hueco legítimo."""
    if valor is None:
        return None
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return "valor no numérico"
    if not math.isfinite(v):
        return "valor no finito"

    if dataset_id == PRESSURE_ID:
        lo, hi = pressure_bounds(altitud)
        if not (lo <= v <= hi):
            ref = "" if altitud is None else f" (altitud {altitud:.0f} m)"
            return f"presión {v:.1f} hPa fuera del rango por altitud [{lo:.0f}, {hi:.0f}]{ref}"
        return None

    if dataset_id in RIVER_LEVEL_IDS or dataset_id in SEA_LEVEL_IDS:
        if not (_LEVEL_MIN_M <= v <= _LEVEL_MAX_M):
            return f"nivel {v:.1f} m fuera del techo de cordura [{_LEVEL_MIN_M:.0f}, {_LEVEL_MAX_M:.0f}]"
        return None

    rng = _SIMPLE_RANGES.get(dataset_id)
    if rng is not None:
        lo, hi = rng
        if not (lo <= v <= hi):
            return f"{v} fuera del rango físico [{lo}, {hi}]"
    return None


def _norm_code(series):
    """Normaliza codigoestacion para casar con el catálogo (quita ceros a la
    izquierda; misma regla que la capa de consulta de la API)."""
    return series.astype("string").str.strip().str.lstrip("0")


def reject_motivos(frame, dataset_id, altitudes=None):
    """Serie de motivos de rechazo (str) / None por fila, VECTORIZADA.

    frame: dataframe de staging (debe tener `valorobservado`; para presión,
    `codigoestacion`). dataset_id: id único del lote. altitudes: dict
    codigo-normalizado -> altitud (m) para la presión.
    """
    n = len(frame)
    valor = pd.to_numeric(frame.get("valorobservado"), errors="coerce")
    present = frame.get("valorobservado").notna() if "valorobservado" in frame else pd.Series(False, index=frame.index)
    # No finito pero presente (ej. texto, inf): rechazo explícito.
    no_finito = present & ~np.isfinite(valor)

    motivos = pd.Series([None] * n, index=frame.index, dtype=object)
    motivos = motivos.mask(no_finito, "valor no numérico/no finito")
    # Solo evaluamos rango sobre valores presentes y finitos.
    evaluable = present & np.isfinite(valor)

    if dataset_id == PRESSURE_ID:
        altitudes = altitudes or {}
        codes = _norm_code(frame.get("codigoestacion", pd.Series([None] * n, index=frame.index)))
        alt = codes.map(altitudes).astype(float)
        exp = _P0_HPA * (1.0 - _ISA_A * alt) ** _ISA_EXP
        lo = np.where(alt.notna(), exp - _PRESSURE_TOL_HPA, _PRESSURE_FALLBACK[0])
        hi = np.where(alt.notna(), exp + _PRESSURE_TOL_HPA, _PRESSURE_FALLBACK[1])
        bad = evaluable & ((valor < lo) | (valor > hi))
        motivos = motivos.mask(bad, "presión fuera del rango por altitud")
        return motivos

    if dataset_id in RIVER_LEVEL_IDS or dataset_id in SEA_LEVEL_IDS:
        bad = evaluable & ((valor < _LEVEL_MIN_M) | (valor > _LEVEL_MAX_M))
        motivos = motivos.mask(bad, f"nivel fuera del techo de cordura [{_LEVEL_MIN_M:.0f}, {_LEVEL_MAX_M:.0f}] m")
        return motivos

    rng = _SIMPLE_RANGES.get(dataset_id)
    if rng is not None:
        lo, hi = rng
        bad = evaluable & ((valor < lo) | (valor > hi))
        motivos = motivos.mask(bad, f"valor fuera del rango físico [{lo}, {hi}]")
    return motivos


def split_frame(frame, dataset_id, altitudes=None):
    """Parte el frame de staging en (aceptado, rechazado).

    `rechazado` conserva todas las columnas de `frame` más una columna `motivo`.
    Si el dataset no tiene reglas, devuelve (frame, frame.iloc[0:0] + motivo).
    """
    motivos = reject_motivos(frame, dataset_id, altitudes)
    is_bad = motivos.notna()
    aceptado = frame.loc[~is_bad]
    rechazado = frame.loc[is_bad].copy()
    rechazado["motivo"] = motivos.loc[is_bad]
    return aceptado, rechazado
