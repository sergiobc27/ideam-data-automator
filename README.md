# IDEAM Data Automator

Herramientas en Python para extraer, validar, organizar y descargar datos
hidrometeorológicos del IDEAM publicados en Socrata / Datos Abiertos Colombia
(`www.datos.gov.co`).

Este repositorio es el **motor** del ecosistema IDEAM y ofrece dos formas de uso:

| Modo | Para quién | Cómo |
|---|---|---|
| **CLI local** | Quien quiere descargar datos a su PC (la herramienta original de la tesis) | `pip install .` y listo |
| **Servidor** | Quien quiere hospedar un espejo propio en PostgreSQL/TimescaleDB con API HTTP (es lo que alimenta [ideam.sergiobc.com](https://ideam.sergiobc.com)) | `pip install ".[server]"` + carpeta `api/` |

## Funcionalidades

- Consulta los 13 datasets hidrometeorológicos estándar del IDEAM (precipitación,
  niveles de río y mar, temperaturas, viento, humedad, presión) más datasets especiales.
- Filtra por departamento, municipio, estación y rango temporal, con homologación
  de variantes territoriales (tildes, mojibake: `ATLANTICO`/`ATLÁNTICO`).
- Genera `floating_id` estable (SHA-256) para upserts idempotentes.
- Exporta organizado por `departamento/municipio/` en Parquet y CSV, dividiendo
  CSV grandes para no exceder los límites de Excel.
- Valida payloads con Pydantic.
- **Modo servidor**: backfill masivo paralelo y reanudable hacia una hypertable
  comprimida de TimescaleDB, delta diario incremental, y API FastAPI con
  endpoints de catálogo, vista previa, exportación ZIP y analítica.

## Instalación (CLI local)

```powershell
git clone https://github.com/sergiobc27/ideam-data-automator.git
cd ideam-data-automator
python -m venv .venv
.venv\Scripts\Activate.ps1          # En Linux/macOS: source .venv/bin/activate
pip install .
```

## Uso rápido

```powershell
# Ver los datasets disponibles y sus IDs
ideam-socrata datasets

# Asistente interactivo (guiado, con menús)
ideam-socrata interactive

# Descarga directa scriptable (sin menús): precipitación de Atlántico, ene-mar 2024
ideam-socrata download --dataset s54a-sgyg --department ATLANTICO `
    --start-date 2024-01-01 --end-date 2024-04-01 --csv

# Verificación rápida de cobertura
ideam-socrata verify-atlantico --start-date 2024-01-01 --end-date 2024-02-01
```

`download` acepta `--department` repetido, `--output-dir`, `--workers` y `--csv`.
Los archivos quedan organizados como `salida/DEPARTAMENTO/MUNICIPIO/variable_*.parquet|csv`.

## Configuración

Copia `.env.example` a `.env` si quieres manejar variables localmente. Un token
de aplicación de Socrata (gratuito) mejora límites y estabilidad:

```text
SOCRATA_APP_TOKEN=
SOCRATA_DOMAIN=www.datos.gov.co
SOCRATA_LIMIT=50000
SOCRATA_MAX_WORKERS=10
SOCRATA_TIMEOUT=300
```

## Estructura

```text
src/ideam_socrata/
  cli.py               # Entry point CLI (interactive, datasets, download, verify)
  batch.py             # Descarga no interactiva / scriptable
  config.py            # Configuración, cliente Socrata y catálogo de datasets
  core.py              # Flujo interactivo de descarga
  extract.py           # Paginación Socrata
  transform.py         # Normalización, floating_id, deduplicación
  query_validation.py  # Validación de variantes territoriales
  exporting.py         # Export Parquet/CSV organizado por carpetas
  validation.py        # Modelos Pydantic
  load.py              # Payload y upsert hacia Socrata
  db/                  # [server] Espejo PostgreSQL/TimescaleDB:
                       #   schema.sql, backfill paralelo, delta diario, estaciones
api/                   # [server] API FastAPI (catálogos, preview, export ZIP, analítica)
deploy/                # [server] Unidades systemd (backfill, delta, API)
tests/                 # Pruebas unitarias
```

## Modo servidor (espejo propio)

El espejo completo (≈450 millones de observaciones) vive en PostgreSQL 15 +
TimescaleDB con compresión columnar y agregados continuos para dashboards:

```bash
pip install ".[server]"
psql "$DATABASE_URL" -f src/ideam_socrata/db/schema.sql   # esquema idempotente
python -m ideam_socrata.db.load_estaciones                 # catálogo de estaciones
python -m ideam_socrata.db.backfill --dataset all --compress --workers 8
python -m ideam_socrata.db.delta                           # incremental diario
```

La API (`api/`) replica los contratos del frontend de `ideam.sergiobc.com` y agrega
analítica (series temporales, climatología, estadísticas por región/estación).
Las unidades de `deploy/` y `api/deploy/` dejan todo corriendo bajo systemd.

## Pruebas

```powershell
python -m unittest discover -s tests
python -m compileall src tests
```

## Política de datos

No se deben subir datos reales, logs, cachés, backups ni credenciales al
repositorio. Los directorios `data/`, `archive/`, `Backup/`, `logs/`, `scratch/`
y `scripts/legacy/` están excluidos del paquete público.

## Ecosistema

| Repositorio | Rol |
|---|---|
| **ideam-data-automator** (este) | Motor: CLI local + ingesta + API |
| `website` | Webapp [ideam.sergiobc.com](https://ideam.sergiobc.com) (React + Cloudflare Worker) |
| `ideam-figma-design` | Referencia histórica del diseño (archivado) |

## Licencia

Apache 2.0. Ver `LICENSE`.
