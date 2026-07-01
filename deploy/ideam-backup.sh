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
# Alerta de offsite: definir HC_BACKUP_URL (check "ideam-backup" en
# healthchecks.io) en /etc/ideam/ideam.env; ver el bloque de subida abajo.
set -euo pipefail

DESTINO="/var/backups/ideam"
FECHA="$(date -u +%Y%m%d)"
ARCHIVO="$DESTINO/ideam_backup_$FECHA.sql.gz"
# Nombre del contenedor Postgres: una sola fuente de verdad, la variable
# PG_CONTAINER de /etc/ideam/ideam.env (linea: PG_CONTAINER=ideam-pg). El
# default coincide con el contenedor real del box (`docker ps`) y con el
# `docker run --name ideam-pg` del procedimiento E de docs/RUNBOOK.md.
CONTENEDOR="${PG_CONTAINER:-ideam-pg}"

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
# Con un usuario IAM de MINIMO PRIVILEGIO (recomendado, en vez de la API key de
# Administrator): definir tambien OCI_PROFILE (perfil en ~/.oci/config) y
# OCI_NAMESPACE en el entorno; el usuario limitado no puede auto-descubrir el
# namespace, asi que hay que pasarlo explicito. Sin esas vars, usa el perfil
# DEFAULT y auto-descubre el namespace (comportamiento anterior).
#
# Alerta accionable (auditoria 2026-07-01): un fallo u omision de la copia
# offsite dejaba solo un renglon en syslog; backup y DB compartian destino sin
# que nadie se enterara. Ahora se pingea healthchecks.io (mismo patron ping_hc
# de ideam-healthcheck.sh) via HC_BACKUP_URL en /etc/ideam/ideam.env:
#   exito  -> HC_BACKUP_URL        (check al dia)
#   fallo  -> HC_BACKUP_URL/fail   (alerta por email, con mensaje corto)
# Sin HC_BACKUP_URL definida solo queda el logger (comportamiento anterior).
# El backup LOCAL ya quedo verificado y rotado llegados aqui: un fallo del
# offsite NUNCA invalida el backup local ni el exit 0 del script.
ping_backup_hc() {  # $1=sufijo ('' exito, '/fail' fallo)  $2=mensaje corto
  [ -n "${HC_BACKUP_URL:-}" ] && curl -fsS -m 10 --retry 2 -o /dev/null \
    --data-raw "${2:-}" "${HC_BACKUP_URL}$1" || true
}

if [ -n "${OCI_BUCKET:-}" ] && command -v oci >/dev/null 2>&1; then
  if oci os object put ${OCI_PROFILE:+--profile "$OCI_PROFILE"} ${OCI_NAMESPACE:+--namespace "$OCI_NAMESPACE"} \
       --bucket-name "$OCI_BUCKET" --file "$ARCHIVO" \
       --name "backups/$(basename "$ARCHIVO")" --force >/dev/null 2>&1; then
    logger -t ideam-backup "subido a Object Storage: $OCI_BUCKET"
    ping_backup_hc "" "backup $FECHA OK: local + offsite ($OCI_BUCKET)"
  else
    logger -t ideam-backup "ADVERTENCIA: fallo la subida a Object Storage (el backup local existe)"
    ping_backup_hc "/fail" "fallo subida offsite a $OCI_BUCKET; backup local OK: $ARCHIVO"
  fi
else
  # Antes este caso se omitia en SILENCIO y el backup quedaba solo en el mismo
  # disco que la DB (perder la caja = perder ambos). Dejar rastro y alertar.
  logger -t ideam-backup "ADVERTENCIA: sin copia offsite (OCI_BUCKET no configurado u oci CLI ausente)"
  ping_backup_hc "/fail" "sin copia offsite (OCI_BUCKET u oci CLI ausentes); backup local OK: $ARCHIVO"
fi
