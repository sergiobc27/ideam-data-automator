import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..catalog import CATALOG_FILTERS, DATASETS, DEPARTMENT_MAP
from ..db import pool, read_with_retry
from ..http_utils import client_ip as _client_ip
from ..normalize import department_variants, get_dataset, validate_required_departments
from ..ratelimit import check_rate_limit
from ..settings import settings

router = APIRouter()


def _lectura_rate(request: Request):
    """Gate anti-abuso por-IP del scope 'lectura' (mismo presupuesto que
    preview/analytics/catalog). Estos endpoints tocan la DB; sin esto el único
    freno era el cache de borde, que las ráfagas con parámetros rotados saltan."""
    ok, _remaining, retry = check_rate_limit(
        "lectura", _client_ip(request), settings.rate_limit_catalog_per_hour
    )
    if not ok:
        raise HTTPException(
            429,
            f"Limite de consultas alcanzado. Intenta de nuevo en {max(retry // 60, 1)} minuto(s).",
        )

# Cota de seguridad para /api/stations.geojson: el catálogo ronda ~18K estaciones,
# así que 50.000 deja amplísimo margen y NO recorta nada hoy; solo evita que un
# crecimiento inesperado o un cambio de filtro materialice cientos de miles de
# filas a la vez y dispare el OOM del box pequeño (auditoría #2).
_STATIONS_GEOJSON_CAP = 50000


@router.get("/api/health")
def health():
    """Vive el proceso. NO toca la DB (ver /api/ready para salud profunda)."""
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


# /api/ready es publico (el healthcheck del box lo llama SIN el secreto del
# proxy, exigirselo romperia la sonda) y toca la DB. Para que una rafaga
# anonima no consuma conexiones del pool, el resultado del SELECT 1 se cachea
# unos segundos por proceso: a lo sumo ~1 sondeo a la DB cada
# _READY_CACHE_SECONDS por worker, sin cambiar el contrato del endpoint
# (auditoria 2026-07-01). El costo es ver el cambio de estado de la DB con
# hasta esos segundos de retraso, irrelevante para un monitor de 30-60s.
_READY_CACHE_SECONDS = 5.0
_READY_STATE = {"ok": None, "at": 0.0}  # ok None = aun sin sondeo
_READY_LOCK = threading.Lock()


def _ready_db_ok():
    try:
        with pool.connection(timeout=5) as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


@router.get("/api/ready")
def ready():
    """Salud profunda: prueba la DB con timeout corto (cacheado unos segundos,
    ver _READY_STATE). El modo de fallo más probable (pool agotado por exports
    o Postgres caído) pasaba invisible porque /api/health responde 200 sin
    tocar la base (hallazgo de auditoría)."""
    state = _READY_STATE
    if state["ok"] is None or time.monotonic() - state["at"] >= _READY_CACHE_SECONDS:
        # Single-flight: un solo hilo sondea la DB a la vez. Si otro ya esta
        # sondeando y existe un resultado previo, se sirve ese (stale de unos
        # segundos); solo se bloquea cuando aun no hay NINGUN resultado.
        if _READY_LOCK.acquire(blocking=state["ok"] is None):
            try:
                if state["ok"] is None or time.monotonic() - state["at"] >= _READY_CACHE_SECONDS:
                    state["ok"] = _ready_db_ok()
                    state["at"] = time.monotonic()
            finally:
                _READY_LOCK.release()
    if not state["ok"]:
        return JSONResponse(
            {"ok": False, "error": "database"},
            status_code=503,
            headers={"cache-control": "no-store"},
        )
    return JSONResponse(
        {"ok": True, "time": datetime.now(timezone.utc).isoformat()},
        headers={"cache-control": "no-store"},
    )


def _data_freshness():
    # Frescura del espejo desde ingest_state (high-water mark del delta):
    # instantáneo, sin tocar la hypertable. Es informativo: si la DB no
    # responde, /api/meta sigue funcionando con valores nulos.
    def _consulta():
        with pool.connection() as conn:
            return conn.execute(
                "SELECT max(hwm_fecha), max(updated_at) FROM ingest_state "
                "WHERE grain = 'delta' AND status = 'done'"
            ).fetchone()

    try:
        row = read_with_retry(_consulta)
        return {
            "latestObservation": row[0].isoformat() if row and row[0] else None,
            "lastSync": row[1].isoformat() if row and row[1] else None,
        }
    except Exception:
        return {"latestObservation": None, "lastSync": None}


def _cached_json(payload, ttl_seconds):
    """JSON cacheable en el borde: el dato cambia 2x/día (delta), así que unos
    minutos de antigüedad son irrelevantes y Cloudflare absorbe los repetidos."""
    return JSONResponse(
        payload,
        headers={"cache-control": f"public, max-age={ttl_seconds}, stale-while-revalidate={ttl_seconds}"},
    )


