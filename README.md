# IDEAM Data Automator

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20562858.svg)](https://doi.org/10.5281/zenodo.20562858)
[![PyPI](https://img.shields.io/pypi/v/ideam-data-automator.svg)](https://pypi.org/project/ideam-data-automator/)
[![Python](https://img.shields.io/pypi/pyversions/ideam-data-automator.svg)](https://pypi.org/project/ideam-data-automator/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/sergiobc27/ideam-data-automator/blob/main/LICENSE)

Herramienta en Python para **extraer, validar, organizar y descargar** datos
hidrometeorológicos del IDEAM publicados en Socrata / Datos Abiertos Colombia
(`www.datos.gov.co`), directamente a tu PC.

Desarrollada como Trabajo de Grado de Ingeniería Civil en la Universidad de la
Costa (CUC), Barranquilla. Automatiza en minutos lo que manualmente toma horas:
consultar estación por estación en los portales del IDEAM, descargar, limpiar
y organizar los archivos.

> **Guías visuales**: si prefieres ver el proceso completo en una sola página,
> descarga la [infografía del flujo local](https://github.com/sergiobc27/ideam-data-automator/blob/main/docs/infografias/infografia-flujo-local.pdf)
> o el [instructivo paso a paso](https://github.com/sergiobc27/ideam-data-automator/blob/main/docs/infografias/instructivo-local.pdf) (PDF).
> La versión web de la plataforma vive en [ideam.sergiobc.com](https://ideam.sergiobc.com).

## Cómo funciona

<p align="center">
  <img src="https://raw.githubusercontent.com/sergiobc27/ideam-data-automator/main/docs/img/diagrama-como-funciona.svg" alt="Diagrama de 4 pasos: datos.gov.co, valida y limpia, organiza en tu PC, y resumen de cobertura" width="880">
</p>

## Guía paso a paso: tus primeros datos en 5 minutos

¿Primera vez? Sigue estos pasos tal cual. No necesitas saber programar.

> **¿Sin Python y sin comandos?** También hay un **ejecutable de doble clic
> para Windows**: descarga `IDEAM-Data-Automator.exe` desde la
> [página de Releases](https://github.com/sergiobc27/ideam-data-automator/releases),
> ábrelo con doble clic y saltas directo al *Paso 0* de abajo. Si Windows
> muestra el aviso azul de protección, pulsa "Más información" y luego
> "Ejecutar de todas formas" (aparece con cualquier programa sin firma comercial).

### Antes de empezar (solo la primera vez)

<p align="center">
  <img src="https://raw.githubusercontent.com/sergiobc27/ideam-data-automator/main/docs/img/diagrama-pasos-instalacion.svg" alt="Instalación en 3 pasos: instala Python marcando Add python.exe to PATH, pega el comando python -m pip install ideam-data-automator en PowerShell, y abre la herramienta con ideam-socrata tui" width="880">
</p>

1. **Instala Python** (3.10 o superior) desde
   [python.org/downloads](https://www.python.org/downloads/). En Windows,
   marca la casilla **"Add Python to PATH"** en la primera pantalla del instalador.
2. **Abre una terminal**: presiona la tecla Windows, escribe `PowerShell` y
   presiona Enter.
3. **Instala la herramienta**: copia y pega esta línea y presiona Enter:

   ```powershell
   python -m pip install ideam-data-automator
   ```

Y ya está. No hace falta nada más.

> **¿Prefieres pipx?** Si ya usas `pipx` para tus herramientas de Python,
> `pipx install ideam-data-automator` también funciona y deja el comando
> `ideam-socrata` aislado en su propio entorno. Si aún no lo tienes, instálalo
> con `python -m pip install --user pipx` y luego `python -m pipx ensurepath`
> (anteponer `python -m` evita el clásico "no se reconoce como comando" de
> Windows). Cierra y abre la terminal después. Ojo: con pipx el programa vive
> aislado, así que la forma `python -m ideam_socrata tui` de abajo no aplica;
> usa siempre `ideam-socrata tui`.

### El recorrido, pantalla por pantalla

**Abre la herramienta**: escribe esto en la terminal y presiona Enter:

```powershell
ideam-socrata tui
```

> **¿Dice "ideam-socrata no se reconoce como comando"?** Pasa en algunos
> Windows cuando la carpeta de scripts de Python no queda en el PATH. Usa esta
> forma equivalente, que funciona siempre:
> ```powershell
> python -m ideam_socrata tui
> ```
> (Sirve para todos los comandos de esta guía: `python -m ideam_socrata` seguido
> de lo mismo. Requiere la versión 1.2.1 o superior; actualiza con
> `python -m pip install -U ideam-data-automator`.)

**Paso 0 · Acepta los términos**

> **Qué hacer**: lee las condiciones de uso (datos abiertos del IDEAM, uso
> académico) y haz clic en el botón verde **"Acepto los términos"**.

<p align="center">
  <img src="https://raw.githubusercontent.com/sergiobc27/ideam-data-automator/main/docs/img/tui-0-acuerdo.svg" alt="Pantalla de acuerdo de uso de la TUI" width="760">
</p>

**Paso 1 · Elige la variable**

> **Qué hacer**: escribe el nombre de lo que buscas (por ejemplo
> `precipitación`), baja con la flecha ↓ hasta la opción que quieres y
> presiona **Enter**.

Hay 21 variables disponibles: precipitación, niveles de río y mar,
temperaturas, viento, humedad, presión, calidad de aire/agua, y más.

<p align="center">
  <img src="https://raw.githubusercontent.com/sergiobc27/ideam-data-automator/main/docs/img/tui-1-variable.svg" alt="Paso 1 de la TUI: selección de variable" width="760">
</p>

**Paso 2 · Marca los departamentos**

> **Qué hacer**: muévete con las flechas ↑↓ y presiona **Espacio** para
> marcar con ✓ cada departamento que te interese (puedes marcar varios).
> Al terminar, haz clic en **"Continuar"**.

Si necesitas afinar más, ahí mismo hay filtros avanzados: zona hidrográfica,
municipio, categoría de estación, o códigos de estación escritos a mano.

<p align="center">
  <img src="https://raw.githubusercontent.com/sergiobc27/ideam-data-automator/main/docs/img/tui-2-deptos.svg" alt="Paso 2 de la TUI: selección de departamentos" width="760">
</p>

**Paso 3 · Revisa los años**

> **Qué hacer**: la herramienta consulta cuántos datos existen de verdad para
> tu selección (estaciones y rango real de fechas). Revisa el rango de años
> propuesto, ajústalo si quieres, y presiona **Descargar**.

<p align="center">
  <img src="https://raw.githubusercontent.com/sergiobc27/ideam-data-automator/main/docs/img/tui-3-anios.svg" alt="Paso 3 de la TUI: selección de años" width="760">
</p>

**Paso 4 · Espera la descarga**

> **Qué hacer**: nada, solo espera. Verás el progreso en vivo (filas por
> segundo y tiempo restante). Al terminar, presiona la tecla **O** para abrir
> la carpeta con tus archivos, o **N** para hacer otra consulta.

<p align="center">
  <img src="https://raw.githubusercontent.com/sergiobc27/ideam-data-automator/main/docs/img/tui-4-descarga.svg" alt="Paso 4 de la TUI: descarga con progreso en vivo" width="760">
</p>

**¿Y ahora?** Tus archivos quedaron en `Documentos\IDEAM_Data\`, organizados
por departamento y municipio, listos para abrir en Excel (CSV) o en
PowerBI/pandas (Parquet). El archivo `RESUMEN_*.txt` te dice cuántos datos
trajo cada estación.

> ¿Prefieres no usar la terminal para nada? En
> [ideam.sergiobc.com](https://ideam.sergiobc.com) está la versión web: los
> mismos datos desde el navegador, sin instalar nada.

## Otros modos de uso

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

Para la herramienta basta con un solo `SOCRATA_APP_TOKEN`; el resto de
variables son ajustes finos opcionales.

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
tests/                 # Pruebas unitarias
docs/                  # Guías e infografías
```

## ¿Y la versión web?

Este repositorio contiene la **herramienta local**: la instalas y los datos
llegan directo a tu computador. Como parte del mismo proyecto también existe
[**ideam.sergiobc.com**](https://ideam.sergiobc.com), la plataforma web donde
puedes explorar los mismos datos desde el navegador (gráficas, mapas y más)
sin instalar nada. Usa la que se acomode a tu trabajo: la local para
descargar series completas a tus carpetas, la web para consultar y visualizar.

## Documentación

| Documento | Qué contiene |
| --- | --- |
| [Infografía del flujo local](https://github.com/sergiobc27/ideam-data-automator/blob/main/docs/infografias/infografia-flujo-local.pdf) | El proceso completo de descarga en una página visual |
| [Instructivo paso a paso](https://github.com/sergiobc27/ideam-data-automator/blob/main/docs/infografias/instructivo-local.pdf) | Guía de instalación y uso con capturas |
| [docs/HISTORIA.md](https://github.com/sergiobc27/ideam-data-automator/blob/main/docs/HISTORIA.md) | Historia y evolución del proyecto |

## Pruebas

```powershell
python -m pytest tests/
```

## Cita académica

Si usas esta herramienta en tu investigación, cítala con los metadatos de
[`CITATION.cff`](https://github.com/sergiobc27/ideam-data-automator/blob/main/CITATION.cff) (GitHub muestra el botón *"Cite this repository"*).

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
