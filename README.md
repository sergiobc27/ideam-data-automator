# IDEAM Data Automator

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20562858.svg)](https://doi.org/10.5281/zenodo.20562858)
[![PyPI](https://img.shields.io/pypi/v/ideam-data-automator.svg)](https://pypi.org/project/ideam-data-automator/)
[![Python](https://img.shields.io/pypi/pyversions/ideam-data-automator.svg)](https://pypi.org/project/ideam-data-automator/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Herramienta en Python para **extraer, validar, organizar y descargar** datos
hidrometeorológicos del IDEAM publicados en Socrata / Datos Abiertos Colombia
(`www.datos.gov.co`), directamente a tu PC.

Desarrollada como Trabajo de Grado de Ingeniería Civil en la Universidad de la
Costa (CUC), Barranquilla. Automatiza en minutos lo que manualmente toma horas:
consultar estación por estación en los portales del IDEAM, descargar, limpiar
y organizar los archivos.

> **Guías visuales**: si prefieres ver el proceso completo en una sola página,
> descarga la [infografía del flujo local](docs/infografias/infografia-flujo-local.pdf)
> o el [instructivo paso a paso](docs/infografias/instructivo-local.pdf) (PDF).
> La versión web de la plataforma vive en [ideam.sergiobc.com](https://ideam.sergiobc.com).

## Cómo funciona

```mermaid
flowchart LR
    A["datos.gov.co<br/>(Socrata, 13 datasets)"] -->|"extracción paginada<br/>con reintentos"| B["Validación y<br/>transformación"]
    B -->|"deduplicación<br/>fechas reales<br/>homologación territorial"| C["Parquet + CSV<br/>organizados por<br/>DEPARTAMENTO/MUNICIPIO"]
    C --> D["RESUMEN por descarga:<br/>cobertura real, filas<br/>por estación"]
    style A fill:#1d4ed8,color:#fff
    style B fill:#0e7490,color:#fff
    style C fill:#15803d,color:#fff
    style D fill:#a16207,color:#fff
```

## Instalación

Requiere Python 3.10+. La forma recomendada es **pipx**, que instala la
herramienta de forma aislada y deja el comando `ideam-socrata` listo en tu PATH:

```powershell
pip install --user pipx
pipx ensurepath
pipx install ideam-data-automator
```

Cierra y vuelve a abrir la terminal tras `pipx ensurepath`. También funciona el
clásico `pip install ideam-data-automator`.

> **¿La terminal dice "ideam-socrata no se reconoce como comando"?**
> Es que la carpeta de scripts de Python no quedó en el PATH (pasa seguido en
> Windows). Dos salidas: (a) usa `pipx` como arriba, que lo arregla; o (b)
> ejecuta siempre anteponiendo `python -m`:
> ```powershell
> python -m ideam_socrata.cli tui
> ```

## Uso

### Interfaz visual (recomendada)

```powershell
ideam-socrata tui
```

Asistente de pantalla completa con navegación por flechas, selección con
checkmarks y panel de resumen en vivo. Así se ve el recorrido completo:

**0. Acuerdo de uso**: al abrir por primera vez, la herramienta explica de
dónde vienen los datos y sus condiciones de uso académico.

<p align="center">
  <img src="docs/img/tui-0-acuerdo.svg" alt="Pantalla de acuerdo de uso de la TUI" width="760">
</p>

**1. Variable**: las 21 variables del IDEAM (precipitación, niveles de río y mar,
temperaturas, viento, humedad, presión, calidad de aire/agua, y más), con buscador.
Son **13 datasets estándar** (las series hidrometeorológicas que suman
≈745 millones de observaciones) más **8 variables especiales**: 13 + 8 = 21.

<p align="center">
  <img src="docs/img/tui-1-variable.svg" alt="Paso 1 de la TUI: selección de variable" width="760">
</p>

**2. Departamentos**: selección múltiple + filtros avanzados por zona
hidrográfica, categoría, tecnología, estado, corriente, entidad, municipio
o códigos de estación manuales.

<p align="center">
  <img src="docs/img/tui-2-deptos.svg" alt="Paso 2 de la TUI: selección de departamentos" width="760">
</p>

**3. Años**: detecta el histórico disponible **para tu filtro** (estaciones y
rango real de fechas) antes de descargar.

<p align="center">
  <img src="docs/img/tui-3-anios.svg" alt="Paso 3 de la TUI: selección de años" width="760">
</p>

**4. Descarga**: paralela, con progreso en vivo (filas/s, bloques, tiempo restante).

<p align="center">
  <img src="docs/img/tui-4-descarga.svg" alt="Paso 4 de la TUI: descarga con progreso en vivo" width="760">
</p>

### Asistente clásico de consola

```powershell
ideam-socrata interactive
```

### Descarga directa scriptable (sin menús)

```powershell
# Ver los datasets disponibles y sus IDs
ideam-socrata datasets

# Precipitación de Atlántico, ene-mar 2024, con copia CSV
ideam-socrata download --dataset s54a-sgyg --department ATLANTICO `
    --start-date 2024-01-01 --end-date 2024-04-01 --csv
```

`download` acepta `--department` repetido, `--output-dir`, `--workers` y `--csv`.

## Qué obtienes

- **Dónde quedan tus archivos**: por defecto en `Documentos\IDEAM_Data\`
  (puedes cambiarlo con `--output-dir` o la variable `IDEAM_OUTPUT_DIR`). La TUI
  muestra la ruta exacta al terminar y la tecla **O** abre la carpeta.
- Archivos organizados por carpetas: `DEPARTAMENTO/MUNICIPIO/variable_*.parquet|csv`.
- **Fechas reales** (no texto): el CSV abre en Excel con filtros de fecha
  funcionales y el Parquet trae timestamps nativos para PowerBI/pandas.
- CSV dividido automáticamente para no exceder el límite de filas de Excel.
- **`RESUMEN_*.txt`** por descarga: rango real de los datos, filas por estación
  con primera/última observación y % de completitud mensual.
- Deduplicación automática y homologación de variantes territoriales
  (`ATLANTICO`/`ATLÁNTICO`, mojibake del portal).

## Configuración (opcional)

Un token de aplicación de Socrata (gratuito) mejora límites y estabilidad.
Copia `.env.example` a `.env`:

```text
SOCRATA_APP_TOKEN=
SOCRATA_DOMAIN=www.datos.gov.co
SOCRATA_LIMIT=50000
SOCRATA_MAX_WORKERS=10
SOCRATA_TIMEOUT=300
```

Para la herramienta local basta con un solo `SOCRATA_APP_TOKEN`. El modo
servidor (espejo completo) usa en cambio `SOCRATA_APP_TOKENS` (en plural, varios
tokens separados por coma que se rotan en round-robin) para sostener las
descargas masivas; ver [docs/SERVIDOR.md](docs/SERVIDOR.md).

## Estructura

```text
src/ideam_socrata/
  tui.py               # Interfaz visual de pantalla completa (Textual)
  main.py / core.py    # Asistente clásico de consola
  cli.py               # Entry point (tui, interactive, datasets, download, verify)
  batch.py             # Descarga no interactiva / scriptable
  engine.py            # Motor de descarga silencioso (usado por la TUI)
  config.py            # Configuración, cliente Socrata y catálogo de datasets
  extract.py           # Paginación Socrata
  transform.py         # Normalización, floating_id, deduplicación
  query_validation.py  # Validación de variantes territoriales
  exporting.py         # Export Parquet/CSV + reporte de cobertura
  validation.py        # Modelos Pydantic
api/                   # API FastAPI que sirve el espejo de datos
deploy/                # Ingestor, esquema TimescaleDB y operación del servidor
tests/                 # Pruebas unitarias
docs/                  # Guías, infografías y validación técnica
```

## Arquitectura del proyecto

La plataforma completa se reparte en **dos repositorios** complementarios:

```mermaid
flowchart TB
    subgraph repo1["sergiobc27/ideam-data-automator (este repo)"]
        CLI["Paquete Python<br/>CLI + TUI de descarga"]
        DB["Espejo PostgreSQL +<br/>TimescaleDB (Oracle Cloud)"]
        API["API FastAPI"]
        DB --- API
    end
    subgraph repo2["sergiobc27/website"]
        WEB["Frontend React/Vite +<br/>Cloudflare Worker"]
    end
    SOC["Socrata<br/>datos.gov.co"] --> CLI
    SOC --> DB
    API -->|"Cloudflare Tunnel"| WEB
    WEB --> USR["ideam.sergiobc.com"]
    style SOC fill:#1d4ed8,color:#fff
    style USR fill:#15803d,color:#fff
```

- **Este repo (`ideam-data-automator`)**: el paquete Python instalable (CLI y
  TUI de descarga), el espejo PostgreSQL + TimescaleDB del histórico del IDEAM
  y la API FastAPI (`api/`) que lo sirve, desplegados en un servidor de Oracle
  Cloud. La operación del servidor está documentada en
  [docs/SERVIDOR.md](docs/SERVIDOR.md) y los procedimientos de guardia y
  recuperación en [docs/RUNBOOK.md](docs/RUNBOOK.md).
- **[`sergiobc27/website`](https://github.com/sergiobc27/website)**: el
  frontend web (React/Vite) y el Cloudflare Worker que hace de proxy hacia la
  API, publicados en [ideam.sergiobc.com](https://ideam.sergiobc.com).

La herramienta local de este repo funciona por sí sola contra Socrata (no
necesita el servidor); el espejo, la API y la web son la capa de consulta y
análisis construida encima.

## Documentación

| Documento | Qué contiene |
| --- | --- |
| [Infografía del flujo local](docs/infografias/infografia-flujo-local.pdf) | El proceso completo de descarga en una página visual |
| [Instructivo paso a paso](docs/infografias/instructivo-local.pdf) | Guía de instalación y uso con capturas |
| [docs/SERVIDOR.md](docs/SERVIDOR.md) | Operación del espejo de datos y la API |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Procedimientos de guardia y recuperación |
| [docs/HISTORIA.md](docs/HISTORIA.md) | Historia y evolución del proyecto |
| [docs/validacion/](docs/validacion/) | Validación externa de las curvas IDF |

## Pruebas

```powershell
python -m pytest tests/
```

## Cita académica

Si usas esta herramienta en tu investigación, cítala con los metadatos de
[`CITATION.cff`](CITATION.cff) (GitHub muestra el botón *"Cite this repository"*).

## Limitaciones y preguntas frecuentes

**¿Por qué no hay datos antes de ~2016 en mi municipio?**
El portal `datos.gov.co` publica la telemetría de las **estaciones automáticas**
del IDEAM, que en su mayoría empezaron a reportar alrededor de 2016. Las series
**convencionales históricas** (medidas a mano desde 1929 hasta ~2015) no están
en datos abiertos: viven solo en el portal **DHIME** del IDEAM. Por eso, para
muchas estaciones el inicio del registro disponible aquí es relativamente
reciente. Revisa siempre el archivo **`RESUMEN_*.txt`** que acompaña cada
descarga: ahí ves la cobertura real estación por estación (primera y última
observación y % de completitud), que es la única fuente confiable de "hasta
dónde llega" tu serie.

**¿Por qué mi descarga tiene menos filas que las que muestra el portal?**
La herramienta **deduplica** los datos por la combinación
**estación + sensor + fecha**: si el portal entrega la misma medición repetida
(algo común cuando el IDEAM republica o corrige valores), aquí se conserva una
sola. El conteo del portal incluye esos duplicados; tu archivo no. Menos filas
no significa datos perdidos, sino datos limpios.

**¿Hay límites de velocidad al descargar?**
Sí. Socrata (la plataforma de `datos.gov.co`) limita cuántas peticiones puede
hacer un cliente por hora. Sin token, ese límite es compartido y bajo, así que
descargas grandes pueden ralentizarse o cortarse. Un **App Token gratuito**
(ver *Configuración*) sube ese límite y hace la descarga más estable. Aun con
token, las descargas de varios años pueden tardar; la herramienta pagina,
reintenta y reanuda automáticamente.

## Política de datos

Los datos provienen del IDEAM bajo la Política de Datos Abiertos de Colombia y
son de uso académico e investigativo. No se suben datos reales, logs ni
credenciales al repositorio.

## Licencia

Apache 2.0. Ver `LICENSE`.
