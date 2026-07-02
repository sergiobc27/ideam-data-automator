# Referencias y fundamentos metodológicos

Este documento respalda académicamente los métodos estadístico-hidrológicos
implementados en este repositorio (curvas IDF, análisis de frecuencia, SPI).
Cada método del código se apoya en una referencia estándar reconocida.

> Nota de honestidad: las referencias se citan por autor/título/año (forma
> verificable en bibliotecas y repositorios). Se evita depender de URLs
> frágiles. Las cifras comparativas tomadas de literatura secundaria se marcan
> como tales.

> **Fuente de verdad de citas.** La bibliografía citable que ve el público en
> la web vive en el repositorio del frontend (`sergiobc27/website`, archivo
> `src/app/lib/referencias.ts`) y es la que manda para todo texto visible.
> Este documento respalda el código de ESTE repositorio (paquete Python y API
> FastAPI) y se mantiene alineado con esa lista. Dos fuentes de este documento
> (WMO-No. 415 y WMO-No. 1090) no aparecen en la lista de la web porque
> respaldan únicamente código de la API, no vistas del frontend.

## Curvas IDF (Intensidad-Duración-Frecuencia)

- **Vargas M., R., & Díaz-Granados O., M. (1998).** *Curvas sintéticas
  regionalizadas de intensidad-duración-frecuencia para Colombia.* En Memorias
  del XIII Seminario Nacional de Hidráulica e Hidrología. Sociedad Colombiana
  de Ingenieros. Referencia nacional de la ecuación `I = K · T^m / D^n`,
  adoptada por el Manual de Drenaje de INVÍAS y citada por el RAS. Es la
  metodología que replica nuestra regresión log-lineal de IDF.
- **INVÍAS (2009).** *Manual de Drenaje para Carreteras.* Instituto Nacional de
  Vías, Colombia. Períodos de retorno de diseño y exigencia de pruebas de
  bondad de ajuste (Kolmogorov-Smirnov / Chi-cuadrado).
- **Ministerio de Vivienda, Ciudad y Territorio (2017).** *Resolución 330 de
  2017: Reglamento Técnico del Sector de Agua Potable y Saneamiento Básico
  (RAS), Art. 135 y Tabla 16.* Períodos de retorno mínimos según tipo de área.

## Análisis de frecuencia de extremos (Gumbel / GEV / Log-Pearson III)

- **Hosking, J. R. M. & Wallis, J. R. (1997).** *Regional Frequency Analysis:
  An Approach Based on L-Moments.* Cambridge University Press. Base del ajuste
  de Gumbel y GEV por L-momentos implementado en `hydrostats.py`.
- **Interagency Advisory Committee on Water Data (1982).** *Guidelines for
  Determining Flood Flow Frequency. Bulletin 17B.* U.S. Geological Survey,
  Office of Water Data Coordination. Respaldo del ajuste Log-Pearson III por
  momentos de los logaritmos, incluida la aproximación de Wilson-Hilferty del
  factor de frecuencia usada en el código (`hydrostats.py`). Nota: existe una
  revisión posterior (Bulletin 17C, USGS 2019, que introduce el método EMA);
  el código implementa el procedimiento clásico del 17B, por eso se cita 17B
  y no 17C.
- **Chow, V. T., Maidment, D. R. & Mays, L. W. (1988).** *Applied Hydrology.*
  McGraw-Hill. Factor de frecuencia de Gumbel y relación período de retorno
  `T = 1 / (1 − F)`.
- **OMM / WMO (2008).** *Guide to Hydrological Practices (WMO-No. 168)*,
  6.ª edición. Recomendación de registros largos (del orden de 30 años o más)
  para cuantiles confiables y uso de pruebas de bondad de ajuste.
- **Sneyers, R. (1990).** *On the Statistical Analysis of Series of
  Observations.* Technical Note No. 143, WMO-No. 415. Organización
  Meteorológica Mundial. Fundamento de las pruebas estadísticas sobre series
  de observaciones aplicadas en la API: análisis de tendencia y
  estacionariedad (Mann-Kendall, Pettitt) en `stationarity.py`.

## Índice de sequía SPI

- **McKee, T. B., Doesken, N. J. & Kleist, J. (1993).** *The relationship of
  drought frequency and duration to time scales.* 8th Conference on Applied
  Climatology, AMS. Definición original del SPI.
- **Organización Meteorológica Mundial (2012).** *Standardized Precipitation
  Index User Guide* (M. Svoboda, M. Hayes y D. Wood). WMO-No. 1090.

> **Nota de método (SPI):** la implementación es una **variante
> no-paramétrica** (percentil empírico de Hazen y transformación normal
> inversa), no el SPI-gamma canónico de McKee. Es una aproximación válida y
> robusta a colas, pero debe reportarse como tal en la tesis para no inducir
> a error.

## Calidad de los datos de origen

- **IDEAM.** *Datos Hidrometeorológicos Crudos: Red de Estaciones* (datos
  abiertos, Ley 1712 de 2014). Los datos son **crudos, no certificados
  DHIME**; pueden requerir análisis de homogeneidad/doble masa. Este límite
  debe quedar explícito en la tesis (las diferencias frente a curvas oficiales
  se explican en parte por esto).

## Qué está implementado en el código (verificado)

Para evitar reclamar trabajo no hecho (y para no rehacer lo ya hecho) se deja
constancia de que el código **ya** incluye: ajuste Gumbel/GEV/LP3 por
L-momentos con **selección por AIC**, pruebas de **bondad de ajuste KS y
Anderson-Darling**, **bandas de confianza por bootstrap (~90%)**, y
**advertencia de registro corto (<15 años)**. Lo que falta es **externo y
documental**: la comparación cuantitativa 1 a 1 contra curvas IDF oficiales
del IDEAM (ver `docs/validacion/PROCEDIMIENTO-VALIDACION-IDF-EXTERNA.md`).
