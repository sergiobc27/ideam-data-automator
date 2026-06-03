"""Normalización de etiquetas, departamentos y construcción de filtros SQL.

Replica la semántica del Worker (normalizeLabel, departmentVariants,
validateRequiredDepartments, expandStationCodes) pero contra Postgres con
parámetros seguros.
"""

import unicodedata

from fastapi import HTTPException

from .catalog import DATASETS_BY_ID, DEPARTMENT_MAP


def normalize_label(value):
    text = "" if value is None else str(value).strip().upper()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


_CANONICAL_BY_NORM = {}
for canonical, variants in DEPARTMENT_MAP.items():
    _CANONICAL_BY_NORM[normalize_label(canonical)] = canonical
    for v in variants:
        _CANONICAL_BY_NORM.setdefault(normalize_label(v), canonical)


def canonical_department(value):
    return _CANONICAL_BY_NORM.get(normalize_label(value))


def department_variants(canonical):
    """Todas las formas en que el valor puede aparecer almacenado (mayúsculas)."""
    variants = {canonical.upper(), normalize_label(canonical)}
    for v in DEPARTMENT_MAP.get(canonical, []):
        variants.add(v.upper())
        variants.add(normalize_label(v))
    return sorted(variants)


def validate_required_departments(departments):
    """Regla de producto: todo export/preview exige >=1 departamento válido."""
    if not departments:
        raise HTTPException(400, "Selecciona al menos un departamento. Las descargas globales no estan permitidas.")
    canonicals = []
    for dep in departments:
        canonical = canonical_department(dep)
        if canonical is None:
            raise HTTPException(400, f"Departamento no soportado: {dep}")
        if canonical not in canonicals:
            canonicals.append(canonical)
    return canonicals


def expand_station_codes(codes):
    """Los códigos pueden venir con o sin el prefijo de ceros (25027140 vs 0025027140)."""
    expanded = set()
    for code in codes:
        c = str(code).strip()
        if not c:
            continue
        expanded.add(c)
        expanded.add(c.lstrip("0") or c)
        expanded.add(c.zfill(10))
    return sorted(expanded)


def get_dataset(dataset_id):
    dataset = DATASETS_BY_ID.get(dataset_id)
    if not dataset:
        raise HTTPException(400, "datasetId invalido.")
    return dataset


def build_filters(payload):
    """Construye (sql_where, params) para observaciones a partir del payload del front.

    payload: datasetId, departments[], catalogFilters{}, startDate, endDate.
    """
    dataset = get_dataset(payload.datasetId)
    canonicals = validate_required_departments(payload.departments)

    clauses = ["source_dataset_id = %(dataset_id)s"]
    params = {"dataset_id": dataset["id"]}

    dep_variants = set()
    for canonical in canonicals:
        dep_variants.update(department_variants(canonical))
    clauses.append("upper(departamento) = ANY(%(departments)s)")
    params["departments"] = sorted(dep_variants)

    filters = payload.catalogFilters or {}
    if filters.get("municipalities"):
        clauses.append("upper(municipio) = ANY(%(municipios)s)")
        params["municipios"] = [str(m).upper() for m in filters["municipalities"]]
    if filters.get("hydrologicZones"):
        clauses.append("upper(zonahidrografica) = ANY(%(zonas)s)")
        params["zonas"] = [str(z).upper() for z in filters["hydrologicZones"]]
    if filters.get("stations"):
        clauses.append("codigoestacion = ANY(%(estaciones)s)")
        params["estaciones"] = expand_station_codes(filters["stations"])
    if filters.get("stationNames"):
        clauses.append("upper(nombreestacion) = ANY(%(nombres)s)")
        params["nombres"] = [str(n).upper() for n in filters["stationNames"]]

    if payload.startDate:
        clauses.append("fechaobservacion >= %(start)s")
        params["start"] = f"{payload.startDate}T00:00:00"
    if payload.endDate:
        clauses.append("fechaobservacion <= %(end)s")
        params["end"] = f"{payload.endDate}T23:59:59.999"

    return " AND ".join(clauses), params, dataset, canonicals
