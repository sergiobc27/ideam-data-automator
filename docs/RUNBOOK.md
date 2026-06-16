# RUNBOOK operativo — espejo IDEAM (servidor Oracle)

Procedimientos de guardia para el box que hospeda el espejo PostgreSQL +
TimescaleDB. Todos los comandos asumen `sudo` o sesion root y, salvo nota, que
el reloj del box esta en **UTC**.

Convenciones del box:

- Codigo de la app: `/opt/ideam/app`  ·  API: `/opt/ideam/api`
- venv: `/opt/ideam/venv`  ·  secretos: `/etc/ideam/ideam.env` (600)
- Descargas crudas: `/opt/ideam/raw/` (chunks `.part`) · bulk: `/opt/ideam/bulk/`
- Postgres corre en Docker (contenedor `timescaledb`); `$DATABASE_URL` en el env.
- `psql` rapido:
  ```bash
  set -a; source /etc/ideam/ideam.env; set +a
  psql "$DATABASE_URL"
  ```

> **Dato clave de recuperacion:** TODOS los datos son **re-derivables** desde
> Socrata (datos.gov.co). La base de datos no es la fuente de verdad; es un
> espejo cacheado. Ante corrupcion grave, reconstruir (procedimiento E) siempre
> es una opcion valida, solo cuesta tiempo de descarga.

---

## A. Backfill atascado / colgado

Sintoma: `ideam-backfill` lleva horas `active` pero el conteo de filas no sube,
o el journal no escribe nada.

```bash
# 1. Estado y ultima actividad
systemctl status ideam-backfill
journalctl -u ideam-backfill -n 50 --no-pager
journalctl -u ideam-backfill -o json -n 1 --output-fields=__REALTIME_TIMESTAMP

# 2. Hay descarga viva? (un .part recien tocado = sigue bajando)
find /opt/ideam/raw -maxdepth 1 -name '*.part' -mmin -60 -ls

# 3. El watchdog ya deberia actuar solo cada 15 min. Revisa que vigilo:
journalctl -t ideam-watchdog -n 30 --no-pager
systemctl list-timers ideam-watchdog.timer
```

Si esta colgado y no quieres esperar al watchdog, reinicia a mano (es seguro,
el backfill es **reanudable** via `ingest_state`):

```bash
systemctl restart ideam-backfill
journalctl -u ideam-backfill -f          # confirma que reanuda y avanza
```

Verifica el progreso real en la base:

```sql
-- pares dataset/anio pendientes vs completados
SELECT status, count(*) FROM ingest_state GROUP BY status;
```

Si reinicia y se vuelve a colgar siempre en el mismo dataset/anio: aislar ese
caso ejecutando el backfill de un solo dataset en primer plano para ver el error:

```bash
set -a; source /etc/ideam/ideam.env; set +a
/opt/ideam/venv/bin/python -m ideam_socrata.db.backfill \
    --dataset ia8x-22em --mode year --compress
```

---

## B. `ideam-delta` failed

Sintoma: `systemctl list-timers` muestra el delta, pero la ultima corrida fallo
(o llego una alerta de healthchecks.io).

```bash
# 1. Por que fallo
systemctl status ideam-delta
journalctl -u ideam-delta -n 80 --no-pager

# 2. Reintento manual inmediato (oneshot, no necesita reset previo)
systemctl start ideam-delta
journalctl -u ideam-delta -f
```

Causas frecuentes:

- **Socrata caido / 5xx o rate limit (429):** reintenta mas tarde; el delta es
  idempotente (`ON CONFLICT DO UPDATE`). Si es rate limit, confirma que
  `SOCRATA_APP_TOKENS` tenga tokens validos en el env.
- **Postgres no responde:** ver que el contenedor este arriba
  ```bash
  docker ps --filter name=timescaledb
  docker logs --tail 50 timescaledb
  ```
- **Estado degradado:** forzar refresco de agregados continuos si las vistas
  quedaron atrasadas:
  ```sql
  CALL refresh_continuous_aggregate('obs_diario',  now() - INTERVAL '7 days', now());
  CALL refresh_continuous_aggregate('obs_mensual', now() - INTERVAL '2 months', now());
  ```

El timer dispara solo a 04:00 y 16:00 UTC; un reintento manual no descoloca el
calendario.

