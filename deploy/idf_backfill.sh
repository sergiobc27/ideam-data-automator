#!/bin/bash
# Precómputo IDF: calcula los máximos anuales móviles por estación pluviográfica.
# Idempotente y reanudable: salta las que ya están en idf_estado.
# Uso:
#   idf_backfill.sh muestra   -> top N por nº de observaciones (rápido, ver IDF ya)
#   idf_backfill.sh full      -> TODAS las sub-horarias pendientes (~horas)
# Corre con baja prioridad (nice/ionice) para no competir con la API.
set -u
MODE="${1:-muestra}"
SAMPLE_N="${2:-30}"
PSQL="docker exec ideam-pg psql -U ideam -d ideam -tAc"

if [ "$MODE" = "muestra" ]; then
  # Top N estaciones de precipitación por volumen (desde mv_catalogo, instantáneo)
  # que aún no estén calculadas. Las más completas = mejores para IDF.
  CODES=$($PSQL "
    SELECT codigoestacion FROM (
      SELECT codigoestacion, sum(total) AS t FROM mv_catalogo
      WHERE source_dataset_id='s54a-sgyg' GROUP BY 1
    ) s
    WHERE codigoestacion NOT IN (SELECT codigoestacion FROM idf_estado)
    ORDER BY t DESC LIMIT $SAMPLE_N;")
else
  # Todas las sub-horarias (>20k obs/año en promedio) pendientes.
  CODES=$($PSQL "
    SELECT codigoestacion FROM (
      SELECT codigoestacion, count(*)::float / nullif(count(DISTINCT date_trunc('year', fechaobservacion)),0) AS opa
      FROM observaciones WHERE source_dataset_id='s54a-sgyg' GROUP BY 1
    ) s
    WHERE opa > 20000 AND codigoestacion NOT IN (SELECT codigoestacion FROM idf_estado)
    ORDER BY opa DESC;")
fi

TOTAL=$(echo "$CODES" | grep -c .)
echo "[$(date -u +%H:%M:%S)] IDF backfill modo=$MODE estaciones=$TOTAL"
i=0
for code in $CODES; do
  i=$((i+1))
  # Valida el código ANTES de interpolarlo en SQL (defensa anti-inyección de 2º
  # orden: viene de mv_catalogo/idf_estado, pero los códigos del IDEAM son
  # alfanuméricos y cualquier cosa fuera de eso se omite).
  if ! [[ "$code" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "[$(date -u +%H:%M:%S)] ($i/$TOTAL) codigo invalido omitido: $code"
    continue
  fi
  t0=$(date +%s)
  anios=$(docker exec ideam-pg psql -U ideam -d ideam -tAc "SELECT idf_compute_station('$code');" 2>&1)
  echo "[$(date -u +%H:%M:%S)] ($i/$TOTAL) $code -> $anios años ($(($(date +%s)-t0))s)"
done
echo "[$(date -u +%H:%M:%S)] IDF backfill $MODE COMPLETO"
