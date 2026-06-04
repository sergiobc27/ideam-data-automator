# Historia del proyecto

*Crónica de cómo nació, evolucionó y se transformó este proyecto — de una
inquietud en clase de Hidráulica a una plataforma de datos con cientos de
millones de observaciones.*

---

## 1. El origen (segundo semestre de 2024): del Canal del Dique a los datos

El proyecto nace hacia **agosto de 2024**, en las aulas de **Ingeniería Civil
de la Universidad de la Costa (CUC)**, durante la asignatura de Hidráulica con
la ingeniera Carol Prada Sánchez, e incubado en el **Semillero de
Investigación en Recursos Hídricos**. El planteamiento inicial era distinto:
*"Modelado y gestión de la sedimentación en el Canal del Dique"*.

Pero al intentar conseguir los datos hidrológicos que ese estudio necesitaba,
apareció el verdadero problema —y la verdadera oportunidad—: obtener
información del IDEAM era lento, fragmentado y frustrante. Lo que empezó como
un obstáculo se convirtió en el proyecto mismo. La pregunta se reformuló:
*¿por qué obtener datos públicos de agua en Colombia tiene que ser tan
difícil, y cómo se arregla?*

Y no era una percepción aislada. Cualquiera que necesitara series históricas
del IDEAM enfrentaba el mismo calvario en el portal **DHIME**: máximo 10
estaciones por descarga, consultas fraccionadas por periodos, archivos
comprimidos que había que unir a mano, y errores frecuentes con cargas
grandes. En la propia encuesta de satisfacción del IDEAM (2021-I), el
**66,6 %** de los participantes manifestó insatisfacción, con los "tiempos de
respuesta" como la queja principal.

## 2. El primer intento: web scraping y la respuesta del IDEAM (dic 2024 – mar 2025)

Hacia **diciembre de 2024 / enero de 2025** llegaron las primeras pruebas
técnicas: **automatizar el portal DHIME directamente** mediante web scraping.
Inspeccionando la plataforma se identificó su servicio web interno —el
endpoint `DhimeServicePortal/api/...`— y se escribió un pequeño prototipo que
funcionaba. Pero surgió la duda responsable: hacerlo sin permiso podía afectar
la estabilidad de la plataforma. Así que se hizo lo correcto: **preguntar
antes de avanzar**.

El **16 de febrero de 2025** se presentó una solicitud formal por el sistema
de Peticiones, Quejas y Reclamos (radicado **No. 20259050022884**), pidiendo
documentación técnica de la API, el mecanismo de autenticación y los límites
de uso. La respuesta de la Oficina de Informática del IDEAM (radicado
**No. 20251210031951**, **3 de marzo de 2025**) fue inequívoca:

> *"Por medio del Portal de Consulta y Descarga de Datos Hidrometeorológicos
> DHIME, actualmente no se puede realizar conexión por medio de API's ya que
> podría colapsar las bases de datos. Sin embargo, como medida alternativa
> [...] se ha dispuesto la información [...] en la página
> https://www.datos.gov.co, donde se permite consumir los datos por medio de
> API's."*
> — Wilmer Espitia Muñoz, Jefe Oficina de Informática, IDEAM

Esa puerta cerrada señaló la ventana correcta: el camino oficial para fines
investigativos era la plataforma de **Datos Abiertos Colombia
(www.datos.gov.co)**, montada sobre la tecnología **Socrata**, donde el IDEAM
publica sus datasets masivos. El propio IDEAM adjuntó a su respuesta el manual
para consumirlos.

*Ese PQR cambió el rumbo del proyecto: de "raspar" un portal web a consumir
una API de datos abiertos — más frágil de lo que parecía, pero infinitamente
más correcto.*

> **Nota sobre seguridad (divulgación responsable):** durante esta etapa de
> exploración del portal DHIME se observaron además debilidades estructurales
> y de seguridad en la plataforma. Estos hallazgos se documentan **por
> separado y de forma privada**, con la intención de reportarlos
> responsablemente al IDEAM para que puedan corregirse, antes de cualquier
> divulgación pública. Por ello no se detallan en este repositorio.

## 3. La era artesanal: los primeros scripts de Socrata (2025)

Con el rumbo claro hacia Socrata, los primeros scripts funcionales (linaje
`v1.7`–`v1.9`) hablaban con la API "a mano": **`requests` para las peticiones
HTTP crudas, `csv` de la librería estándar para escribir, `tqdm` para la barra
de progreso y `ThreadPoolExecutor` para paralelizar** — 216 líneas de Python
puro, sin pandas siquiera. Ya estaban las ideas que sobrevivirían todas las
generaciones: descargar por bloques temporales, organizar en carpetas por
territorio, y reintentar ante fallos.

Aquí se aprendieron las primeras **limitaciones de Socrata**: paginación de
máximo 50.000 registros por solicitud, y la necesidad del **App Token** para
no ser estrangulado por las cuotas anónimas.

## 4. La tesis (20 de marzo de 2026)

El trabajo de grado — *"Automatización Inteligente Para La Gestión Visual De
Datos Hídricos Del IDEAM Con Python Y Power BI"* — formalizó el flujo:
**Python extrae de Socrata → CSVs organizados por carpetas → ETL → tablero
interactivo en Power BI**, enfocado en precipitación (~250 millones de
registros disponibles).

Los resultados empíricos hablaron solos:

| Métrica | Manual (DHIME) | Automatizado | Mejora |
|---|---|---|---|
| Un archivo de 5,7 MB | 2,00 min | 0,04 min | **98,19 %** |
| Departamento completo (Tolima: 1.151 archivos, 714 MB, 36 carpetas) | >249 min proyectados | 4,50 min | **~55x** |

