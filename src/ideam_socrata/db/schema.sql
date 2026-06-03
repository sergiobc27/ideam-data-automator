-- ============================================================
-- Esquema espejo IDEAM (PostgreSQL 15 + TimescaleDB)
-- Idempotente: se puede re-aplicar sin romper nada.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ------------------------------------------------------------
-- Dimensión: catálogo de estaciones (dataset Socrata hp9r-jxuu)
-- Nota: los códigos del catálogo pueden venir sin el padding de
-- ceros que usan los datasets de observación (p.ej. 25027140 vs
-- 0025027140); el matching se resuelve en la capa de consulta.
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS estaciones (
    codigoestacion       TEXT PRIMARY KEY,
    nombre               TEXT,
    categoria            TEXT,
    tecnologia           TEXT,
    estado               TEXT,
    departamento         TEXT,
    departamento_norm    TEXT,
    municipio            TEXT,
    latitud              DOUBLE PRECISION,
    longitud             DOUBLE PRECISION,
    altitud              DOUBLE PRECISION,
    fecha_instalacion    DATE,
    fecha_suspension     DATE,
    area_operativa       TEXT,
    area_hidrografica    TEXT,
    zona_hidrografica    TEXT,
    subzona_hidrografica TEXT,
    corriente            TEXT,
    entidad              TEXT,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_estaciones_depto ON estaciones (departamento_norm);

-- ------------------------------------------------------------
-- Hechos: observaciones (hypertable única para los 13 datasets)
-- floating_id = sha256(dataset_id|codigoestacion|codigosensor|fechaobservacion)
-- calculado SIEMPRE en Python (ideam_socrata.transform.add_floating_id).
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS observaciones (
    floating_id        BYTEA            NOT NULL,
    source_dataset_id  TEXT             NOT NULL,
    codigoestacion     TEXT             NOT NULL,
    codigosensor       TEXT,
    fechaobservacion   TIMESTAMPTZ      NOT NULL,
    valorobservado     REAL,
    nombreestacion     TEXT,
    departamento       TEXT,
    municipio          TEXT,
    zonahidrografica   TEXT,
    latitud            DOUBLE PRECISION,
    longitud           DOUBLE PRECISION,
    descripcionsensor  TEXT,
    unidadmedida       TEXT,
    ingested_at        TIMESTAMPTZ      NOT NULL DEFAULT now(),
    -- TimescaleDB exige que toda UNIQUE incluya la columna de partición.
    -- floating_id ya incorpora la fecha en el hash, así que la pareja es 1:1.
    CONSTRAINT observaciones_uq UNIQUE (floating_id, fechaobservacion)
);

SELECT create_hypertable('observaciones', 'fechaobservacion',
                         chunk_time_interval => INTERVAL '30 days',
                         if_not_exists       => TRUE);

CREATE INDEX IF NOT EXISTS ix_obs_serie
    ON observaciones (source_dataset_id, codigoestacion, fechaobservacion DESC);

-- Compresión columnar (imprescindible para caber en 200 GB).
-- Las columnas de la UNIQUE deben estar en segmentby u orderby.
ALTER TABLE observaciones SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'source_dataset_id, codigoestacion',
    timescaledb.compress_orderby   = 'fechaobservacion DESC, floating_id'
);

SELECT add_compression_policy('observaciones', INTERVAL '30 days', if_not_exists => TRUE);

-- ------------------------------------------------------------
-- Staging para cargas masivas vía COPY (UNLOGGED: sin WAL).
-- floating_id llega como hex (lo produce Python); el upsert
-- final lo convierte con decode(floating_id_hex,'hex').
-- ------------------------------------------------------------
CREATE UNLOGGED TABLE IF NOT EXISTS staging_obs (
    floating_id_hex    TEXT,
    source_dataset_id  TEXT,
    codigoestacion     TEXT,
    codigosensor       TEXT,
    fechaobservacion   TIMESTAMPTZ,
    valorobservado     REAL,
    nombreestacion     TEXT,
    departamento       TEXT,
    municipio          TEXT,
    zonahidrografica   TEXT,
    latitud            DOUBLE PRECISION,
    longitud           DOUBLE PRECISION,
    descripcionsensor  TEXT,
    unidadmedida       TEXT
);

-- Filas que no pasan validación
CREATE TABLE IF NOT EXISTS observaciones_rechazos (
    id                BIGSERIAL PRIMARY KEY,
    source_dataset_id TEXT,
    raw               JSONB,
    motivo            TEXT,
    rejected_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- Estado de ingesta: backfill reanudable y high-water mark del delta
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_state (
    source_dataset_id TEXT        NOT NULL,
    grain             TEXT        NOT NULL,   -- 'backfill' | 'delta'
    chunk_key         TEXT        NOT NULL,   -- '2014' | '2014-03' | 'hwm'
    status            TEXT        NOT NULL DEFAULT 'pending',  -- pending|running|done|error
    rows_loaded       BIGINT      NOT NULL DEFAULT 0,
    hwm_fecha         TIMESTAMPTZ,
    error             TEXT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source_dataset_id, grain, chunk_key)
);

-- ------------------------------------------------------------
-- Continuous aggregates para dashboards (jerárquicos)
-- n = filas totales, n_validos = con valor no nulo.
-- El promedio mensual se calcula en la API como
-- sum(valor_sum)/nullif(sum(n_validos),0) (promedio ponderado).
-- ------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS obs_diario
WITH (timescaledb.continuous) AS
SELECT source_dataset_id,
       codigoestacion,
       departamento,
       municipio,
       time_bucket('1 day', fechaobservacion) AS dia,
       count(*)                AS n,
       count(valorobservado)   AS n_validos,
       avg(valorobservado)     AS valor_avg,
       min(valorobservado)     AS valor_min,
       max(valorobservado)     AS valor_max,
       sum(valorobservado)     AS valor_sum
FROM observaciones
GROUP BY source_dataset_id, codigoestacion, departamento, municipio, dia
WITH NO DATA;

SELECT add_continuous_aggregate_policy('obs_diario',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS obs_mensual
WITH (timescaledb.continuous) AS
SELECT source_dataset_id,
       codigoestacion,
       departamento,
       municipio,
       time_bucket('1 month', dia) AS mes,
       sum(n)          AS n,
       sum(n_validos)  AS n_validos,
       min(valor_min)  AS valor_min,
       max(valor_max)  AS valor_max,
       sum(valor_sum)  AS valor_sum
FROM obs_diario
GROUP BY source_dataset_id, codigoestacion, departamento, municipio, mes
WITH NO DATA;

SELECT add_continuous_aggregate_policy('obs_mensual',
    start_offset      => INTERVAL '3 months',
    end_offset        => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists     => TRUE);
