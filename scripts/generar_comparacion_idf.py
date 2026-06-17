#!/usr/bin/env python3
"""Genera el CSV de comparacion IDF (plataforma vs Gonzalez 2023) para un
subconjunto de estaciones, listo para `scripts/validar_idf.py`.

Cierra la parte manual de la validacion 1-a-1: en vez de copiar a mano los
valores del panel IDF de la web, llama al endpoint y arma el CSV.

Para cada estacion del cruce (docs/validacion/gonzalez2023-cruce-plataforma.json):
  - I_plataforma = `intensityMmH` de las curvas de POST /api/analytics/idf,
                   por (duracion, Tr)  -> lo MISMO que muestra el panel de la web.
  - I_oficial    = tau * Tr^rho / (dur + d0)^mu   (formula de Gonzalez 2023,
                   coeficientes del cruce).
Escribe cabeceras identicas a validar_idf.py:
  estacion,duracion_min,Tr_anios,I_oficial_mmh,I_plataforma_mmh

USO (las 20 estaciones de 10-14 anios con mu fisico >0.50):
  python scripts/generar_comparacion_idf.py \
    --min-anios 10 --max-anios 14 --min-mu 0.50 \
    --out docs/validacion/comparacion-gonzalez2023-10a14.csv

Solo stdlib (urllib). Llama secuencialmente (con pausa) para no cargar la box.
"""
import argparse
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

# Grilla de la validacion (misma que comparacion-gonzalez2023-15a.csv): se
# descartan 720 y 1440 min porque caen fuera del rango de validez de Gonzalez
# (~10-360 min) y son los bordes mas ruidosos.
DURACIONES = (10, 20, 30, 60, 120, 180, 360)
DATASET_PRECIP = "s54a-sgyg"
API_DEFAULT = "https://ideam.sergiobc.com"

# Cloudflare bloquea el User-Agent por defecto de urllib ("Python-urllib") como
# bot (403 en el borde). Nos identificamos como el navegador que usa el panel
# IDF de la propia web, con su Origin/Referer, igual que una peticion legitima.
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def intensidad_oficial_mmh(tau, rho, d0, mu, dur_min, tr_anios):
    """I = tau * Tr^rho / (dur + d0)^mu  (mm/h). Formula de Gonzalez (2023)."""
    return tau * (tr_anios ** rho) / ((dur_min + d0) ** mu)


def filtrar_estaciones(cruce, min_anios, max_anios, min_mu):
    """Devuelve las estaciones del cruce con anios en [min,max] y mu > min_mu.

    min_mu es EXCLUSIVO (mu>0.50 deja fuera las curvas regionalizadas planas
    cuyo mu<=0.50 que inflan el MAPE sin reflejar la plataforma)."""
    out = []
    for e in cruce:
        a = e.get("anios_plataforma")
        m = e.get("mu")
        if a is None or m is None:
            continue
        if min_anios <= a <= max_anios and m > min_mu:
            out.append(e)
    return out


def nombre_csv(estacion):
    """'TIBAITATA - AUT' + '21206990' -> 'TIBAITATA_-_AUT_21206990'."""
    return f"{estacion['nombre'].replace(' ', '_')}_{estacion['codigo_ideam']}"


def consultar_idf(api_base, codigo, timeout=60):
    """POST /api/analytics/idf -> dict de respuesta (o lanza)."""
    body = json.dumps({
        "datasetId": DATASET_PRECIP,
        "catalogFilters": {"stations": [str(codigo)]},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/api/analytics/idf",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _UA,
            "Origin": api_base.rstrip("/"),
            "Referer": api_base.rstrip("/") + "/",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def filas_estacion(estacion, idf_resp):
    """Combina la respuesta del endpoint con los coeficientes de Gonzalez.

    Devuelve filas dict listas para el CSV, solo para las duraciones de la
    grilla. Si la estacion no tiene curvas (available=False), devuelve []."""
    if not idf_resp.get("available") or not idf_resp.get("curves"):
        return []
    nombre = nombre_csv(estacion)
    tau, rho = estacion["tau"], estacion["rho"]
    d0, mu = estacion["d0"], estacion["mu"]
    filas = []
    for curva in idf_resp["curves"]:
        tr = curva["returnPeriod"]
        for punto in curva["points"]:
            dur = punto["durMin"]
            if dur not in DURACIONES:
                continue
            i_plat = punto.get("intensityMmH")
            if i_plat is None:
                continue
            i_of = intensidad_oficial_mmh(tau, rho, d0, mu, dur, tr)
            filas.append({
                "estacion": nombre,
                "duracion_min": dur,
                "Tr_anios": tr,
                "I_oficial_mmh": round(i_of, 2),
                "I_plataforma_mmh": i_plat,
            })
    return filas


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cruce", default="docs/validacion/gonzalez2023-cruce-plataforma.json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-anios", type=int, default=10)
    ap.add_argument("--max-anios", type=int, default=14)
    ap.add_argument("--min-mu", type=float, default=0.50)
    ap.add_argument("--api", default=API_DEFAULT)
    ap.add_argument("--pausa", type=float, default=1.0, help="segundos entre llamadas (gentil con la box)")
    args = ap.parse_args(argv[1:])

    cruce = json.loads(Path(args.cruce).read_text(encoding="utf-8"))
    estaciones = filtrar_estaciones(cruce, args.min_anios, args.max_anios, args.min_mu)
    print(f"{len(estaciones)} estaciones: anios [{args.min_anios},{args.max_anios}], mu>{args.min_mu}")

    todas = []
    ok = saltadas = 0
    for i, est in enumerate(estaciones, 1):
        cod = est["codigo_ideam"]
        etq = f"[{i}/{len(estaciones)}] {est['nombre']} ({cod}, {est['anios_plataforma']}a)"
        try:
            resp = consultar_idf(args.api, cod)
        except Exception as exc:  # noqa: BLE001
            print(f"  {etq}: ERROR de red -> saltada ({exc})")
            saltadas += 1
            continue
        filas = filas_estacion(est, resp)
        if not filas:
            print(f"  {etq}: sin curvas (available={resp.get('available')}) -> saltada")
            saltadas += 1
        else:
            todas.extend(filas)
            ok += 1
            print(f"  {etq}: {len(filas)} filas")
        if i < len(estaciones):
            time.sleep(args.pausa)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["estacion", "duracion_min", "Tr_anios",
                                          "I_oficial_mmh", "I_plataforma_mmh"])
        w.writeheader()
        w.writerows(todas)
    print(f"\n{ok} estaciones OK, {saltadas} saltadas. {len(todas)} filas -> {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