Y el Capítulo 5 dejó sembrado el futuro, proponiendo como **Líneas de
Investigación Futura**: bases de datos locales o en la nube con
actualizaciones programadas, superación de los límites de Socrata, ampliación
a más variables hidrometeorológicas, y la evolución hacia *"una plataforma
inteligente de monitoreo y análisis hídrico"*. Todo lo que vino después es la
ejecución de esa agenda.

## 5. La maduración del código: v2.0 → v4.0 → paquete (abril 2026)

En cuestión de semanas el script artesanal se profesionalizó:

| Versión | Novedades | Librerías que entran |
|---|---|---|
| v2.0 (abr) | Manipulación tabular seria y la interfaz visual que define al proyecto | **pandas**, **rich** |
| v3.0 (abr) | Cliente oficial de Socrata y asistente interactivo con menús | **sodapy**, rich.prompt |
| v4.0 (abr) | Modularización (config/core/ui), logging, instalador | estructura de paquete |
| **0.1.0** (28-abr) | Repo público `ideam-data-automator`: src-layout, **floating_id** (SHA-256 para upserts idempotentes), validación **pydantic**, exportación **parquet**, pruebas y CI | pyarrow, pydantic |

En paralelo se desarrolló una **versión con interfaz gráfica (GUI)** en Python,
pensando en que muchos estudiantes no usarían una herramienta de terminal. Era
una buena intuición sobre la accesibilidad —la misma que más adelante llevaría
a la versión web—, aunque esa GUI no tuvo continuidad y quedó archivada en el
legado del proyecto.

## 6. El salto a la web (abril–mayo 2026)

La siguiente ambición: que nadie necesitara instalar nada. Se diseñó una
interfaz en **Figma**, se materializó en **React + Vite**, y se desplegó como
**Cloudflare Worker** en `ideam.sergiobc.com`.

Esta era — "Socrata en vivo" — fue una lección de arquitectura: cada consulta
del usuario viajaba hasta Socrata, y sobrevivir a sus límites exigió una
maquinaria creciente: caché de catálogos en R2, trabajos asíncronos con
Durable Objects, rate limiting, reintentos con backoff. El último commit de
la era (31 de mayo: *"maximize Socrata throughput and harden export jobs"*)
era ya una confesión: **el cuello de botella no era nuestro código, era
depender de Socrata en tiempo real.**

## 7. La gran migración (junio 2026): el espejo propio

La decisión: ejecutar la línea futura de la tesis y montar **una base de
datos propia** con TODO el histórico, alimentada automáticamente.

**La arquitectura** (2–3 de junio): servidor Oracle Cloud (gratuito, 4 OCPU /
24 GB / 200 GB ARM) corriendo PostgreSQL 15 + **TimescaleDB** (hypertable
comprimida + agregados continuos), un ingestor Python que reutiliza el
pipeline de la tesis, una **API FastAPI** que replica los contratos de la
web, y un **Cloudflare Tunnel** que la expone sin abrir un solo puerto.

**La saga del backfill** (3–4 de junio) merece contarse, porque cada fallo
enseñó algo:

1. **El misterio de los timeouts**: las consultas anuales filtradas tardaban
   >10 minutos en responder. Causa: pedir los datos *ordenados* obligaba a
   Socrata a preparar todo antes de transmitir. Quitar el `$order` (el upsert
   idempotente no necesita orden) destrabó las descargas.
2. **El navegador era más listo que nosotros**: la observación empírica de
   que descargar el CSV completo desde el navegador funcionaba ("medio día
   para 70 GB") mientras nuestro código sufría cortes cada ~5 millones de
   filas reveló el patrón culpable: descargar-y-procesar entrelazados dejaba
   el socket ocioso y el servidor cortaba la conexión. Separar la descarga
   (continua, a disco) del procesamiento multiplicó la velocidad **41x**
   (de 108 KB/s a 4,4 MB/s).
3. **El hallazgo no documentado**: Socrata comprime con **gzip** si se le
   pide (`Accept-Encoding`), aunque su documentación no lo menciona. Los
   archivos viajan 5–8x más pequeños: conexiones más cortas que terminan
   antes del corte.
4. **HTTP 200 no significa "sí"**: el endpoint de export masivo (`rows.csv`)
   **ignora los filtros `$where` en silencio** — responde 200 con el dataset
   completo. Una prueba de paridad (¿las mismas 211 filas por ambas vías?) lo
   desenmascaró en un minuto. Lección grabada: *verificar resultados, no
   códigos de estado.*

En el camino, el universo de datos resultó mayor de lo estimado: los conteos
cacheados de Socrata estaban desactualizados, y el total real ronda los
**~745 millones de observaciones** en los 13 datasets (Dirección del Viento
sola: 111 millones que ningún conteo oficial reflejaba).

## 8. Dónde estamos y lo que sigue

Hoy el proyecto es un ecosistema de tres piezas con un mismo corazón:

- **`ideam-data-automator`** — el motor: la CLI de la tesis (ahora con motor
  rápido gzip, validaciones amigables y descargas scriptables) + el ingestor
  del espejo + la API.
- **`ideam-webapp`** — la plataforma web en `ideam.sergiobc.com`.
- El **espejo PostgreSQL/TimescaleDB** llenándose con el histórico completo y
  actualizándose solo cada madrugada.

Lo que viene: el *cutover* de la web al espejo propio, dashboards de
analítica (series, climatologías, tendencias) servidos en milisegundos,
publicación en PyPI, y — fiel al espíritu de la tesis — la posibilidad de
abrir la API a otros investigadores: una pequeña infraestructura de **ciencia
abierta** para los datos del agua en Colombia.

---

*Documento vivo. Última actualización: junio de 2026.*
