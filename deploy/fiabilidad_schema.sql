-- ============================================================
-- Lote 2.1 — Fiabilidad precalculada por estación
-- ------------------------------------------------------------
-- Guarda el semáforo (verde/amarillo/rojo) y sus insumos por estación, calculado
-- por app.services.fiabilidad_batch con la MISMA lógica del semáforo on-the-fly.
-- El endpoint /idf-stations la lee (LEFT JOIN) para poblar el selector sin
-- recalcular. La fiabilidad cambia lento → se refresca con un timer mensual.
-- ============================================================

CREATE TABLE IF NOT EXISTS estacion_fiabilidad (
    codigoestacion text PRIMARY KEY,
    level          text NOT NULL,          -- 'verde' | 'amarillo' | 'rojo'
    n              int,                     -- años válidos (máximos diarios anuales)
    completeness   real,                    -- 0..1
    stationary     boolean,
    reasons        jsonb,                   -- motivos citables del nivel
    computed_at    timestamptz NOT NULL DEFAULT now()
);
