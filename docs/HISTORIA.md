# Historia del proyecto

*Crónica de cómo nació y evolucionó esta herramienta: de una inquietud en
clase de Hidráulica a un paquete público que descarga en minutos lo que
manualmente tomaba horas.*

---

## 1. El origen (segundo semestre de 2024): del Canal del Dique a los datos

El proyecto nace hacia **agosto de 2024**, en las aulas de **Ingeniería Civil
de la Universidad de la Costa (CUC)**, durante la asignatura de Hidráulica con
la ingeniera Carol Prada Sánchez, e incubado en el **Semillero de
Investigación en Recursos Hídricos**. El planteamiento inicial era distinto:
*"Modelado y gestión de la sedimentación en el Canal del Dique"*.

Pero al intentar conseguir los datos hidrológicos que ese estudio necesitaba,
apareció el verdadero problema (y la verdadera oportunidad): obtener
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
Inspeccionando la plataforma se identificó su servicio web interno (el
endpoint `DhimeServicePortal/api/...`) y se escribió un pequeño prototipo que
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
> (Wilmer Espitia Muñoz, Jefe Oficina de Informática, IDEAM)

Esa puerta cerrada señaló la ventana correcta: el camino oficial para fines
investigativos era la plataforma de **Datos Abiertos Colombia
(www.datos.gov.co)**, montada sobre la tecnología **Socrata**, donde el IDEAM
publica sus datasets masivos. El propio IDEAM adjuntó a su respuesta el manual
para consumirlos.

*Ese PQR cambió el rumbo del proyecto: de "raspar" un portal web a consumir
una API de datos abiertos, más frágil de lo que parecía, pero infinitamente
más correcta.*

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
de progreso y `ThreadPoolExecutor` para paralelizar**: 216 líneas de Python
puro, sin pandas siquiera. Ya estaban las ideas que sobrevivirían todas las
generaciones: descargar por bloques temporales, organizar en carpetas por
territorio, y reintentar ante fallos.

Aquí se aprendieron las primeras **limitaciones de Socrata**: paginación de
máximo 50.000 registros por solicitud, y la necesidad del **App Token** para
no ser estrangulado por las cuotas anónimas.

## 4. La tesis (20 de marzo de 2026)

El trabajo de grado, *"Automatización Inteligente Para La Gestión Visual De
Datos Hídricos Del IDEAM Con Python Y Power BI"*, formalizó el flujo:
**Python extrae de Socrata → CSVs organizados por carpetas → ETL → tablero
interactivo en Power BI**, enfocado en precipitación (≈282 millones de
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
una buena intuición sobre la accesibilidad (la misma que más adelante llevaría
a la versión web), aunque esa GUI no tuvo continuidad y quedó archivada en el
legado del proyecto.

## 6. De la terminal al navegador (2026)

La siguiente ambición fue que nadie necesitara instalar nada para ver sus
datos. De esa idea nació la **plataforma web del proyecto**,
[ideam.sergiobc.com](https://ideam.sergiobc.com), donde los mismos datos se
exploran desde el navegador con gráficas, mapas y análisis interactivos.

La herramienta local de este repositorio siguió su propio camino de
maduración: publicación en **PyPI**, rediseño completo de la interfaz de
terminal, un motor de descarga notablemente más rápido, validaciones
amigables y el **ejecutable de doble clic** para Windows.

## 7. Dónde estamos

Hoy el proyecto tiene dos puertas de entrada con un mismo corazón:

- **`ideam-data-automator`** (este repositorio): la herramienta local para
  descargar series completas, limpias y organizadas, directo a tu PC.
- **[ideam.sergiobc.com](https://ideam.sergiobc.com)**: la plataforma web
  para consultar y visualizar sin instalar nada.

Fiel al espíritu de la tesis, ambas persiguen la misma promesa: que obtener
datos públicos del agua en Colombia deje de ser difícil.

---

*Documento vivo. Última actualización: julio de 2026.*
