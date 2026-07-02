"""Dedup determinista (auditoria datos-correctitud #7).

Ante una colision intra-chunk del mismo (estacion, sensor, fecha) con distinto
valorobservado, deduplicate_observations debe conservar SIEMPRE el mismo valor
(el mayor), sin depender del orden de llegada del stream de Socrata.
"""

import pandas as pd

from ideam_socrata.transform import deduplicate_observations


def _chunk(valores):
    return pd.DataFrame({
        "codigoestacion": ["E1"] * len(valores),
        "codigosensor": ["0240"] * len(valores),
        "fechaobservacion": ["2024-01-01T00:00:00"] * len(valores),
        "valorobservado": valores,
    })


def test_colision_conserva_el_mayor_sin_importar_el_orden():
    # Mismo (estacion, sensor, fecha), valores 5.0 y 8.0 en AMBOS ordenes:
    # el resultado debe ser identico (8.0), no arbitrario.
    df_a, dups_a = deduplicate_observations(_chunk([5.0, 8.0]), "fechaobservacion")
    df_b, dups_b = deduplicate_observations(_chunk([8.0, 5.0]), "fechaobservacion")
    assert dups_a == 1 and dups_b == 1
    assert len(df_a) == 1 and len(df_b) == 1
    assert df_a["valorobservado"].iloc[0] == 8.0
    assert df_b["valorobservado"].iloc[0] == 8.0


def test_no_colapsa_sensores_ni_fechas_distintas():
    df = pd.DataFrame({
        "codigoestacion": ["E1", "E1", "E1"],
        "codigosensor": ["0240", "0257", "0240"],
        "fechaobservacion": ["2024-01-01T00:00:00", "2024-01-01T00:00:00",
                             "2024-01-01T00:10:00"],
        "valorobservado": [1.0, 2.0, 3.0],
    })
    out, dups = deduplicate_observations(df, "fechaobservacion")
    assert dups == 0
    assert len(out) == 3


def test_sin_columna_valor_sigue_deduplicando():
    # Sin valorobservado (datasets sin esa columna): el sort cae a la identidad y
    # el dedup por clave sigue funcionando.
    df = pd.DataFrame({
        "codigoestacion": ["E1", "E1"],
        "codigosensor": ["0240", "0240"],
        "fechaobservacion": ["2024-01-01T00:00:00", "2024-01-01T00:00:00"],
    })
    out, dups = deduplicate_observations(df, "fechaobservacion")
    assert dups == 1 and len(out) == 1
