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
-- p_min_obs 30000 ≈ 57% de un año a 10 min (52.560): balance entre rigor (más
-- que el 48% original que la auditoría objetó) y cobertura de la red (el 76%
-- dejaba sin años válidos al grueso de estaciones del IDEAM, que tienen huecos
-- frecuentes). Cota superior física de 60 mm/10min descarta picos/centinelas
-- (#5). Rejilla densa + ROWS = exactitud temporal sin el sesgo de huecos del
-- lado inseguro (#2). Lock por estación evita choques batch+refresh (#8).
CREATE OR REPLACE FUNCTION idf_compute_station(p_codigo text, p_min_obs int DEFAULT 30000)
RETURNS int AS $$
DECLARE
    v_anios int;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('idf:' || p_codigo));
    DELETE FROM idf_max_anual WHERE codigoestacion = p_codigo;

    INSERT INTO idf_max_anual (codigoestacion, anio, dur_min, max_mm)
    SELECT p_codigo, a.anio, d.dur_min, d.max_mm
    FROM (
        SELECT anio,
               max(d10)   AS m10,   max(d20)   AS m20,   max(d30)   AS m30,
               max(d60)   AS m60,   max(d120)  AS m120,  max(d180)  AS m180,
               max(d360)  AS m360,  max(d720)  AS m720,  max(d1440) AS m1440,
               sum(es_real::int) AS n_obs,       -- observaciones REALES del año
               sum(val)          AS total_anual  -- lámina anual (cordura física)
        FROM (
            SELECT extract(year FROM (slot AT TIME ZONE 'UTC'))::int AS anio,
                   val,
                   sum(val) OVER w10   AS d10,
                   sum(val) OVER w20   AS d20,
                   sum(val) OVER w30   AS d30,
                   sum(val) OVER w60   AS d60,
                   sum(val) OVER w120  AS d120,
                   sum(val) OVER w180  AS d180,
                   sum(val) OVER w360  AS d360,
                   sum(val) OVER w720  AS d720,
                   sum(val) OVER w1440 AS d1440,
                   es_real
            -- Rejilla DENSA de 10 min (huecos = 0): hace que las ventanas ROWS
            -- de N intervalos cubran exactamente N×10 min de tiempo real, sin
            -- saltar huecos. Combina la exactitud temporal de RANGE con la
            -- velocidad O(filas) de ROWS (RANGE puro tardaba 6min/estación
            -- grande). Huecos cuentan como 0 → del lado SEGURO de diseño
            -- (nunca sobreestima). Corrige auditoría #5 #2.
            FROM (
                -- Sensor-aware (corrige el bug multi-sensor): los sensores de una
                -- estación miden la MISMA lluvia, NO se suman. Por AÑO se usa el
                -- sensor MÁS COMPLETO (más slots con dato). Así las estaciones de
                -- un solo sensor no cambian y las multi-sensor dejan de inflarse
                -- ×N. Verificado en datos reales (Soledad 0029045190: años mono-
                -- sensor idénticos; 2024 28,9->10,0 mm/10min con el sensor 0257).
                WITH sensores AS (
                    SELECT date_bin('10 min', fechaobservacion, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS slot,
                           codigosensor,
                           sum(valorobservado) AS val
                    FROM observaciones
                    WHERE source_dataset_id = 's54a-sgyg'
                      AND codigoestacion = p_codigo
                      AND valorobservado >= 0 AND valorobservado <= 60  -- saneo: sin negativos ni picos no físicos
                    GROUP BY 1, 2
                ), dom AS (
                    SELECT DISTINCT ON (yr) yr, codigosensor
                    FROM (
                        SELECT extract(year FROM (slot AT TIME ZONE 'UTC'))::int AS yr,
                               codigosensor, count(*) AS nslots, sum(val) AS sval
                        FROM sensores GROUP BY 1, 2
                    ) z ORDER BY yr, nslots DESC, sval DESC
                ), obs AS (
                    SELECT s.slot, s.val
                    FROM sensores s
                    JOIN dom d ON d.yr = extract(year FROM (s.slot AT TIME ZONE 'UTC'))::int
                              AND d.codigosensor = s.codigosensor
                ), rango AS (SELECT min(slot) AS t0, max(slot) AS t1 FROM obs)
                SELECT g.slot,
                       coalesce(o.val, 0)::real AS val,
                       (o.val IS NOT NULL) AS es_real
                FROM rango,
                     LATERAL generate_series(rango.t0, rango.t1, INTERVAL '10 min') AS g(slot)
                LEFT JOIN obs o ON o.slot = g.slot
            ) grid
            WINDOW
              w10   AS (ORDER BY slot ROWS BETWEEN 0   PRECEDING AND CURRENT ROW),
              w20   AS (ORDER BY slot ROWS BETWEEN 1   PRECEDING AND CURRENT ROW),
              w30   AS (ORDER BY slot ROWS BETWEEN 2   PRECEDING AND CURRENT ROW),
              w60   AS (ORDER BY slot ROWS BETWEEN 5   PRECEDING AND CURRENT ROW),
              w120  AS (ORDER BY slot ROWS BETWEEN 11  PRECEDING AND CURRENT ROW),
              w180  AS (ORDER BY slot ROWS BETWEEN 17  PRECEDING AND CURRENT ROW),
              w360  AS (ORDER BY slot ROWS BETWEEN 35  PRECEDING AND CURRENT ROW),
              w720  AS (ORDER BY slot ROWS BETWEEN 71  PRECEDING AND CURRENT ROW),
              w1440 AS (ORDER BY slot ROWS BETWEEN 143 PRECEDING AND CURRENT ROW)
        ) movil
        GROUP BY anio
    ) a
    CROSS JOIN LATERAL (VALUES
        (10, a.m10), (20, a.m20), (30, a.m30), (60, a.m60), (120, a.m120),
        (180, a.m180), (360, a.m360), (720, a.m720), (1440, a.m1440)
    ) AS d(dur_min, max_mm)
    WHERE a.n_obs >= p_min_obs
      AND a.total_anual <= 13000  -- descarta AÑOS con lámina anual físicamente imposible
                                  -- (> récord mundial ~13.000 mm; p.ej. Soledad 2018 corrupto = 150.907)
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