---

## C. Disco llenandose

Sintoma: alertas de espacio, o escrituras que empiezan a fallar.

```bash
# 1. Ver uso global y de los directorios IDEAM
df -h /
du -h -d1 /opt/ideam | sort -h
docker system df                      # cuanto ocupa Docker (imagenes/volumenes)
```

Acciones, de menos a mas agresivas:

```bash
# a) Limpiar exports temporales de la API (los borra solo el timer cada 15 min,
#    pero puedes forzarlo)
systemctl start ideam-export-cleanup
ls -lh /var/lib/ideam-api/exports

# b) Borrar chunks crudos ya cargados/comprimidos
ls -lh /opt/ideam/raw
rm -f /opt/ideam/raw/*.part          # solo los .part HUERFANOS (sin backfill vivo)
# (verifica antes que ideam-backfill NO este active)

# c) .csv.gz de bulk ya ingeridos
ls -lh /opt/ideam/bulk
rm -f /opt/ideam/bulk/*.csv.gz       # re-descargables con descargar.sh

# d) Imagenes/contenedores Docker colgados
docker system prune -f
```

A nivel base de datos, verificar que la **compresion de TimescaleDB** este
realmente aplicada (es lo que hace que ~450M de filas quepan):

```sql
SELECT pg_size_pretty(hypertable_size('observaciones'));
SELECT count(*) FROM timescaledb_information.chunks
WHERE hypertable_name='observaciones' AND is_compressed;
```

Si hay muchos chunks sin comprimir, el backfill `--mode year` los comprime al
cerrar cada anio; un backfill interrumpido puede dejarlos pendientes.

---

## D. API caida (tunel / uvicorn)

Sintoma: el frontend no recibe datos; el dominio publico da 502/timeout.

```bash
# 1. Esta arriba uvicorn?
systemctl status ideam-api
journalctl -u ideam-api -n 60 --no-pager
curl -fsS http://127.0.0.1:8000/health || echo "API local NO responde"
```

Si la API local responde pero el dominio publico no, el problema es el **tunel
Cloudflare**:

```bash
systemctl status cloudflared
journalctl -u cloudflared -n 60 --no-pager
cloudflared tunnel info <NOMBRE_O_UUID>      # estado de las conexiones
```

Reinicios (de menos a mas):

```bash
systemctl restart ideam-api        # solo la app
systemctl restart cloudflared      # solo el tunel
```

Si uvicorn no levanta, suele ser:

- DB inalcanzable -> revisar `docker ps` / `$DATABASE_URL` (ver C/E).
- Error de import o dependencia -> probar en primer plano:
  ```bash
  set -a; source /etc/ideam/ideam.env; set +a
  cd /opt/ideam/api
  /opt/ideam/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
  ```

`Restart=always` reintenta uvicorn solo; si entra en bucle de reinicio,
`journalctl -u ideam-api -f` muestra la causa repetida.

---

## E. Reconstruir el servidor desde cero

Cuando el box se pierde o la base se corrompe. **Todo es re-derivable de
Socrata**; el unico costo es el tiempo de descarga del historico.

> **Prueba de restauracion (verificada 2026-06-16).** El backup diario
> `/var/backups/ideam/ideam_backup_*.sql.gz` se restauro en un contenedor
> TimescaleDB temporal y aislado **sin errores**: `estaciones` (17.976 filas) e
> `ingest_state` (116) vuelven integras. **Alcance real del backup:** es
> `--schema-only` (toda la DDL) + `--data-only` SOLO de `ingest_state` y
> `estaciones`. NO incluye los datos de `observaciones` ni los datos del catalogo
> de TimescaleDB, asi que al restaurarlo `observaciones` queda como **tabla plana
> (0 hypertables)**. Por eso el `.sql.gz` **NO es un restore standalone**: la
> recuperacion correcta es ESTE procedimiento E (correr `schema.sql`, que recrea
> las hypertables/caggs/compresion, + backfill desde Socrata). El backup sirve
> para (a) conservar los high-water marks de `ingest_state` y el catalogo
> `estaciones`, y (b) como verificacion de integridad. Las observaciones SIEMPRE
> se re-derivan de Socrata. Atajo opcional: tras el paso 3, restaurar solo la
> data de `ingest_state` desde el backup permite que el delta reanude sin
> re-backfillear todo.

