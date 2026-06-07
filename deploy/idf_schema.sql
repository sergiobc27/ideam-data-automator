-- ============================================================
-- IDF (Intensidad-Duración-Frecuencia) — precómputo de máximos anuales móviles
-- ------------------------------------------------------------
-- Los datos de precipitación del IDEAM vienen cada 10 min (estaciones
-- automáticas). Para curvas IDF REALES se necesita, por año, la lluvia máxima
-- acumulada en ventanas móviles de cada duración de diseño. Ese cálculo (window
-- RANGE sobre ~1M filas/estación) es caro (~decenas de s), así que se PRECOMPUTA
-- aquí una vez por estación y el delta diario refresca el año en curso. El
-- endpoint /api/analytics/idf solo lee esta tabla y ajusta Gumbel (instantáneo).
-- Duraciones: múltiplos de 10 min (la resolución del dato).
-- ============================================================

CREATE TABLE IF NOT EXISTS idf_max_anual (
    codigoestacion text   NOT NULL,
    anio           int    NOT NULL,
    dur_min        int    NOT NULL,
    max_mm         real   NOT NULL,
    PRIMARY KEY (codigoestacion, anio, dur_min)
);
CREATE INDEX IF NOT EXISTS ix_idf_estacion ON idf_max_anual (codigoestacion);

-- Control: qué estaciones se han procesado, cuántos años válidos, cuándo.
CREATE TABLE IF NOT EXISTS idf_estado (
    codigoestacion text PRIMARY KEY,
    anios_validos  int,
    obs_total      bigint,
    computed_at    timestamptz NOT NULL DEFAULT now()
);

-- Calcula (o recalcula) los máximos anuales móviles de UNA estación.
-- Devuelve el número de años válidos insertados. Idempotente: borra y reinserta.
-- Un año es "válido" si tiene >= p_min_obs observaciones (un año completo a
-- 10 min son ~52.560; el umbral por defecto ~la mitad cubre la temporada).
CREATE OR REPLACE FUNCTION idf_compute_station(p_codigo text, p_min_obs int DEFAULT 25000)
RETURNS int AS $$
DECLARE
    v_anios int;
BEGIN
    DELETE FROM idf_max_anual WHERE codigoestacion = p_codigo;

    INSERT INTO idf_max_anual (codigoestacion, anio, dur_min, max_mm)
    SELECT p_codigo, a.anio, d.dur_min, d.max_mm
    FROM (
        SELECT anio,
               max(d10)   AS m10,   max(d20)   AS m20,   max(d30)   AS m30,
               max(d60)   AS m60,   max(d120)  AS m120,  max(d180)  AS m180,
               max(d360)  AS m360,  max(d720)  AS m720,  max(d1440) AS m1440,
               count(*)   AS n_obs
        FROM (
            SELECT extract(year FROM (fechaobservacion AT TIME ZONE 'UTC'))::int AS anio,
                   sum(valorobservado) OVER w10   AS d10,
                   sum(valorobservado) OVER w20   AS d20,
                   sum(valorobservado) OVER w30   AS d30,
                   sum(valorobservado) OVER w60   AS d60,
                   sum(valorobservado) OVER w120  AS d120,
                   sum(valorobservado) OVER w180  AS d180,
                   sum(valorobservado) OVER w360  AS d360,
                   sum(valorobservado) OVER w720  AS d720,
                   sum(valorobservado) OVER w1440 AS d1440
            FROM observaciones
            WHERE source_dataset_id = 's54a-sgyg'
              AND codigoestacion = p_codigo
              AND valorobservado >= 0           -- saneo: descarta centinelas negativos
            -- Ventanas por NÚMERO DE INTERVALOS de 10 min (ROWS), no por tiempo
            -- (RANGE): PG calcula ROWS con suma deslizante incremental O(filas),
            -- ~constante sin importar la duración; RANGE temporal era O(filas ×
            -- tamaño_ventana) y reventaba en estaciones grandes. Para datos
            -- regulares de 10 min es equivalente (método estándar en análisis de
            -- pluviógrafos: máximo móvil de N intervalos). dur_min = N × 10.
            WINDOW
              w10   AS (ORDER BY fechaobservacion ROWS BETWEEN 0   PRECEDING AND CURRENT ROW),
              w20   AS (ORDER BY fechaobservacion ROWS BETWEEN 1   PRECEDING AND CURRENT ROW),
              w30   AS (ORDER BY fechaobservacion ROWS BETWEEN 2   PRECEDING AND CURRENT ROW),
              w60   AS (ORDER BY fechaobservacion ROWS BETWEEN 5   PRECEDING AND CURRENT ROW),
              w120  AS (ORDER BY fechaobservacion ROWS BETWEEN 11  PRECEDING AND CURRENT ROW),
              w180  AS (ORDER BY fechaobservacion ROWS BETWEEN 17  PRECEDING AND CURRENT ROW),
              w360  AS (ORDER BY fechaobservacion ROWS BETWEEN 35  PRECEDING AND CURRENT ROW),
              w720  AS (ORDER BY fechaobservacion ROWS BETWEEN 71  PRECEDING AND CURRENT ROW),
              w1440 AS (ORDER BY fechaobservacion ROWS BETWEEN 143 PRECEDING AND CURRENT ROW)
        ) movil
        GROUP BY anio
    ) a
    CROSS JOIN LATERAL (VALUES
        (10, a.m10), (20, a.m20), (30, a.m30), (60, a.m60), (120, a.m120),
        (180, a.m180), (360, a.m360), (720, a.m720), (1440, a.m1440)
    ) AS d(dur_min, max_mm)
    WHERE a.n_obs >= p_min_obs
      AND d.max_mm IS NOT NULL
      AND d.max_mm >= 0;  -- sumas de no-negativos: finitas por construcción

    SELECT count(DISTINCT anio) INTO v_anios FROM idf_max_anual WHERE codigoestacion = p_codigo;

    INSERT INTO idf_estado (codigoestacion, anios_validos, obs_total, computed_at)
    VALUES (
        p_codigo, v_anios,
        (SELECT count(*) FROM observaciones WHERE source_dataset_id = 's54a-sgyg' AND codigoestacion = p_codigo),
        now()
    )
    ON CONFLICT (codigoestacion) DO UPDATE
        SET anios_validos = EXCLUDED.anios_validos,
            obs_total = EXCLUDED.obs_total,
            computed_at = now();

    RETURN v_anios;
END;
$$ LANGUAGE plpgsql;
