#!/usr/bin/env bash
# ============================================================
# descargar-bulk.sh   (en el box: /opt/ideam/bulk/descargar.sh)
# ------------------------------------------------------------
# Descarga por COLA los exports masivos de Socrata (.csv.gz)
# para el primer arranque / reconstruccion, cuando bajar via la
# API paginada del backfill seria demasiado lento. Cada dataset
# se baja como CSV comprimido directo del endpoint de export.
#
# Robustez:
#   - Reintentos por archivo (curl --retry + bucle externo).
#   - Verificacion de integridad con `gzip -t` (descarta y
#     reintenta los .gz corruptos / truncados).
#   - Reanudable: si el .gz final ya existe y pasa gzip -t, se
#     salta. Las descargas van a .part y solo se renombran al
#     verificarse OK.
#
# Tras bajar, se cargan con el loader COPY del backfill; este
# script SOLO baja y verifica. La carga a Postgres la hace el
# pipeline normal (ver docs/RUNBOOK.md, procedimiento E).
#
# INSTALACION:
#   sudo install -m 755 deploy/descargar-bulk.sh /opt/ideam/bulk/descargar.sh
#   sudo /opt/ideam/bulk/descargar.sh            # baja la cola completa
#
# Requiere: curl, gzip. Lee SOCRATA_DOMAIN y SOCRATA_APP_TOKEN
# de /etc/ideam/ideam.env si existe (token opcional pero sube
# el rate limit de Socrata).
# ============================================================
set -euo pipefail

ENV_FILE="/etc/ideam/ideam.env"
OUT_DIR="${BULK_DIR:-/opt/ideam/bulk}"
DOMAIN="${SOCRATA_DOMAIN:-www.datos.gov.co}"
MAX_INTENTOS=5

# Cargar env del box si esta presente (no obligatorio).
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$ENV_FILE"; set +a
fi

# Cola de datasets Socrata (id 4x4). Editar segun necesidad.
DATASETS=(
    s54a-sgyg   # precipitacion
    sbwg-7ju4   # temperatura
    ia8x-22em   # nivel
    n6vw-vkfe   # caudal
    ku6w-3rnf   # humedad relativa
)

mkdir -p "$OUT_DIR"
log() { logger -t ideam-bulk -s "$*"; }

# URL de export CSV de Socrata. El token va como query param.
url_de() {
    local id="$1"
    local u="https://${DOMAIN}/api/views/${id}/rows.csv?accessType=DOWNLOAD"
    if [[ -n "${SOCRATA_APP_TOKEN:-}" ]]; then
        u="${u}&\$\$app_token=${SOCRATA_APP_TOKEN}"
    fi
    printf '%s' "$u"
}

descargar_uno() {
    local id="$1"
    local final="${OUT_DIR}/${id}.csv.gz"
    local parte="${final}.part"

    # Ya bajado y valido -> saltar.
    if [[ -f "$final" ]] && gzip -t "$final" 2>/dev/null; then
        log "SKIP ${id}: ya existe y pasa gzip -t"
        return 0
    fi

    local url; url="$(url_de "$id")"
    local intento=1
    while (( intento <= MAX_INTENTOS )); do
        log "GET ${id} (intento ${intento}/${MAX_INTENTOS})"
        # --compressed: Socrata sirve gzip en transito; curl lo guarda
        # ya comprimido cuando combinamos con -H "Accept-Encoding: gzip".
        if curl -sS --fail --location \
                --connect-timeout 30 --max-time 7200 \
                --retry 3 --retry-delay 10 \
                -H "Accept-Encoding: gzip" \
                -o "$parte" "$url"; then
            # Verificar integridad del gzip descargado.
            if gzip -t "$parte" 2>/dev/null; then
                mv -f "$parte" "$final"
                log "OK ${id}: verificado ($(du -h "$final" | cut -f1))"
                return 0
            else
                log "CORRUPTO ${id}: gzip -t fallo, descarto y reintento"
                rm -f "$parte"
            fi
        else
            log "FALLO curl ${id} (intento ${intento})"
            rm -f "$parte"
        fi
        intento=$(( intento + 1 ))
        sleep $(( intento * 15 ))
    done

    log "ERROR ${id}: agotados ${MAX_INTENTOS} intentos"
    return 1
}

fallidos=0
for ds in "${DATASETS[@]}"; do
    descargar_uno "$ds" || fallidos=$(( fallidos + 1 ))
done

if (( fallidos > 0 )); then
    log "Cola terminada con ${fallidos} dataset(s) fallido(s)"
    exit 1
fi
log "Cola de descarga bulk completada sin errores"
