# Changelog

Todos los cambios notables de este proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y el
versionado sigue [SemVer](https://semver.org/lang/es/).

> **La historia de este proyecto:** nació como trabajo de grado en Ingeniería
> Civil (Universidad de la Costa, 2026), *"Automatización Inteligente Para La
> Gestión Visual De Datos Hídricos Del IDEAM Con Python Y Power BI"*, que
> demostró un ahorro de tiempo superior al 98 % frente a la descarga manual
> en el portal DHIME. Las versiones posteriores pulieron esta herramienta
> local (más variables, más velocidad, interfaz visual) y la acompañaron de
> la plataforma web del proyecto: [ideam.sergiobc.com](https://ideam.sergiobc.com).

## [1.2.2] - 2026-07-19

*El repositorio y el paquete quedan enfocados en la herramienta local; la
plataforma web se presenta como producto aparte, con su enlace.*

### Cambiado

- El paquete publica únicamente la herramienta local (TUI, asistente de
  consola y descargas por lotes). El código interno de servidor que
  acompañaba al repositorio se retiró del árbol público y del paquete
  (subpaquete `ideam_socrata.db` y extra de instalación `server`).
- README, historia del proyecto y metadatos de cita reescritos alrededor de
  la herramienta local.

## [1.2.1.post1] - 2026-07-19

*Solo documentación, el código es idéntico al de 1.2.1: los dos diagramas del
README (cómo funciona y arquitectura) pasan de Mermaid a imágenes SVG propias,
porque PyPI no dibuja Mermaid y los mostraba como bloques de código crudo.
Además, la guía de instalación abre con un resumen visual en 3 pasos.*

## [1.2.1] - 2026-07-19

*La instalación funciona a la primera para quien no sabe programar.*

### Agregado

- El paquete es ejecutable como módulo: `python -m ideam_socrata tui` (y
  cualquier otro subcomando). Es la vía que funciona aunque la carpeta Scripts
  de Python no esté en el PATH, el caso más común en Windows donde
  `ideam-socrata` "no se reconoce como comando".

### Corregido

- Guía de instalación del README: la ruta principal pasa a ser
  `python -m pip install ideam-data-automator`, que no depende del PATH. La
  secuencia anterior con pipx fallaba a la primera en Windows
  (`pip install --user pipx` deja `pipx.exe` fuera del PATH, así que
  `pipx ensurepath` respondía "no se reconoce como comando") y su nota de
  rescate sugería `python -m ideam_socrata.cli tui`, que con pipx no puede
  funcionar porque el paquete queda aislado en otro entorno.
- Instructivo PDF (`docs/infografias/instructivo-local.pdf`) actualizado con
  los mismos comandos corregidos.

## [1.2.0.post1] - 2026-07-03

*Solo documentación, el código es idéntico al de 1.2.0: el README pasa a ser
una guía paso a paso con imágenes que indica qué hacer en cada pantalla,
pensada para personas sin experiencia en programación.*

## [1.2.0] - 2026-07-03

*Rediseño visual de la TUI y pulido de robustez de la herramienta de terminal,
derivados de una auditoría multiagente del paquete instalable, más las
correcciones de las auditorías de fin de junio. Compatible hacia atrás: no
cambian los comandos ni los formatos de salida.*

### Herramienta de terminal (CLI + TUI)

#### Agregado
- **Rediseño moderno de la TUI** (`ideam-socrata tui`): tema propio de la
  Universidad de la Costa sobre fondo oscuro, cajas con relieve y el título de
  cada paso integrado en el borde, barra de progreso de pasos (Variable,
  Departamentos, Años, Descarga), barra de descarga con degradado y tiempo
  estimado, indicadores de carga nativos, botones que reaccionan al foco y al
  ratón, validación en vivo del rango de años y avisos (toast) al terminar.
- **`verify` informa el resultado de forma fiable**: nuevo campo `ok` en la
  salida JSON y código de salida distinto de cero cuando la muestra no se pudo
  obtener (antes podía reportar éxito ante un fallo de red).

#### Corregido
- **Exportación a prueba de cortes (escritura atómica)**: los archivos Parquet,
  CSV y el resumen se escriben en un temporal y se renombran al final. Si la
  descarga se interrumpe (Ctrl+C, falta de memoria, caída del proceso) ya no
  queda un archivo a medias que aparente estar completo.
- **Salida limpia ante Ctrl+D / fin de entrada**: el asistente interactivo ya no
  muestra un error técnico al cerrarse con Ctrl+D o con la entrada agotada.
- **`verify` resiliente**: la consulta de muestra reintenta ante fallos
  transitorios de red en lugar de abortar con un error crudo.

#### Empaquetado
- `requests` pasa a ser dependencia principal (lo usan los comandos `datasets` y
  `download`); antes solo llegaba de forma indirecta a través de `sodapy`.
- Se requiere `textual >= 2.0` para las nuevas capacidades visuales de la TUI.
- **La configuración se carga solo cuando se necesita**: importar el paquete ya
  no exige tener un `.env` presente, lo que facilita usarlo como librería y
  empaquetarlo como ejecutable.
- Receta de empaquetado a `.exe` de Windows versionada en `packaging/` (icono
  propio y sin arrastrar dependencias del modo servidor al ejecutable).

#### Calidad
- 27 pruebas nuevas (entrypoint de la CLI, escrituras atómicas, validación de
  cargas y empaquetado). El paquete pasa de 79 a 106 pruebas.
- Los umbrales de plausibilidad física de cada variable (por ejemplo, cuánta
  lluvia diaria es físicamente posible) quedan centralizados en un único módulo
  (`physical_ranges`), la referencia que usa la capa de análisis.
- Textos internos y docstrings renombrados al nombre oficial del proyecto,
  **IDEAM Data Automator**.

## [1.1.0] - 2026-06-19

*Endurecimiento de correctitud y robustez tras dos rondas de auditoría. La CLI y
la TUI son **compatibles hacia atrás**: no cambian los comandos, los formatos de
salida ni los `floating_id`. El grueso del trabajo fue del **modo servidor**; los
cambios que afectan a quien usa la herramienta por terminal van primero.*

### Herramienta de terminal (CLI + TUI)

#### Corregido
- **Consultas a Socrata más robustas (escape SoQL)**: los filtros que la CLI envía
  a `datos.gov.co` (el `$where` por departamento, estación y rango de fechas) ahora
  escapan correctamente los literales. Antes, un valor con una comilla o un
  carácter inusual podía romper o alterar la consulta. (El mismo blindaje protege
  al ingestor del modo servidor, donde se procesan miles de valores de forma
  automática.)
- **`--end-date` ahora es exclusivo de verdad**: las ventanas de fechas quedan
  recortadas exactas, sin arrastrar el día final por error.
- Mayor robustez general y rutas de salida predecibles.

#### Agregado
- **Aviso permanente en la TUI** sobre el alcance de la fuente: `datos.gov.co`
  publica la telemetría de las estaciones **automáticas** (que empezaron a
  reportar hacia ~2016); las series **convencionales históricas** viven en el
  portal **DHIME** del IDEAM.
- **7 quick-wins de UX** de la auditoría de producto en la interfaz interactiva.

### Modo servidor (extra `[server]`: espejo PostgreSQL/TimescaleDB e ingesta)

*Solo afecta a quien levanta el espejo de datos; la CLI local no lo necesita.*

#### Cambiado
- **El espejo de Socrata es ahora una copia PURA**: se retiró el saneo físico
  durante la ingesta; el espejo refleja exactamente lo publicado por la fuente y
  el control de calidad físico se reserva para la capa de cálculo (el módulo
  `physical_ranges.py` queda disponible para ese uso).

#### Corregido
- **Bug de precipitación multi-sensor**: en estaciones con varios sensores las
  láminas se inflaban porque los sensores se sumaban. Los agregados diario y
  mensual son ahora *sensor-aware* (usan el sensor más completo por periodo, no
  la suma) y `obs_diario` prefiere el medidor real sobre el sensor GPRS
  sub-reportador.
- **Zona horaria**: la conexión del ingestor fija `America/Bogota` (antes UTC).
- El `COPY` de ingesta ya no aborta el lote entero por una sola fila inválida;
  las altitudes se cargan en su propia transacción. Backfill más robusto: pico de
  disco acotado al liberar los `.csv.gz` tras el split, `--max-time` en `curl`
  contra cuelgues de primer byte y casts `timestamptz` correctos al refrescar
  agregados.

#### Agregado
- Carga local del espejo desde exports masivos `.csv.gz` (divididos por año), para
  sembrar la base sin re-descargar vía API.

### Otros
- Artefactos de **validación IDF externa** (comparación con González 2023, misma
  red de 10 min) y procedimiento reproducible en `docs/validacion/`.
- Cobertura de pruebas ampliada (escape SoQL, zona horaria, espejo puro, rangos
  físicos y validación IDF): la suite supera ahora las **79 pruebas**.

## [1.0.3] - 2026-06-05

*Versión de endurecimiento tras una auditoría integral multi-rol (arquitectura,
seguridad, datos, QA, release y revisión académica).*

### Corregido
- **La API ahora "falla cerrado"**: si `API_SHARED_SECRET` no está configurado se
  rechazan todas las solicitudes (antes quedaba sin autenticación) y se registra
  un error explícito al arrancar.
- **Las descargas de datasets especiales ya no exportan resultados parciales**:
  si un bloque falla tras los reintentos, se cancela la exportación con un
  mensaje claro en lugar de producir archivos incompletos en silencio.
- `requirements.txt` no incluía `textual`: quien instalaba por esa vía no podía
  abrir la interfaz visual (`ideam-socrata tui`).
- `schema.sql` ahora viaja dentro del paquete (package-data) y la guía de
  servidor (`docs/SERVIDOR.md`) documenta el flujo correcto con `git clone`.

### Cambiado
- Pisos de versión mínima en todas las dependencias (`pandas>=2.0`,
  `pydantic>=2.0`, etc.) en `pyproject.toml` y `requirements.txt`.

## [1.0.2] - 2026-06-05

### Agregado
- **Versión citable**: DOI de Zenodo
  ([10.5281/zenodo.20562858](https://doi.org/10.5281/zenodo.20562858)),
  `CITATION.cff` con referencia a la tesis, `.zenodo.json` y badges en el README.

### Cambiado
- README de PyPI enfocado 100 % en la herramienta local (el modo servidor se
  movió a `docs/SERVIDOR.md`).
- El lanzador de Windows (`.bat`) abre la ventana maximizada.

## [1.0.1] - 2026-06-05

### Cambiado
- Nombre del paquete en PyPI: `ideam-data-automator` (coincide con el repositorio).

## [1.0.0] - 2026-06-05

*Primera versión publicada en PyPI. Ejecuta las Líneas de Investigación Futura
del Capítulo 5 de la tesis.*

### Agregado
- **Interfaz visual de pantalla completa** (`ideam-socrata tui`, Textual):
  navegación por flechas, selección con checkmarks, buscador de variables,
  panel de resumen en vivo, animaciones, filtros avanzados del catálogo y
  progreso con filas/s y tiempo restante. Conserva el flujo completo del
  asistente clásico (aviso legal, 21 variables, departamentos, años).
- **Datasets especiales habilitados** (calidad de aire/agua, normales
  climatológicas, zonificación, GEI, escorrentía, catálogo de estaciones) con
  flujo adaptado a la estructura de cada uno.
- **Reporte de cobertura** `RESUMEN_*.txt` en cada descarga: rango real de los
  datos, filas por estación con primera/última observación y % de completitud
  mensual.
- **Cobertura previa por filtro** en el paso de años: estaciones del catálogo y
  rango real de fechas antes de descargar.
- **Fechas reales para Excel**: el CSV exporta `YYYY-MM-DD HH:MM:SS` (filtrable
  como fecha) y el Parquet guarda timestamps nativos, preservando la paridad
  exacta de los `floating_id` históricos.
- **Espejo de datos propio** (propuesta de tesis: *"almacenamiento en bases de
  datos locales o en la nube y ejecución programada de actualizaciones"*):
  subpaquete `ideam_socrata.db` que replica los 13 datasets hidrometeorológicos
  (≈745 millones de observaciones — la tesis trabajó la precipitación,
  ≈282M) en PostgreSQL 15 + TimescaleDB: hypertable comprimida,
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
  tamaño aproximado (la precipitación de la tesis ≈282M dentro de los ≈745M
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
