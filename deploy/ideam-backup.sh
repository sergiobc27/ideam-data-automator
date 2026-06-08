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

mkdir -p "$DESTINO"

{
  docker exec "$CONTENEDOR" pg_dump -U ideam -d ideam --schema-only
  docker exec "$CONTENEDOR" pg_dump -U ideam -d ideam --data-only \
      --table=ingest_state --table=estaciones
} | gzip > "$ARCHIVO.tmp"
mv "$ARCHIVO.tmp" "$ARCHIVO"

TAMANO=$(du -h "$ARCHIVO" | cut -f1)
logger -t ideam-backup "backup OK: $ARCHIVO ($TAMANO)"

# Rotación: conservar 14 días
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