@router.get("/api/meta")
def meta(request: Request):
    _lectura_rate(request)
    return _cached_json({
        "datasets": [
            {"id": d["id"], "name": d["name"], "category": d["category"], "dateColumn": d["dateColumn"]}
            for d in DATASETS
        ],
        "departments": sorted(DEPARTMENT_MAP.keys()),
        "previewLimit": settings.preview_limit,
        "exportPageSize": settings.export_page_size,
        "maxExportRows": settings.export_max_rows,
        "catalogFilters": CATALOG_FILTERS,
        "dataFreshness": _data_freshness(),
    }, ttl_seconds=300)


@router.get("/api/date-range")
def date_range(datasetId: str, request: Request):
    _lectura_rate(request)
    dataset = get_dataset(datasetId)
    # min/max desde obs_diario (agregado continuo): instantáneo. Sobre la
    # hypertable cruda, los datasets que terminaron en el pasado (los de mar,
    # hasta 2020) obligaban a un ChunkAppend hacia atrás desde 2026 saltando
    # ~6 años de chunks vacíos -> timeout de 30s. obs_diario ya tiene el rango.
    def _consulta():
        with pool.connection() as conn:
            return conn.execute(
                "SELECT min(dia), max(dia) FROM obs_diario WHERE source_dataset_id = %s",
                (dataset["id"],),
            ).fetchone()

    row = read_with_retry(_consulta)
    start, end = row
    # obs_diario está alineado a UTC; en la sesión (America/Bogota) .date()
    # directo regresaría el día anterior en los bordes del rango.
    start = start.astimezone(timezone.utc) if start else None
    end = end.astimezone(timezone.utc) if end else None
    return _cached_json({
        "datasetId": dataset["id"],
        "dateColumn": dataset["dateColumn"],
        "startDate": start.date().isoformat() if start else None,
        "endDate": end.date().isoformat() if end else None,
        "startYear": start.year if start else None,
        "endYear": end.year if end else None,
        "cachedAt": datetime.now(timezone.utc).isoformat(),
        "cacheTtlSeconds": 3600,
    }, ttl_seconds=3600)


@router.get("/api/stations.geojson")
def stations_geojson(request: Request):
    """Catálogo completo de estaciones como GeoJSON para el mapa.

    ~18K features (≈0,5MB gzip). El catálogo cambia poco: cache de 24h en el
    borde. El BETWEEN descarta outliers de captura fuera del territorio
    colombiano (San Andrés incluido: lon hasta -82, lat hasta 14).
    """
    _lectura_rate(request)

    def _consulta():
        with pool.connection() as conn:
            return conn.execute(
                "SELECT codigoestacion, nombre, categoria, tecnologia, estado, "
                "departamento_norm, municipio, latitud, longitud, altitud, "
                "zona_hidrografica, corriente, entidad "
                "FROM estaciones "
                "WHERE latitud BETWEEN -5 AND 14 AND longitud BETWEEN -82 AND -66 "
                # Cota de seguridad anti-OOM (ver _STATIONS_GEOJSON_CAP): no recorta
                # el catálogo actual (~18K), evita materializar sin límite (auditoría #2).
                f"LIMIT {_STATIONS_GEOJSON_CAP}"
            ).fetchall()

    rows = read_with_retry(_consulta)
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r[8], r[7]]},
            "properties": {
                "codigo": r[0],
                "nombre": r[1],
                "categoria": r[2],
                "tecnologia": r[3],
                "estado": r[4],
                "departamento": r[5],
                "municipio": r[6],
                "altitud": r[9],
                "zonaHidrografica": r[10],
                "corriente": r[11],
                "entidad": r[12],
            },
        }
        for r in rows
    ]
    # 2h (antes 24h): el catálogo cambia poco, pero 24h dejaba estaciones
    # nuevas del delta invisibles demasiado tiempo e iba contra los TTL del
    # resto de la API (auditoría #4).
    return JSONResponse(
        {"type": "FeatureCollection", "features": features},
        headers={"cache-control": "public, max-age=7200, stale-while-revalidate=7200"},
    )


@router.get("/api/municipalities")
def municipalities(request: Request, department: list[str] = Query(default=[])):
    _lectura_rate(request)
    canonicals = validate_required_departments(department)
    variants = set()
    for canonical in canonicals:
        variants.update(department_variants(canonical))
    def _consulta():
        with pool.connection() as conn:
            return conn.execute(
                "SELECT DISTINCT municipio FROM mv_catalogo "
                "WHERE upper(departamento) = ANY(%s) AND municipio IS NOT NULL ORDER BY municipio",
                (sorted(variants),),
            ).fetchall()

    rows = read_with_retry(_consulta)
    return _cached_json({"municipalities": [r[0] for r in rows]}, ttl_seconds=3600)
