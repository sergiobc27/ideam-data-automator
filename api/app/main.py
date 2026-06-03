import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .db import init_db, pool
from .routers import analytics, catalog_routes, export, meta, preview
from .settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ideam-api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    Path(settings.exports_dir).mkdir(parents=True, exist_ok=True)
    # Poblar el resumen de catálogo si aún está vacío (primera vez).
    with pool.connection() as conn:
        populated = conn.execute(
            "SELECT relispopulated FROM pg_class WHERE relname = 'mv_catalogo'"
        ).fetchone()
        if populated and not populated[0]:
            logger.info("Poblando mv_catalogo por primera vez...")
            conn.execute("REFRESH MATERIALIZED VIEW mv_catalogo")
    logger.info("API lista.")
    yield
    pool.close()


app = FastAPI(title="IDEAM API", lifespan=lifespan, docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ideam.sergiobc.com", "http://localhost:5173", "http://localhost:8787"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def proxy_secret_guard(request: Request, call_next):
    """Si hay secreto configurado, solo el Worker (proxy) puede llamar a la API."""
    if settings.api_shared_secret and request.url.path != "/api/health":
        if request.headers.get("x-ideam-proxy-secret") != settings.api_shared_secret:
            return JSONResponse({"error": "No autorizado."}, status_code=403)
    return await call_next(request)


# El frontend lee `data.error`; FastAPI usa `detail` -> lo mapeamos.
@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse({"error": f"Solicitud invalida: {exc.errors()[:2]}"}, status_code=400)


@app.exception_handler(Exception)
async def unhandled_handler(_request: Request, exc: Exception):
    logger.exception("Error no manejado: %s", exc)
    return JSONResponse({"error": "Error interno del servidor."}, status_code=500)


app.include_router(meta.router)
app.include_router(catalog_routes.router)
app.include_router(preview.router)
app.include_router(export.router)
app.include_router(analytics.router)
