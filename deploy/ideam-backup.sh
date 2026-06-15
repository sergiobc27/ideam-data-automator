#!/bin/bash
# Backup diario del espejo IDEAM — estrategia $0.
#
# El espejo (764M filas) es RE-DERIVABLE desde Socrata, así que NO se respalda
# la hypertable cruda: basta con lo irreemplazable y liviano:
#   1. ESQUEMA completo (tablas, hypertable, agregados, políticas) --schema-only
#   2. ingest_state  (el mapa de qué está cargado: permite reanudar/re-derivar)
#   3. estaciones    (catálogo dimensional, 18K filas)
# Total: unos pocos MB comprimidos. Rotación: últimos 14 días en /var/backups/ideam.
# Restauración: ver docs/RUNBOOK.md (recrear esquema + re-disparar backfill).
#
# Subida opcional a Oracle Object Storage (Always Free: 20 GB): configurar OCI
# CLI una vez (`oci setup config`) y definir OCI_BUCKET en /etc/ideam/ideam.env.
set -euo pipefail

DESTINO="/var/backups/ideam"
FECHA="$(date -u +%Y%m%d)"
ARCHIVO="$DESTINO/ideam_backup_$FECHA.sql.gz"
CONTENEDOR="ideam-pg"

# Tamaño mínimo plausible del dump de esquema (un esquema real pesa mucho más;
# por debajo de esto algo falló y no debemos publicar/rotar).
MIN_SCHEMA_BYTES=2048

mkdir -p "$DESTINO"

TMP_SCHEMA="$(mktemp)"
TMP_DATA="$(mktemp)"
trap 'rm -f "$TMP_SCHEMA" "$TMP_DATA" "$ARCHIVO.tmp"' EXIT

# OJO RESTAURACIÓN (TimescaleDB): este es un dump --schema-only + datos de 2
# tablas. Para restaurarlo en una BD nueva, ANTES de cargar el esquema:
#   CREATE EXTENSION IF NOT EXISTS timescaledb;
#   SELECT timescaledb_pre_restore();
# y AL TERMINAR de cargar:  SELECT timescaledb_post_restore();
# (sin esto, las hypertables/agregados no se restauran limpio). Ver docs/RUNBOOK.md.

# 1) ESQUEMA completo (tablas, hypertables, agregados, políticas). Con set -e,
#    si pg_dump falla el script aborta aquí (sin el enmascaramiento del antiguo
#    grupo `{ ... } | gzip`, donde un fallo del primer dump pasaba inadvertido).
docker exec "$CONTENEDOR" pg_dump -U ideam -d ideam --schema-only > "$TMP_SCHEMA"

# 2) Datos irreemplazables: ingest_state (mapa de carga) + estaciones (catálogo).
docker exec "$CONTENEDOR" pg_dump -U ideam -d ideam --data-only \
    --table=ingest_state --table=estaciones > "$TMP_DATA"

# Sanidad: cada parte debe tener contenido plausible antes de empaquetar.
if [ "$(wc -c < "$TMP_SCHEMA")" -lt "$MIN_SCHEMA_BYTES" ]; then
  logger -t ideam-backup "ERROR: dump de esquema vacío/sospechoso (<${MIN_SCHEMA_BYTES}B); aborto sin rotar"
  exit 1
fi
if [ ! -s "$TMP_DATA" ]; then
  logger -t ideam-backup "ERROR: dump de datos vacío; aborto sin rotar"
  exit 1
fi

cat "$TMP_SCHEMA" "$TMP_DATA" | gzip > "$ARCHIVO.tmp"

# Verificar integridad del .gz ANTES de publicarlo y ANTES de rotar.
if ! gzip -t "$ARCHIVO.tmp"; then
  logger -t ideam-backup "ERROR: el backup no pasó gzip -t; aborto sin rotar"
  exit 1
fi

mv "$ARCHIVO.tmp" "$ARCHIVO"

TAMANO=$(du -h "$ARCHIVO" | cut -f1)
logger -t ideam-backup "backup OK: $ARCHIVO ($TAMANO)"

# Rotación: conservar 14 días. Solo se llega aquí si el backup de hoy quedó
# verificado, así que una racha de fallos NO erosiona la ventana de retención.
find "$DESTINO" -name 'ideam_backup_*.sql.gz' -mtime +14 -delete

# --- Subida opcional a Oracle Object Storage (Always Free) ---
# Requiere: oci setup config (una vez) y OCI_BUCKET en el entorno.
if [ -n "${OCI_BUCKET:-}" ] && command -v oci >/dev/null 2>&1; then
  if oci os object put --bucket-name "$OCI_BUCKET" --file "$ARCHIVO" \
       --name "backups/$(basename "$ARCHIVO")" --force >/dev/null 2>&1; then
    logger -t ideam-backup "subido a Object Storage: $OCI_BUCKET"
  else
    logger -t ideam-backup "ADVERTENCIA: fallo la subida a Object Storage (el backup local existe)"
  fi
fi
