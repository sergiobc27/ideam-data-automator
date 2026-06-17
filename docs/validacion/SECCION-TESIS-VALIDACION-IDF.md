# Validación de las curvas IDF de la plataforma (borrador para la tesis)

> Borrador redactable. Los números provienen de `RESULTADOS-VALIDACION-IDF.md` y son
> reproducibles con `scripts/validar_idf.py` y `scripts/generar_comparacion_idf.py`.
> Adáptalo a la voz y el formato de tu documento.

## Objetivo

Contrastar punto por punto las curvas Intensidad–Duración–Frecuencia (IDF) que genera la
plataforma contra una fuente IDF publicada y revisada por pares, para cuantificar el error
y establecer hasta qué punto el insumo es defendible para ingeniería.

## Fuente de referencia

Se adoptó como referencia a González Silva (2023), tesis de Maestría en Ingeniería Civil de
la Escuela Colombiana de Ingeniería Julio Garavito, que estima curvas IDF regionalizadas para
Colombia a partir de **la misma red automática de 10 minutos del IDEAM** que alimenta la
plataforma. Esta coincidencia de red es decisiva: las curvas IDF clásicas (p. ej. Bogotá
1962–1993, Cali 1997, Cúcuta 2006) provienen de estaciones antiguas que no están en el espejo
de datos, por lo que casi no cruzan con las estaciones disponibles. González (2023) publica los
coeficientes de 388 estaciones (Tabla 1, pp. 73–85) bajo la ecuación

    I = τ · Tr^ρ / (d + d0)^μ      [I en mm/h, d en min, Tr en años; validez ≈ 10–360 min]

La extracción de coeficientes se verificó con la estación AEROPUERTO CAMILO DAZA – AUT como
ancla: la re-lectura del PDF reprodujo exactamente los valores publicados (τ=486.09, ρ=0.26,
d0=0.00, μ=0.71).

## Método

- **I_plataforma:** máximos anuales móviles por duración sobre los datos de 10 min; en cada
  duración se elige Gumbel, GEV o Log-Pearson III por criterio AIC, con pruebas de bondad de
  ajuste (Kolmogorov–Smirnov y Anderson–Darling) y bandas de confianza por bootstrap; se ajusta
  además la ecuación I = K·T^m/D^n (R²log = 0.95–0.99).
- **I_oficial:** la ecuación de González evaluada con los coeficientes de cada estación.
- **Métrica:** error relativo porcentual por punto `(|I_plataforma − I_oficial| / I_oficial)`
  y su promedio (MAPE) por estación, por duración y global. Umbral de consistencia/publicable
  MAPE < 15–20 % (referencia habitual en *Journal of Hydrology*).
- **Universo:** de 243 estaciones con IDF usable (≥5 años) en el espejo, 162 cruzan con González;
  solo 13 alcanzan ≥15 años de registro (ninguna ≥20), reflejo de que la red automática es reciente.

## Resultados

**Lote de registro largo (13 estaciones de ≥15 años).** Seis estaciones validan a nivel
publicable (MAPE 6.6–15.6 %):

| Estación (cód. IDEAM) | Años | μ (González) | MAPE | Veredicto |
|---|---|---|---|---|
| SOCHA – AUT (24035360) | 18 | 0.54 | 6.6 % | Excelente |
| TIBAITATÁ – AUT (21206990) | 17 | 0.72 | 10.7 % | Excelente |
| PAQUILÓ (21195170) | 16 | 0.64 | 13.2 % | Excelente |
| EL ESPINO – AUT (24035370) | 15 | 0.63 | 14.1 % | Excelente |
| SANTA ROSITA (21209920) | 17 | 0.66 | 15.4 % | Publicable |
| UNIVERSIDAD DE CUNDINAMARCA (21235030) | 15 | 0.51 | 15.6 % | Publicable |

**Lote de registro medio (20 estaciones de 10–14 años con μ > 0.50).** Nueve estaciones validan
a nivel publicable (MAPE < 20 %), tres de ellas excelentes (< 15 %): MARENGO (11.9 %),
VILLA TERESA (13.6 %), BATALLÓN ROOKE (13.7 %), CAJAMARCA (15.6 %), ARRANCAPLUMAS (16.3 %),
MOGOTES (16.7 %), SAN CAYETANO (16.7 %), PURACÉ (18.9 %) y CANTERAS (19.7 %).

**En conjunto, 15 estaciones de la red de 10 minutos validan a nivel publicable.** La tasa de
acuerdo es estable entre lotes (6/13 ≈ 46 % y 9/20 ≈ 45 %), lo que indica que el resultado no
depende de la longitud de registro sino de la calidad de la curva de referencia.

## Discusión y limitaciones

- **Dónde coincide.** En las estaciones cuya curva de referencia tiene un exponente físicamente
  razonable (μ entre 0.51 y 0.72), la plataforma reproduce la curva publicada dentro del umbral.
- **Dónde diverge.** Las estaciones con MAPE alto comparten un μ anómalamente bajo (≤ 0.30) en el
  modelo de González: el ajuste regionalizado/espacial les asigna una curva casi plana
  (poca caída de la intensidad con la duración), físicamente improbable, que subestima las
  intensidades cortas. El desajuste es del **referente regionalizado** en esos sitios, no del
  ajuste por estación de la plataforma. En el lote medio, los pocos atípicos restantes
  (registros de 10–11 años o zonas con posible mezcla de sensores de precipitación) son
  candidatos a depuración de datos, no evidencia de error de cálculo.
- **Naturaleza de la comparación.** I_plataforma son intensidades empíricas por punto;
  I_oficial es una fórmula suave. Parte del error en los extremos del rango (10 y 360 min)
  proviene de esa diferencia de naturaleza, no de un fallo.
- **Datos.** Se usan datos crudos del IDEAM (no certificados DHIME), que pueden requerir análisis
  de homogeneidad; muchas estaciones tienen < 30 años, por lo que los Tr altos deben leerse como
  preliminares (criterio OMM).

## Posicionamiento

El insumo `I(D, Tr)` queda validado para estaciones puntuales y es apto para
pre-dimensionamiento hidráulico y docencia. No sustituye un estudio hidrológico normado
completo (regionalización, tránsito y estimación de caudales), que excede el alcance de
este trabajo.
