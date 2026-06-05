# IDEAM Data Automator

Herramienta en Python para **extraer, validar, organizar y descargar** datos
hidrometeorológicos del IDEAM publicados en Socrata / Datos Abiertos Colombia
(`www.datos.gov.co`), directamente a tu PC.

Desarrollada como Trabajo de Grado de Ingeniería Civil en la Universidad de la
Costa (CUC), Barranquilla — automatiza en minutos lo que manualmente toma horas:
consultar estación por estación en los portales del IDEAM, descargar, limpiar
y organizar los archivos.

## Instalación

```powershell
pip install ideam-data-automator
```

(Requiere Python 3.10+. También puedes clonar el repo y usar `pip install .`)

## Uso

### Interfaz visual (recomendada)

```powershell
ideam-socrata tui
```

Asistente de pantalla completa con navegación por flechas, selección con
checkmarks y panel de resumen en vivo:

1. **Variable** — las 21 fuentes del IDEAM (precipitación, niveles de río y mar,
   temperaturas, viento, humedad, presión, calidad de aire/agua, y más), con buscador.
2. **Departamentos** — selección múltiple + filtros avanzados por zona
   hidrográfica, categoría, tecnología, estado, corriente, entidad, municipio
   o códigos de estación manuales.
3. **Años** — detecta el histórico disponible **para tu filtro** (estaciones y
   rango real de fechas) antes de descargar.
4. **Descarga** — paralela, con progreso en vivo (filas/s, bloques, tiempo restante).

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
tests/                 # Pruebas unitarias
```

## Pruebas

```powershell
python -m pytest tests/
```

## Cita académica

Si usas esta herramienta en tu investigación, cítala con los metadatos de
[`CITATION.cff`](CITATION.cff) (GitHub muestra el botón *"Cite this repository"*).

## Política de datos

Los datos provienen del IDEAM bajo la Política de Datos Abiertos de Colombia y
son de uso académico e investigativo. No se suben datos reales, logs ni
credenciales al repositorio.

## Licencia

Apache 2.0. Ver `LICENSE`.
