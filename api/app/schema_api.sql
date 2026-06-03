-- Esquema propio de la API (idempotente). Se aplica al arrancar.

CREATE TABLE IF NOT EXISTS api_rate_limit (
    scope        TEXT NOT NULL,
    ip           TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL DEFAULT now(),
    hits         INT NOT NULL DEFAULT 0,
    PRIMARY KEY (scope, ip)
);

CREATE TABLE IF NOT EXISTS export_jobs (
    job_id            UUID PRIMARY KEY,
    status            TEXT NOT NULL DEFAULT 'queued',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    dataset_id        TEXT NOT NULL,
    dataset_name      TEXT,
    payload           JSONB NOT NULL,
    selected_formats  TEXT[] NOT NULL DEFAULT '{}',
    effective_formats TEXT[] NOT NULL DEFAULT '{}',
    file_stem         TEXT,
    row_count         BIGINT NOT NULL DEFAULT 0,
    total_pages       INT NOT NULL DEFAULT 0,
    completed_pages   INT NOT NULL DEFAULT 0,
    processed_rows    BIGINT NOT NULL DEFAULT 0,
    current_stage     TEXT NOT NULL DEFAULT 'En cola',
    retry_count       INT NOT NULL DEFAULT 0,
    error             TEXT,
    warnings          JSONB NOT NULL DEFAULT '[]',
    parts             JSONB NOT NULL DEFAULT '[]',
    metrics           JSONB
);

CREATE INDEX IF NOT EXISTS ix_export_jobs_created ON export_jobs (created_at DESC);

-- Resumen del catálogo por dataset/region/estación: alimenta catalog-bundle,
-- options, municipalities y coverage de forma instantánea.
-- Se refresca tras el delta diario (ideam_socrata.db.delta) y al iniciar la API
-- si está vacío.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_catalogo AS
SELECT source_dataset_id,
       departamento,
       municipio,
       zonahidrografica,
       codigoestacion,
       nombreestacion,
       count(*) AS total
FROM observaciones
GROUP BY 1, 2, 3, 4, 5, 6
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_catalogo
    ON mv_catalogo (source_dataset_id, departamento, municipio, zonahidrografica,
                    codigoestacion, nombreestacion);
