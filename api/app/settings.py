from pydantic_settings import BaseSettings


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

    class Config:
        env_prefix = ""
        extra = "ignore"


settings = Settings()
