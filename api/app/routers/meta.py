from datetime import datetime, timezone

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ..catalog import CATALOG_FILTERS, DATASETS, DEPARTMENT_MAP
from ..db import pool
from ..normalize import department_variants, get_dataset, validate_required_departments
from ..settings import settings

router = APIRouter()


@router.get("/api/health")
def health():
    """Vive el proceso. NO toca la DB (ver /api/ready para salud profunda)."""
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@router.get("/api/ready")
def ready():
    """Salud profunda: prueba la DB con timeout corto. El modo de fallo más
    probable (pool agotado por exports o Postgres caído) pasaba invisible
    porque /api/health responde 200 sin tocar la base (hallazgo de auditoría)."""
    try:
        with pool.connection(timeout=5) as conn:
            conn.execute("SET LOCAL statement_timeout = '5s'")
            conn.execute("SELECT 1").fetchone()
    except Exception:
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
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "SELECT max(hwm_fecha), max(updated_at) FROM ingest_state "
                "WHERE grain = 'delta' AND status = 'done'"
            ).fetchone()
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
def meta():
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
def date_range(datasetId: str):
    dataset = get_dataset(datasetId)
    # min/max desde obs_diario (agregado continuo): instantáneo. Sobre la
    # hypertable cruda, los datasets que terminaron en el pasado (los de mar,
    # hasta 2020) obligaban a un ChunkAppend hacia atrás desde 2026 saltando
    # ~6 años de chunks vacíos -> timeout de 30s. obs_diario ya tiene el rango.
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT min(dia), max(dia) FROM obs_diario WHERE source_dataset_id = %s",
            (dataset["id"],),
        ).fetchone()
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
def stations_geojson():
    """Catálogo completo de estaciones como GeoJSON para el mapa.

    ~18K features (≈0,5MB gzip). El catálogo cambia poco: cache de 24h en el
    borde. El BETWEEN descarta outliers de captura fuera del territorio
    colombiano (San Andrés incluido: lon hasta -82, lat hasta 14).
    """
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT codigoestacion, nombre, categoria, tecnologia, estado, "
            "departamento_norm, municipio, latitud, longitud, altitud, "
            "zona_hidrografica, corriente, entidad "
            "FROM estaciones "
            "WHERE latitud BETWEEN -5 AND 14 AND longitud BETWEEN -82 AND -66"
        ).fetchall()
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
    return JSONResponse(
        {"type": "FeatureCollection", "features": features},
        headers={"cache-control": "public, max-age=86400, stale-while-revalidate=86400"},
    )


@router.get("/api/municipalities")
def municipalities(department: list[str] = Query(default=[])):
    canonicals = validate_required_departments(department)
    variants = set()
    for canonical in canonicals:
        variants.update(department_variants(canonical))
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT municipio FROM mv_catalogo "
            "WHERE upper(departamento) = ANY(%s) AND municipio IS NOT NULL ORDER BY municipio",
            (sorted(variants),),
        ).fetchall()
    return _cached_json({"municipalities": [r[0] for r in rows]}, ttl_seconds=3600)
