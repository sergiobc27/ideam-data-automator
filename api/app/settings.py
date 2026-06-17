from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://ideam@127.0.0.1:5432/ideam"
    # Si esta definido, el Worker debe enviar X-Ideam-Proxy-Secret con este valor.
    api_shared_secret: str | None = None

    exports_dir: str = "/var/lib/ideam-api/exports"
    export_ttl_seconds: int = 3600

    preview_limit: int = 200
    export_page_size: int = 10000

    rate_limit_export_per_hour: int = 30
    rate_limit_catalog_per_hour: int = 600

    # Candados anti-DoS / anti-costo del export.
    # EXPORT_MAX_ROWS: tope de filas estimadas antes de generar (rechazo 413).
    # EXPORT_MAX_BYTES: tope del ZIP en disco; el job se aborta si lo supera (2 GB).
    # EXPORT_MAX_ACTIVE_JOBS: tope GLOBAL de jobs queued+planning+processing (429).
    export_max_rows: int = 5_000_000
    export_max_bytes: int = 2_000_000_000
    export_max_active_jobs: int = 4

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")


settings = Settings()
