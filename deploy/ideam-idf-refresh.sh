#!/bin/bash
# Refresco mensual de las curvas IDF: recalcula los máximos anuales móviles de
# las estaciones YA procesadas, para capturar el año en curso conforme el delta
# trae datos nuevos. Los máximos anuales cambian poco día a día, así que mensual
# (de madrugada, baja prioridad) es suficiente. Estaciones nuevas pluviográficas
# se incorporan con `idf_backfill.sh full`.
#
# AÑO EN CURSO = PROVISIONAL (auditoría datos-correctitud #6). idf_compute_station
# hace DELETE+reinsert de TODOS los años, así que el año en curso se recalcula con
# datos parciales en cada corrida. Dos salvaguardas ya acotan el efecto:
#   1) El gate anual p_min_obs (≈57% del año) impide que el año en curso ENTRE en
#      idf_max_anual hasta ~mes 7-8; antes de eso no afecta el ajuste.
#   2) Una vez dentro, el sensor dominante se elige por slots ACUMULADOS a la
#      fecha, así que su máximo puede OSCILAR (no monótonamente) entre refrescos
#      de la 2ª mitad del año, y solo en estaciones multi-sensor con completitud
#      pareja entre sensores (las mono-sensor son inmunes).
# Por eso el último año debe tratarse como PROVISIONAL: no compares una consulta
# de septiembre con una de noviembre esperando el mismo valor. El cierre completo
# (fijar/avisar el año provisional en /idf) queda como mejora de la API; aquí solo
# se deja constancia de la naturaleza provisional del recálculo del año abierto.
set -uo pipefail
docker exec ideam-pg psql -U ideam -d ideam -tAc \
  "SELECT codigoestacion FROM idf_estado ORDER BY computed_at" | grep . | while read -r code; do
  # Los códigos de estación del IDEAM son alfanuméricos; valida ANTES de
  # interpolar (defensa anti-inyección de 2º orden, aunque vengan de la DB).
  [[ "$code" =~ ^[A-Za-z0-9_-]+$ ]] || { logger -t ideam-idf-refresh "codigo invalido omitido: $code"; continue; }
  docker exec ideam-pg psql -U ideam -d ideam -tAc "SELECT idf_compute_station('$code');" >/dev/null 2>&1
done
logger -t ideam-idf-refresh "refresco IDF mensual completado"