### 1. Base de datos (Docker TimescaleDB)

```bash
mkdir -p /opt/ideam/pgdata
docker run -d --name timescaledb --restart unless-stopped \
    -p 127.0.0.1:5432:5432 \
    -e POSTGRES_PASSWORD='<password>' \
    -e POSTGRES_DB=ideam \
    -v /opt/ideam/pgdata:/var/lib/postgresql/data \
    timescale/timescaledb:latest-pg15
docker ps --filter name=timescaledb
```

### 2. Codigo, venv y secretos

```bash
git clone https://github.com/sergiobc27/ideam-data-automator.git /opt/ideam/app
python3 -m venv /opt/ideam/venv
/opt/ideam/venv/bin/pip install -e "/opt/ideam/app[server]"

# Recrear el env (DATABASE_URL, SOCRATA_APP_TOKENS, HEALTHCHECK_URL, etc.)
install -m 600 /dev/null /etc/ideam/ideam.env
$EDITOR /etc/ideam/ideam.env
set -a; source /etc/ideam/ideam.env; set +a
```

### 3. Esquema (idempotente) + catalogo de estaciones

```bash
psql "$DATABASE_URL" -f /opt/ideam/app/src/ideam_socrata/db/schema.sql
/opt/ideam/venv/bin/python -m ideam_socrata.db.load_estaciones
```

### 4. Backfill historico

Opcion rapida de arranque (cola de exports masivos, verificados con `gzip -t`):

```bash
install -m 755 /opt/ideam/app/deploy/descargar-bulk.sh /opt/ideam/bulk/descargar.sh
/opt/ideam/bulk/descargar.sh
```

Carga incremental/oficial via systemd (reanudable, comprime por anio):

```bash
install -m 644 /opt/ideam/app/deploy/ideam-backfill.service /etc/systemd/system/
systemctl daemon-reload
systemctl start ideam-backfill
journalctl -u ideam-backfill -f
# verificar progreso: SELECT status,count(*) FROM ingest_state GROUP BY status;
```

### 5. Units / unidades de medida y agregados

La `unidadmedida` llega como columna en cada observacion, asi que el backfill ya
la puebla. Tras la carga, materializar los agregados continuos:

```sql
CALL refresh_continuous_aggregate('obs_diario',  NULL, NULL);
CALL refresh_continuous_aggregate('obs_mensual', NULL, NULL);
```

### 6. Delta + watchdog (automatizacion continua)

```bash
cd /opt/ideam/app/deploy
install -m 644 ideam-delta.service ideam-delta.timer /etc/systemd/system/
install -m 755 ideam-watchdog.sh /usr/local/bin/ideam-watchdog.sh
install -m 644 ideam-watchdog.service ideam-watchdog.timer /etc/systemd/system/
# (opcional) monitoreo healthchecks.io
install -m 644 ideam-notify-fail@.service /etc/systemd/system/
mkdir -p /etc/systemd/system/ideam-delta.service.d
install -m 644 ideam-delta-healthcheck.conf /etc/systemd/system/ideam-delta.service.d/healthcheck.conf

systemctl daemon-reload
systemctl enable --now ideam-delta.timer ideam-watchdog.timer
systemctl list-timers 'ideam-*'
```

### 7. API + tunel Cloudflare

```bash
install -m 644 /opt/ideam/app/api/deploy/ideam-api.service /etc/systemd/system/
install -m 644 /opt/ideam/app/api/deploy/ideam-export-cleanup.service \
               /opt/ideam/app/api/deploy/ideam-export-cleanup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ideam-api ideam-export-cleanup.timer
curl -fsS http://127.0.0.1:8000/health

# Cloudflare Tunnel (credenciales y config.yml propias del box)
cloudflared service install            # o restaurar /etc/cloudflared/
systemctl enable --now cloudflared
cloudflared tunnel info <NOMBRE_O_UUID>
```

### 8. Verificacion final

```bash
systemctl is-active ideam-api cloudflared
systemctl list-timers 'ideam-*'
psql "$DATABASE_URL" -c "SELECT pg_size_pretty(hypertable_size('observaciones'));"
psql "$DATABASE_URL" -c "SELECT count(*) FROM estaciones;"
```
