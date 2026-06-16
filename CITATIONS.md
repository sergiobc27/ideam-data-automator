# Referencias y fundamentos metodológicos

Este documento respalda académicamente los métodos estadístico-hidrológicos
implementados en la plataforma (curvas IDF, análisis de frecuencia, SPI). Cada
método del código se apoya en una referencia estándar reconocida.

> Nota de honestidad: las referencias se citan por autor/título/año (forma
> verificable en bibliotecas y repositorios). Se evita depender de URLs frágiles.
> Las cifras comparativas tomadas de literatura secundaria se marcan como tales.

## Curvas IDF (Intensidad–Duración–Frecuencia)

- **Vargas, R. & Díaz-Granados, M. (1998).** *Curvas Sintéticas Regionalizadas
  de Intensidad–Duración–Frecuencia para Colombia.* Universidad de los Andes.
  — Referencia nacional de la ecuación `I = K · T^m / D^n`, adoptada por el
  Manual de Drenaje de INVÍAS y citada por el RAS. Es la metodología que replica
  nuestra regresión log-lineal de IDF.
- **INVÍAS (2009).** *Manual de Drenaje para Carreteras.* Instituto Nacional de
  Vías, Colombia. — Períodos de retorno de diseño y exigencia de pruebas de
  bondad de ajuste (Kolmogorov–Smirnov / Chi-cuadrado).
- **Ministerio de Vivienda, Ciudad y Territorio (2017).** *Resolución 330 de
  2017 — Reglamento Técnico del Sector de Agua Potable y Saneamiento Básico
  (RAS), Art. 135 y Tabla 16.* — Períodos de retorno mínimos según tipo de área.

## Análisis de frecuencia de extremos (Gumbel / GEV / Log-Pearson III)

- **Hosking, J. R. M. & Wallis, J. R. (1997).** *Regional Frequency Analysis: An
  Approach Based on L-Moments.* Cambridge University Press. — Base del ajuste de
  Gumbel y GEV por L-momentos implementado en `hydrostats.py`.
- **U.S. Geological Survey (2019).** *Bulletin 17C — Guidelines for Determining
  Flood Flow Frequency.* — Respaldo del ajuste Log-Pearson III (incl. la
  aproximación de Wilson–Hilferty usada en el código).
- **Chow, V. T., Maidment, D. R. & Mays, L. W. (1988).** *Applied Hydrology.*
  McGraw-Hill. — Factor de frecuencia de Gumbel y relación período de
  retorno `T = 1 / (1 − F)`.
- **OMM / WMO.** *Guide to Hydrological Practices (WMO-No. 168)* y *On the
  Statistical Analysis of Series of Observations (WMO-No. 415, 1990).* —
  Recomendación de ≥30 años de registro para cuantiles confiables y uso de
  pruebas de bondad de ajuste (KS, Anderson–Darling).

## Índice de sequía SPI

- **McKee, T. B., Doesken, N. J. & Kleist, J. (1993).** *The relationship of
  drought frequency and duration to time scales.* 8th Conference on Applied
  Climatology, AMS. — Definición original del SPI.
- **OMM (2012).** *Standardized Precipitation Index User Guide (WMO-No. 1090).*

> **Nota de método (SPI):** la implementación es una **variante no-paramétrica**
> (percentil empírico de Hazen → normal inversa), no el SPI-gamma canónico de
> McKee. Es una aproximación válida y robusta a colas, pero debe reportarse como
> tal en la tesis para no inducir a error.

## Calidad de los datos de origen

- **IDEAM.** *Datos Hidrometeorológicos Crudos — Red de Estaciones* (datos
  abiertos, Ley 1712/2014). — Los datos son **crudos, no certificados DHIME**;
  pueden requerir análisis de homogeneidad/doble masa. Este límite debe quedar
  explícito en la tesis (las diferencias frente a curvas oficiales se explican
  en parte por esto).

## Qué está implementado en el código (verificado)

Para evitar reclamar trabajo no hecho — y para no rehacer lo ya hecho — se deja
constancia de que el código **ya** incluye: ajuste Gumbel/GEV/LP3 por L-momentos
con **selección por AIC**, pruebas de **bondad de ajuste KS y Anderson–Darling**,
**bandas de confianza por bootstrap (~90%)**, y **advertencia de registro corto
(<15 años)**. Lo que falta es **externo y documental**: la comparación
cuantitativa 1‑a‑1 contra curvas IDF oficiales del IDEAM (ver
`docs/validacion/PROCEDIMIENTO-VALIDACION-IDF-EXTERNA.md`).
