#!/bin/bash
# Refresco mensual de las curvas IDF: recalcula los máximos anuales móviles de
# las estaciones YA procesadas, para capturar el año en curso conforme el delta
# trae datos nuevos. Los máximos anuales cambian poco día a día, así que mensual
# (de madrugada, baja prioridad) es suficiente. Estaciones nuevas pluviográficas
# se incorporan con `idf_backfill.sh full`.
set -u
docker exec ideam-pg psql -U ideam -d ideam -tAc \
  "SELECT codigoestacion FROM idf_estado ORDER BY computed_at" | grep . | while read -r code; do
  docker exec ideam-pg psql -U ideam -d ideam -tAc "SELECT idf_compute_station('$code');" >/dev/null 2>&1
done
logger -t ideam-idf-refresh "refresco IDF mensual completado"
