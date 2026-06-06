# Modo servidor (espejo propio) — opcional

> Esto **no** es necesario para la herramienta local (`pip install
> ideam-data-automator`). Es la infraestructura avanzada que hospeda un espejo
> completo de los datos en una base de datos propia.

El espejo completo (≈745 millones de observaciones en los 13 datasets estándar;
precipitación sola ≈282 millones) vive en PostgreSQL 15 + TimescaleDB con
compresión columnar y agregados continuos para dashboards.

El modo servidor se instala **clonando el repositorio** (las carpetas `api/` y
`deploy/` no viajan en el paquete pip):

```bash
git clone https://github.com/sergiobc27/ideam-data-automator.git
cd ideam-data-automator
pip install -e ".[server]"
psql "$DATABASE_URL" -f src/ideam_socrata/db/schema.sql   # esquema idempotente
python -m ideam_socrata.db.load_estaciones                 # catálogo de estaciones
python -m ideam_socrata.db.backfill --dataset all --mode year
python -m ideam_socrata.db.delta                           # incremental diario
```

(Desde v1.0.3 `schema.sql` también viaja dentro del paquete pip; su ruta instalada se
obtiene con `python -c "import ideam_socrata.db, pathlib; print(pathlib.Path(ideam_socrata.db.__file__).parent / 'schema.sql')"`.)

## Componentes

```text
src/ideam_socrata/db/  # schema.sql, backfill paralelo reanudable, delta diario
api/                   # API FastAPI (catálogos, preview, export ZIP, analítica)
deploy/                # Unidades systemd (backfill, delta, API)
```

- **`backfill --mode year`**: carga por años descendentes con compresión del
  año al completarse (nunca insertar en chunks ya comprimidos), rotación de
  App Tokens y reanudación vía tabla `ingest_state`.
- **`delta`**: incremental diario desde el `hwm` (máxima fecha cargada),
  con `ON CONFLICT ... DO UPDATE` porque el IDEAM corrige valores históricos.
- **API**: replica los contratos del frontend y agrega analítica (series
  temporales, climatología, estadísticas por región/estación), servida tras
  Cloudflare Tunnel.

## Tokens de Socrata (rotación)

A diferencia de la herramienta local —que usa un único `SOCRATA_APP_TOKEN`—, el
ingestor del servidor admite un **pool** de App Tokens en la variable
`SOCRATA_APP_TOKENS` (plural): varios tokens **separados por coma**. El backfill
los rota en **round-robin** entre peticiones para repartir la carga y no agotar
el límite de velocidad de un solo token durante las descargas masivas de años
completos.

```text
# Un token (igual que la herramienta local):
SOCRATA_APP_TOKEN=abc123

# Pool rotatorio para el ingestor del servidor:
SOCRATA_APP_TOKENS=token_uno,token_dos,token_tres
```

Si solo defines `SOCRATA_APP_TOKEN`, el ingestor también lo usa; el pool plural
es para sostener el throughput del espejo completo.

## Secretos

`DATABASE_URL`, tokens de Socrata y el secreto del proxy viven en
`/etc/ideam/ideam.env` (permisos 600) en el servidor — nunca en el repositorio.
