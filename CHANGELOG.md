# Changelog

Todos los cambios notables de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y el
versionado sigue [SemVer](https://semver.org/lang/es/).

> **La historia de este proyecto:** nació como trabajo de grado en Ingeniería
> Civil (Universidad de la Costa, 2026) — *"Automatización Inteligente Para La
> Gestión Visual De Datos Hídricos Del IDEAM Con Python Y Power BI"* — que
> demostró un ahorro de tiempo superior al 98 % frente a la descarga manual en
> el portal DHIME. Las versiones posteriores ejecutan las **Líneas de
> Investigación Futura** propuestas en esa misma tesis: base de datos propia
> con actualización programada, ampliación a todas las variables
> hidrometeorológicas, superación de los límites de la API Socrata y evolución
> hacia una plataforma web de monitoreo y análisis hídrico.

## [No publicado]

*Ejecuta las Líneas de Investigación Futura del Capítulo 5 de la tesis.*

### Agregado
- **Espejo de datos propio** (propuesta de tesis: *"almacenamiento en bases de
  datos locales o en la nube y ejecución programada de actualizaciones"*):
  subpaquete `ideam_socrata.db` que replica los 13 datasets hidrometeorológicos
  (~745 millones de observaciones — la tesis trabajó los ~250M de
  precipitación) en PostgreSQL 15 + TimescaleDB: hypertable comprimida,
  agregados continuos diario/mensual, backfill histórico paralelo y reanudable,
  y delta incremental diario (04:00) con upsert idempotente por `floating_id`.
- **API HTTP** (propuesta de tesis: *"plataforma inteligente de monitoreo y
  análisis hídrico"*): servicio FastAPI (`api/`) que sirve el espejo —
  catálogos, vista previa, exportación ZIP organizada (csv/json/parquet) y 7
  endpoints de analítica (series temporales, climatología mensual,
  estadísticas por región/estación). Reemplaza las consultas en vivo a Socrata
  de [ideam.sergiobc.com](https://ideam.sergiobc.com).
- **CLI — comando `download`**: descarga no interactiva y scriptable
  (dataset + departamentos + rango de fechas) con dos motores: `rapido`
  (compresión gzip en tránsito, ~2x más veloz) y `soda` (paginación clásica de
  la tesis). Con barra de progreso en vivo y panel de resumen.
- **CLI — comando `datasets`**: tabla de los 13 datasets disponibles con su
  tamaño aproximado (de los ~250M de precipitación de la tesis a los ~745M
  totales hoy mapeados).
- **CLI — validaciones amigables**: departamentos mal escritos sugieren la
  corrección ("¿Quisiste decir 'BOLIVAR'?") y se validan ANTES de ir a la red;
  fechas malformadas o invertidas explican el error en lugar de mostrar un
  traceback; `--version`, `verify` generalizado y ejemplos en `--help`.
- Salida UTF-8 en consolas Windows (acentos correctos).
- Despliegue como servicios `systemd` (`deploy/` y `api/deploy/`): backfill
  reanudable, delta diario, API y limpieza de exports.
- Pruebas nuevas de bloques temporales, paridad de fechas US/ISO y
  validaciones (16 en total).

### Cambiado
- Las dependencias de servidor (`psycopg`) se movieron al extra opcional
  `[server]`: la instalación de la CLI local quedó más liviana (`pip install .`).
- `normalize_chunk` acepta DataFrames además de listas de registros (permite
  procesar CSV masivos por chunks conservando el mismo `floating_id`).
- README reescrito: modos de uso CLI/servidor, mapa del ecosistema y nuevo
  nombre del repositorio (`ideam-data-automator`).

### Corregido
- **El export masivo de Socrata (`rows.csv`) ignora `$where` en silencio**
  (responde HTTP 200 con el dataset completo): las descargas filtradas ahora
  usan `/resource/`, que sí filtra y exige `$limit` explícito. Detectado con
  una prueba de paridad de resultados (211/211 filas).
- **Cortes de conexión en descargas masivas** (la "inestabilidad de la API"
  documentada como limitación en la tesis, ahora diagnosticada): el patrón
  descargar-y-procesar entrelazado dejaba el socket ocioso durante el
  procesamiento y el servidor cortaba la conexión. Ahora la descarga es
  continua a disco (como un navegador) y el procesamiento ocurre aparte; con
  gzip el tiempo de conexión cae ~5-8x adicional.
- La paginación profunda con `$offset` (costo O(n), inviable a escala de
  millones de filas) se eliminó de todas las rutas de descarga masiva.

## [0.1.0] - 2026-04-28

*La herramienta de la tesis, empaquetada.*

### Agregado
- Primera versión pública del pipeline del trabajo de grado (evolución de los
  scripts `v1.7`→`v4.0` desarrollados durante la investigación): CLI
  interactiva (`ideam-socrata interactive`) para extraer, validar y organizar
  datos hidrológicos del IDEAM desde Socrata / Datos Abiertos Colombia.
- Resultado empírico que motivó la herramienta: la extracción automatizada
  redujo el tiempo de descarga en más de un 98 % frente al portal DHIME
  (caso Tolima: 1.151 archivos / 714 MB organizados en 36 carpetas en 4,5
  minutos, frente a más de 249 minutos por la vía manual, que además limita a
  10 estaciones por descarga).
- Normalización de variantes territoriales (tildes, mojibake) con mapeo
  canónico de departamentos.
- `floating_id` (SHA-256) como clave estable para upserts idempotentes.
- Exportación organizada `departamento/municipio/` en Parquet y CSV, con
  división de CSV grandes para no exceder los límites de Excel.
- Validación de payloads con Pydantic y verificación de cobertura territorial.
- Integración continua (GitHub Actions) y pruebas unitarias.
