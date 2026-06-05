# Modo servidor (espejo propio) — opcional

> Esto **no** es necesario para la herramienta local (`pip install
> ideam-data-automator`). Es la infraestructura avanzada que hospeda un espejo
> completo de los datos en una base de datos propia.

El espejo completo (≈450 millones de observaciones) vive en PostgreSQL 15 +
TimescaleDB con compresión columnar y agregados continuos para dashboards:

```bash
pip install "ideam-data-automator[server]"
psql "$DATABASE_URL" -f src/ideam_socrata/db/schema.sql   # esquema idempotente
python -m ideam_socrata.db.load_estaciones                 # catálogo de estaciones
python -m ideam_socrata.db.backfill --dataset all --mode year
python -m ideam_socrata.db.delta                           # incremental diario
```

## Componentes

```text
src/ideam_socrata/db/  # schema.sql, backfill paralelo reanudable, delta diario
api/                   # API FastAPI (catálogos, preview, export ZIP, analítica)
deploy/                # Unidades systemd (backfill, delta, API)
```

- **`backfill --mode year`**: carga por años descendentes con compresión del
  año al completarse (nunca insertar en chunks ya comprimidos), rotación de
  App Tokens (`SOCRATA_APP_TOKENS`, separados por coma) y reanudación vía
  tabla `ingest_state`.
- **`delta`**: incremental diario desde el `hwm` (máxima fecha cargada),
  con `ON CONFLICT ... DO UPDATE` porque el IDEAM corrige valores históricos.
- **API**: replica los contratos del frontend y agrega analítica (series
  temporales, climatología, estadísticas por región/estación), servida tras
  Cloudflare Tunnel.

## Secretos

`DATABASE_URL`, tokens de Socrata y el secreto del proxy viven en
`/etc/ideam/ideam.env` (permisos 600) en el servidor — nunca en el repositorio.
