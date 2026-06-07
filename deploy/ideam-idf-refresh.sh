#!/bin/bash
# Refresco mensual de las curvas IDF: recalcula los máximos anuales móviles de
# las estaciones YA procesadas, para capturar el año en curso conforme el delta
# trae datos nuevos. Los máximos anuales cambian poco día a día, así que mensual
# (de madrugada, baja prioridad) es suficiente. Estaciones nuevas pluviográficas
# se incorporan con `idf_backfill.sh full`.
set -uo pipefail
docker exec ideam-pg psql -U ideam -d ideam -tAc \
  "SELECT codigoestacion FROM idf_estado ORDER BY computed_at" | grep . | while read -r code; do
  # Los códigos de estación del IDEAM son alfanuméricos; valida ANTES de
  # interpolar (defensa anti-inyección de 2º orden, aunque vengan de la DB).
  [[ "$code" =~ ^[A-Za-z0-9_-]+$ ]] || { logger -t ideam-idf-refresh "codigo invalido omitido: $code"; continue; }
  docker exec ideam-pg psql -U ideam -d ideam -tAc "SELECT idf_compute_station('$code');" >/dev/null 2>&1
done
logger -t ideam-idf-refresh "refresco IDF mensual completado"
