# Procedimiento de validación externa 1-a-1 de curvas IDF

Estado: **procedimiento listo; pendiente de ejecutar** cuando se obtengan las
curvas IDF oficiales de referencia. Complementa
[VALIDACION-IDF-2026-06-07.md](VALIDACION-IDF-2026-06-07.md) (validación interna
y cualitativa, ya hecha) y [VIABILIDAD-NORMATIVA-2026-06-07.md](VIABILIDAD-NORMATIVA-2026-06-07.md)
(posicionamiento normativo).

## Qué ya está hecho (no rehacer)

Verificado en el código (`api/app/services/hydrostats.py`, `api/app/routers/analytics.py`):

- Ajuste **Gumbel / GEV / Log-Pearson III** por L-momentos, con **selección
  automática por AIC**.
- Pruebas de **bondad de ajuste**: Kolmogorov–Smirnov y Anderson–Darling.
- **Bandas de confianza ~90%** por bootstrap para los cuantiles.
- **Advertencia de registro corto** (<15 años).
- Regresión IDF log-lineal `I = K · T^m / D^n` con `R²` en espacio log.

→ Por tanto, NO hay que "implementar bondad de ajuste / intervalos de confianza":
ya existen. La brecha es **externa**.

## La única brecha real: comparación cuantitativa contra curvas oficiales

### Insumo que debe conseguir Sergio (bloqueante)

≥10 estaciones con **curvas IDF oficiales publicadas** (IDEAM
`archivo.ideam.gov.co/curvas-idf`, o tesis universitarias con coeficientes
`K, m, n` o tablas `I(D, Tr)`). Candidatas con cobertura geográfica:
Bogotá, Cartagena (Aeropuerto Rafael Núñez), Tunja, Medellín, Cúcuta, Santa Marta.

### Procedimiento

1. **Estaciones**: ≥10 con IDF oficial y ≥15 años de registro en nuestro espejo.
2. **Duraciones**: 10, 20, 30, 60, 120, 180, 360, 1440 min.
3. **Períodos de retorno (Tr)**: 2, 5, 10, 25, 50, 100 años.
4. Para cada `(estación, duración, Tr)`: tomar `I_oficial` y `I_plataforma`.
5. **Error relativo** = `|I_plataforma − I_oficial| / I_oficial × 100 %`.
6. Reportar **MAPE** por estación y por duración.
7. **Umbral**: MAPE **< 15–20 %** se considera consistente/publicable
   (estándar en *Journal of Hydrology*). MAPE mayor → investigar causa
   (datos crudos vs DHIME, longitud de registro, distribución elegida).

### Cómo ejecutarlo (LISTO "para el clic")

Ya está todo cableado; solo falta llenar los datos oficiales:

1. **Llena la plantilla** [`idf-comparacion-PLANTILLA.csv`](idf-comparacion-PLANTILLA.csv)
   (cópiala a, p.ej., `mi-comparacion.csv`). Columnas:
   `estacion,duracion_min,Tr_anios,I_oficial_mmh,I_plataforma_mmh`.
   - `I_oficial_mmh`: de la curva IDF oficial (PDF del IDEAM o tesis).
   - `I_plataforma_mmh`: del panel IDF de la web (ideam.sergiobc.com) para esa
     estación/duración/Tr.
   - Puedes llenar por partes: las filas con celdas vacías se omiten.
2. **Corre el validador** (sin dependencias externas):
   ```bash
   python scripts/validar_idf.py mi-comparacion.csv
   ```
   Imprime el error relativo por fila y el **MAPE** por estación, por duración y
   global, con veredicto (EXCELENTE <15% · PUBLICABLE <20% · REVISAR ≥20%).
3. Pega la tabla de resultados en la tesis.

El cálculo del MAPE está cubierto por tests (`tests/test_validar_idf.py`).

### Tabla de resultados (plantilla)

| Estación | n (años) | Duración | Tr | I_oficial (mm/h) | I_plataforma (mm/h) | Error rel. % |
|----------|----------|----------|----|------------------|---------------------|--------------|
| …        | …        | …        | …  | …                | …                   | …            |

## Posicionamiento honesto (para la defensa)

Cumplimiento normativo (resumen; detalle en VIABILIDAD-NORMATIVA):

- **RAS 0330/2017 Art. 135** — Tr mínimos: ✅ cubierto · regionalización: ❌ ·
  caudal Q (método racional): ❌ (fuera de alcance, es insumo de lluvia).
- **INVÍAS 2009** — bondad de ajuste KS/AD: ✅ · reducción por área (ARF): ❌.
- **OMM (30 años)**: ⚠️ muchas estaciones tienen <30 años → reportar IC y marcar
  Tr altos como preliminares.

**Posicionamiento:** insumo hidrológico `I(D, Tr)` validado para estaciones
puntuales, apto para **pre-dimensionamiento y docencia**; **no sustituye** un
estudio hidrológico normado completo (regionalización + tránsito + caudales).

## Limitaciones documentadas

- Datos **crudos del IDEAM** (no DHIME certificados): pueden requerir análisis de
  homogeneidad / doble masa.
- Techo físico en lectura (precipitación) es **contención no destructiva**, no
  saneo de origen (ver memoria del proyecto, "Fix #2").
- Método de máximos anuales por ventanas móviles: caveat de contigüidad (ROWS)
  verificado a 1440 min; duraciones cortas (10–60 min) conviene revisarlas.
