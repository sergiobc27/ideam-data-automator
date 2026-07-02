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
    -- % de slots REALES (no rellenados con 0) dentro de la ventana móvil que
    -- fijó el máximo de esa duración/año. Señal de completitud LOCAL: la rejilla
    -- densa cuenta huecos como 0 (lado seguro), así que un máximo apoyado en una
    -- ventana con muchos huecos puede subestimar la lámina real (auditoría #4).
    -- La capa de arriba puede avisar cuando sea bajo. NULL en filas antiguas
    -- hasta el próximo recómputo.
    pct_slots_reales real,
    PRIMARY KEY (codigoestacion, anio, dur_min)
);
CREATE INDEX IF NOT EXISTS ix_idf_estacion ON idf_max_anual (codigoestacion);
-- Migración idempotente para DBs ya creadas (CREATE TABLE IF NOT EXISTS no altera
-- una tabla existente): añade la columna de completitud si aún no está.
ALTER TABLE idf_max_anual ADD COLUMN IF NOT EXISTS pct_slots_reales real;

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
-- Además persiste pct_slots_reales por (año, duración): fracción de slots reales
-- en la ventana que fijó el máximo, para que la API avise cuando el pico se
-- apoyó en huecos (auditoría #4).
CREATE OR REPLACE FUNCTION idf_compute_station(p_codigo text, p_min_obs int DEFAULT 30000)
RETURNS int AS $$
DECLARE
    v_anios int;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('idf:' || p_codigo));
    DELETE FROM idf_max_anual WHERE codigoestacion = p_codigo;

    INSERT INTO idf_max_anual (codigoestacion, anio, dur_min, max_mm, pct_slots_reales)
    -- Rejilla DENSA de 10 min (huecos = 0): hace que las ventanas ROWS de N
    -- intervalos cubran exactamente N×10 min de tiempo real, sin saltar huecos.
    -- Combina la exactitud temporal de RANGE con la velocidad O(filas) de ROWS
    -- (RANGE puro tardaba 6min/estación grande). Huecos cuentan como 0 → del lado
    -- SEGURO de diseño (nunca sobreestima). Corrige auditoría #5 #2.
    WITH
        -- Sensor-aware (corrige el bug multi-sensor): los sensores de una
        -- estación miden la MISMA lluvia, NO se suman. Por AÑO se usa un solo
        -- sensor. Así las estaciones de un solo sensor no cambian y las
        -- multi-sensor dejan de inflarse ×N. Verificado en datos reales
        -- (Soledad 0029045190: años mono-sensor idénticos).
        -- Criterio de desempate ALINEADO con obs_diario (Fix #2,
        -- src/ideam_socrata/db/schema.sql:191): PRIMERO se desprioriza el GPRS de
        -- telemetría '0257', que SOBRE-muestrea (más slots que el medidor real
        -- '0240') pero SUB-reporta la lluvia; con el viejo criterio "más slots"
        -- ganaba y bajaba la lámina (Soledad 2024: 28,9->10,0 mm/10min al tomar
        -- 0257). Recién después se prefiere el sensor más completo (más slots) y,
        -- a igualdad, el de mayor lámina.
        sensores AS (
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
            ) z
            -- Desprioriza '0257' ANTES de desempatar por completitud: el GPRS
            -- sub-reporta la lluvia (ver comentario arriba y obs_diario).
            ORDER BY yr, coalesce(codigosensor = '0257', false) ASC,
                     nslots DESC, sval DESC
        ), obs0 AS (
            SELECT s.slot, s.val
            FROM sensores s
            JOIN dom d ON d.yr = extract(year FROM (s.slot AT TIME ZONE 'UTC'))::int
                      AND d.codigosensor = s.codigosensor
        ), dias_malos AS (
            -- Días con lámina diaria físicamente imposible (>500 mm/día, holgado
            -- sobre cualquier extremo real colombiano): corrupción de la fuente
            -- que pasa el tope por-slot pero acumula absurdos en el día (p.ej.
            -- San Andrés 1.647 mm/día). Se EXCLUYE el día, no el año, para no
            -- perder años buenos.
            SELECT date_trunc('day', slot AT TIME ZONE 'UTC') AS dia
            FROM obs0 GROUP BY 1 HAVING sum(val) > 500
        ), obs AS (
            SELECT slot, val FROM obs0
            WHERE date_trunc('day', slot AT TIME ZONE 'UTC') NOT IN (SELECT dia FROM dias_malos)
        ), rango AS (SELECT min(slot) AS t0, max(slot) AS t1 FROM obs),
        grid AS (
            SELECT g.slot,
                   coalesce(o.val, 0)::real AS val,
                   (o.val IS NOT NULL) AS es_real
            FROM rango,
                 LATERAL generate_series(rango.t0, rango.t1, INTERVAL '10 min') AS g(slot)
            LEFT JOIN obs o ON o.slot = g.slot
        ),
        -- Sumas móviles por duración (dNN) y, en la MISMA ventana, cuántos slots
        -- son reales (rNN) frente al total de slots de la ventana (cNN). rNN/cNN
        -- da la fracción de datos reales de esa ventana concreta.
        movil AS (
            SELECT extract(year FROM (slot AT TIME ZONE 'UTC'))::int AS anio,
                   slot, val, es_real,
                   sum(val) OVER w10   AS d10,   sum(val) OVER w20   AS d20,
                   sum(val) OVER w30   AS d30,   sum(val) OVER w60   AS d60,
                   sum(val) OVER w120  AS d120,  sum(val) OVER w180  AS d180,
                   sum(val) OVER w360  AS d360,  sum(val) OVER w720  AS d720,
                   sum(val) OVER w1440 AS d1440,
                   sum(es_real::int) OVER w10   AS r10,   sum(es_real::int) OVER w20   AS r20,
                   sum(es_real::int) OVER w30   AS r30,   sum(es_real::int) OVER w60   AS r60,
                   sum(es_real::int) OVER w120  AS r120,  sum(es_real::int) OVER w180  AS r180,
                   sum(es_real::int) OVER w360  AS r360,  sum(es_real::int) OVER w720  AS r720,
                   sum(es_real::int) OVER w1440 AS r1440,
                   count(*) OVER w10   AS c10,   count(*) OVER w20   AS c20,
                   count(*) OVER w30   AS c30,   count(*) OVER w60   AS c60,
                   count(*) OVER w120  AS c120,  count(*) OVER w180  AS c180,
                   count(*) OVER w360  AS c360,  count(*) OVER w720  AS c720,
                   count(*) OVER w1440 AS c1440
            FROM grid
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
        ),
        -- Por (año, duración): la VENTANA GANADORA (mayor lámina móvil) y el % de
        -- sus slots que son reales. El DISTINCT ON ... ORDER BY depth DESC toma la
        -- misma ventana que el antiguo max(dNN) (mismo valor de lámina), y de paso
        -- arrastra el conteo real/total de ESA ventana.
        ganadora AS (
            SELECT DISTINCT ON (anio, dur_min)
                   anio, dur_min, depth AS max_mm,
                   CASE WHEN win_slots > 0
                        THEN round((100.0 * real_slots / win_slots)::numeric, 1)::real
                   END AS pct_slots_reales
            FROM movil
            CROSS JOIN LATERAL (VALUES
                (10,   d10,   r10,   c10),
                (20,   d20,   r20,   c20),
                (30,   d30,   r30,   c30),
                (60,   d60,   r60,   c60),
                (120,  d120,  r120,  c120),
                (180,  d180,  r180,  c180),
                (360,  d360,  r360,  c360),
                (720,  d720,  r720,  c720),
                (1440, d1440, r1440, c1440)
            ) AS d(dur_min, depth, real_slots, win_slots)
            ORDER BY anio, dur_min, depth DESC NULLS LAST, real_slots DESC, slot
        ),
        -- Gates ANUALES (idénticos a antes): completitud, lámina anual y máx 24h.
        anual AS (
            SELECT anio,
                   sum(es_real::int) AS n_obs,       -- observaciones REALES del año
                   sum(val)          AS total_anual, -- lámina anual (cordura física)
                   max(d1440)        AS m1440        -- máx 24h móvil (cordura física)
            FROM movil
            GROUP BY anio
        )
    SELECT p_codigo, g.anio, g.dur_min, g.max_mm, g.pct_slots_reales
    FROM ganadora g
    JOIN anual a ON a.anio = g.anio
    WHERE a.n_obs >= p_min_obs
      AND a.total_anual <= 13000  -- descarta AÑOS con lámina anual físicamente imposible
                                  -- (> récord mundial ~13.000 mm; p.ej. Soledad 2018 corrupto = 150.907)
      AND a.m1440 <= 500          -- descarta AÑOS cuyo máx 24h MÓVIL es físicamente imposible.
                                  -- La métrica IDF es ventana móvil de 24h; el tope dias_malos solo
                                  -- cubre el día-CALENDARIO y deja pasar ráfagas corruptas que cruzan
                                  -- la medianoche (p.ej. 400+400 mm en dos días <500 c/u → móvil 800).
      AND g.max_mm IS NOT NULL
      AND g.max_mm >= 0;  -- sumas de no-negativos: finitas por construcción

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
