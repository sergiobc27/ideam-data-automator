#!/usr/bin/env bash
# ============================================================
# ideam-watchdog.sh
# ------------------------------------------------------------
# Detecta y recupera un backfill ATASCADO (proceso vivo pero
# sin avanzar). El backfill historico es de larga duracion y a
# veces se cuelga en una request Socrata sin morir: systemd lo
# ve "active" y Restart=on-failure NO dispara porque no hubo
# fallo. Este script suple ese hueco.
#
# Heuristica: se considera atascado si TODO esto es cierto:
#   1. ideam-backfill esta 'active' o 'activating'.
#   2. Lleva > 3600s (1h) sin escribir una linea nueva al journal.
#   3. NO hay ningun /opt/ideam/raw/*.part modificado en los
#      ultimos 60 min (no se esta descargando un chunk a disco).
# Si las 3 se cumplen -> systemctl restart ideam-backfill.
# El restart es seguro: el backfill es reanudable (tabla
# ingest_state), los (dataset, anio) en 'done' se saltan.
#
# Se ejecuta via ideam-watchdog.timer (cada 15 min).
#
# INSTALACION:
#   sudo install -m 755 deploy/ideam-watchdog.sh /usr/local/bin/ideam-watchdog.sh
#   sudo install -m 644 deploy/ideam-watchdog.service /etc/systemd/system/
#   sudo install -m 644 deploy/ideam-watchdog.timer   /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now ideam-watchdog.timer
#
# Ver actividad:  journalctl -t ideam-watchdog
# ============================================================
set -euo pipefail

UNIT="ideam-backfill.service"
RAW_DIR="/opt/ideam/raw"
STALL_SECS=3600          # 1h sin journal nuevo
PART_FRESH_MIN=60        # ningun .part tocado en 60 min

log() { logger -t ideam-watchdog "$*"; }

# 1) El servicio debe estar corriendo (o arrancando).
state="$(systemctl show -p ActiveState --value "$UNIT" 2>/dev/null || echo unknown)"
if [[ "$state" != "active" && "$state" != "activating" ]]; then
    # No esta corriendo -> nada que vigilar.
    exit 0
fi

# 2) Antiguedad de la ultima linea del journal para esa unidad.
#    Tomamos el ultimo timestamp __REALTIME (microsegundos epoch).
last_us="$(journalctl -u "$UNIT" -o json -n 1 --output-fields=__REALTIME_TIMESTAMP 2>/dev/null \
            | sed -n 's/.*"__REALTIME_TIMESTAMP"[: ]*"\([0-9]*\)".*/\1/p')"

if [[ -z "${last_us:-}" ]]; then
    # Sin lineas de journal todavia: lo dejamos pasar, aun no hay base de comparacion.
    exit 0
fi

now_us="$(date +%s%6N)"
age_secs=$(( (now_us - last_us) / 1000000 ))

if (( age_secs < STALL_SECS )); then
    # Escribio journal hace poco -> esta avanzando.
    exit 0
fi

# 3) Comprobar si hay descarga de chunk en curso (.part fresco).
#    find -mmin -60 lista archivos modificados en los ultimos 60 min.
if [[ -d "$RAW_DIR" ]]; then
    fresh_part="$(find "$RAW_DIR" -maxdepth 1 -name '*.part' -mmin "-${PART_FRESH_MIN}" -print -quit 2>/dev/null || true)"
    if [[ -n "$fresh_part" ]]; then
        # Hay un .part reciente: esta bajando datos, no esta colgado.
        exit 0
    fi
fi

# Las 3 condiciones se cumplen -> atascado. Reiniciar (reanudable).
log "backfill atascado: ${age_secs}s sin journal y sin .part fresco en ${RAW_DIR}; reiniciando ${UNIT}"
systemctl restart "$UNIT"
log "restart de ${UNIT} emitido"
