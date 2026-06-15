"""Semáforo de fiabilidad por estación para análisis de frecuencia (Lote 3.2).

Combina en una sola señal verde/amarillo/rojo: longitud del registro de máximos
anuales, completitud de cada año y resultado de las pruebas de estacionariedad.
Degradación por capas con piso en rojo. Función pura; no toca la DB. La consume
app.routers.analytics."""

# Umbral ÚNICO de "año válido": un año cuenta como completo si tiene al menos
# estos días con dato. Decisión del dueño del proyecto: 300 días (auditoría de
# umbrales 2026-06-15). Esta es la fuente de verdad COMPARTIDA por las tres
# rutas que antes lo definían por separado y desincronizaban:
#   - app.routers.analytics.return_periods  (filtro de años válidos)
#   - app.reliability.reliability_report     (completitud, abajo vía _DIAS_MIN_ANIO)
#   - app.services.fiabilidad_batch          (filtro de años válidos)
# Cualquiera de esas debe IMPORTAR esta constante, nunca redefinir el número.
_DIAS_MIN_ANIO_VALIDO = 300

# Alias histórico usado internamente para la completitud; apunta a la constante
# compartida para no divergir (antes era 330 y desincronizaba con las otras).
_DIAS_MIN_ANIO = _DIAS_MIN_ANIO_VALIDO
_LEVELS = ("rojo", "amarillo", "verde")


def _downgrade(level):
    """Baja un nivel; piso en 'rojo'."""
    return _LEVELS[max(0, _LEVELS.index(level) - 1)]


def reliability_report(valid_years, stationarity):
    """valid_years: lista de {year, maximum, days}. stationarity: salida de
    stationarity_report (o None). Devuelve {level, n, completeness,
    incompleteYears, stationary, reasons[]}."""
    n = len(valid_years)
    incomplete = sum(1 for y in valid_years if (y.get("days") or 0) < _DIAS_MIN_ANIO)
    completeness = round(1.0 - incomplete / n, 3) if n else 0.0
    reasons = []

    # 1) base por longitud del registro
    if n >= 30:
        level = "verde"
    elif n >= 15:
        level = "amarillo"
        reasons.append(f"Registro de longitud media ({n} años).")
    else:
        level = "rojo"
        reasons.append(f"Registro corto ({n} años): los Tr altos son poco confiables.")

    # 2) completitud (>=10% de años incompletos baja un nivel)
    if n and incomplete / n >= 0.10:
        level = _downgrade(level)
        reasons.append(
            f"{incomplete} de {n} años ({round(100 * incomplete / n)}%) con registro "
            f"incompleto (<{_DIAS_MIN_ANIO} días): el máximo anual pudo no capturarse.")

    # 3) estacionariedad (tendencia o cambio de régimen baja un nivel)
    stationary = bool(stationarity.get("stationary")) if stationarity else True
    if stationarity and stationarity.get("stationary") is False:
        level = _downgrade(level)
        reasons.append(
            "Las pruebas detectan tendencia o cambio de régimen (serie no "
            "estacionaria); el ajuste de extremos asume estacionariedad.")

    return {"level": level, "n": n, "completeness": completeness,
            "incompleteYears": incomplete, "stationary": stationary, "reasons": reasons}
