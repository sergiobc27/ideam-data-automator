#!/usr/bin/env python3
"""Valida las curvas IDF de la plataforma contra curvas IDF OFICIALES (1-a-1).

Es la herramienta que cierra la brecha academica de la tesis: comparar la
intensidad I(D,Tr) que produce la plataforma contra la de una fuente oficial
(IDEAM / tesis universitarias) y reportar el error (MAPE).

USO ("para el clic"):
  1. Consigue las curvas IDF oficiales de >=10 estaciones (PDF del IDEAM en
     archivo.ideam.gov.co/curvas-idf, o tablas/coeficientes de tesis).
  2. Copia docs/validacion/idf-comparacion-PLANTILLA.csv y llena:
       - I_oficial_mmh    -> de la fuente oficial
       - I_plataforma_mmh -> del panel IDF de la web (ideam.sergiobc.com) para
                             esa estacion/duracion/Tr
     (Puedes llenar por partes: las filas con celdas vacias se omiten.)
  3. Corre:  python scripts/validar_idf.py mi-comparacion.csv
     Imprime el error relativo por fila y el MAPE por estacion, por duracion y
     global, con veredicto. Umbral publicable: MAPE < 15-20% (Journal of
     Hydrology). Sin dependencias externas (solo stdlib).

CSV (cabeceras exactas):
  estacion,duracion_min,Tr_anios,I_oficial_mmh,I_plataforma_mmh
"""
import csv
import sys
from collections import defaultdict

UMBRAL_EXCELENTE = 15.0
UMBRAL_PUBLICABLE = 20.0
CAMPOS = ["estacion", "duracion_min", "Tr_anios", "I_oficial_mmh", "I_plataforma_mmh"]


def error_relativo_pct(oficial, plataforma):
    """Error relativo porcentual |plataforma - oficial| / |oficial| * 100."""
    if oficial == 0:
        raise ValueError("I_oficial_mmh no puede ser 0 (division por cero en MAPE)")
    return abs(plataforma - oficial) / abs(oficial) * 100.0


def _mape(errores):
    return sum(errores) / len(errores) if errores else None


def compute_validation(rows):
    """rows: iterable de dicts con las cabeceras de CAMPOS.

    Devuelve {n, mape_global, mape_por_estacion, mape_por_duracion, detalle}.
    Omite filas sin I_oficial_mmh o I_plataforma_mmh (permite llenar por partes).
    """
    detalle = []
    por_estacion = defaultdict(list)
    por_duracion = defaultdict(list)
    for r in rows:
        of = r.get("I_oficial_mmh")
        pl = r.get("I_plataforma_mmh")
        if of in (None, "") or pl in (None, ""):
            continue
        of, pl = float(of), float(pl)
        e = error_relativo_pct(of, pl)
        detalle.append({
            "estacion": r.get("estacion", "?"),
            "duracion_min": r.get("duracion_min", "?"),
            "Tr_anios": r.get("Tr_anios", "?"),
            "I_oficial_mmh": of,
            "I_plataforma_mmh": pl,
            "error_rel_pct": e,
        })
        por_estacion[r.get("estacion", "?")].append(e)
        por_duracion[str(r.get("duracion_min", "?"))].append(e)
    return {
        "n": len(detalle),
        "mape_global": _mape([d["error_rel_pct"] for d in detalle]),
        "mape_por_estacion": {k: _mape(v) for k, v in por_estacion.items()},
        "mape_por_duracion": {k: _mape(v) for k, v in por_duracion.items()},
        "detalle": detalle,
    }


def veredicto(mape):
    if mape is None:
        return "SIN DATOS (llena el CSV)"
    if mape < UMBRAL_EXCELENTE:
        return f"EXCELENTE (MAPE {mape:.1f}% < {UMBRAL_EXCELENTE:.0f}%)"
    if mape < UMBRAL_PUBLICABLE:
        return f"PUBLICABLE (MAPE {mape:.1f}% < {UMBRAL_PUBLICABLE:.0f}%)"
    return (f"REVISAR (MAPE {mape:.1f}% >= {UMBRAL_PUBLICABLE:.0f}%): "
            "datos crudos no certificados? registro corto? distribucion?")


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main(argv):
    if len(argv) != 2:
        print("uso: python scripts/validar_idf.py <comparacion.csv>")
        return 2
    res = compute_validation(_read_csv(argv[1]))
    if res["n"] == 0:
        print("No hay filas completas. Llena I_oficial_mmh e I_plataforma_mmh.")
        return 1
    print(f"Filas comparadas: {res['n']}")
    print(f"MAPE global: {res['mape_global']:.2f}%  ->  {veredicto(res['mape_global'])}")
    print("\nMAPE por estacion:")
    for k, val in sorted(res["mape_por_estacion"].items()):
        print(f"  {k:24s} {val:6.2f}%")
    print("\nMAPE por duracion (min):")
    def _ord(kv):
        k = kv[0]
        return float(k) if k.replace(".", "", 1).isdigit() else float("inf")
    for k, val in sorted(res["mape_por_duracion"].items(), key=_ord):
        print(f"  {k:>8s} {val:6.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
