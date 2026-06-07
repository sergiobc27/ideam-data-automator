#!/bin/bash
# Monitoreo $0 via healthchecks.io (plan gratuito: 20 checks).
#
# CONFIGURACION (una vez):
#   1. Cuenta gratis en https://healthchecks.io
#   2. Crear 3 checks: ideam-api (period 15m, grace 10m),
#      ideam-delta (period 12h, grace 6h), ideam-disco (period 15m).
#   3. Copiar las URLs de ping a /etc/ideam/ideam.env:
#        HC_API_URL=https://hc-ping.com/xxxx
#        HC_DELTA_URL=https://hc-ping.com/yyyy
#        HC_DISK_URL=https://hc-ping.com/zzzz
# Sin URLs configuradas el script solo registra en syslog (no falla).
# healthchecks.io alerta por email cuando un check deja de recibir pings.
set -u

ping_hc() {  # $1=url $2=sufijo ('' exito, '/fail' fallo)
  [ -n "$1" ] && curl -fsS -m 10 --retry 2 -o /dev/null "$1$2" || true
}

# 1) API sana DE VERDAD: /api/ready prueba la DB (no solo el proceso) y
#    ademas se verifica el camino publico completo (edge -> worker -> tunel),
#    porque un tunel caido con API local viva pasaba invisible.
# --retry 3: un blip de 1s de Cloudflare/tunel NO debe disparar /fail (evita
# fatiga de alarmas por falsos positivos transitorios - auditoria #4).
PUBLIC_URL="${PUBLIC_HEALTH_URL:-https://ideam.sergiobc.com/api/health}"
if ! curl -fsS -m 10 --retry 3 --retry-delay 2 --retry-all-errors -o /dev/null http://127.0.0.1:8000/api/ready; then
  logger -t ideam-healthcheck "API local /api/ready NO responde (DB o proceso)"
  ping_hc "${HC_API_URL:-}" "/fail"
elif ! curl -fsS -m 15 --retry 3 --retry-delay 2 --retry-all-errors -o /dev/null "$PUBLIC_URL"; then
  logger -t ideam-healthcheck "camino publico caido (tunel/worker): $PUBLIC_URL"
  ping_hc "${HC_API_URL:-}" "/fail"
else
  ping_hc "${HC_API_URL:-}" ""
fi

# 2) Disco bajo control? (alerta sobre 85%)
USO=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [ "${USO:-0}" -lt 85 ]; then
  ping_hc "${HC_DISK_URL:-}" ""
else
  logger -t ideam-healthcheck "DISCO al ${USO}%"
  ping_hc "${HC_DISK_URL:-}" "/fail"
fi

# 3) El delta corrio en las ultimas 26 horas?
DELTA_OK=$(docker exec ideam-pg psql -U ideam -d ideam -tAc \
  "SELECT count(*) FROM ingest_state WHERE grain='delta' AND status='done' \
   AND updated_at > now() - interval '26 hours'" 2>/dev/null | tr -dc '0-9')
if [ "${DELTA_OK:-0}" -gt 0 ]; then
  ping_hc "${HC_DELTA_URL:-}" ""
else
  logger -t ideam-healthcheck "delta SIN corridas exitosas en 26h"
  ping_hc "${HC_DELTA_URL:-}" "/fail"
fi
