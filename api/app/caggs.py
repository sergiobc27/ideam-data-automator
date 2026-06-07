"""Helpers compartidos para consultar los continuous aggregates.

Los caggs (obs_diario con time_col='dia', obs_mensual con time_col='mes')
están ALINEADOS A UTC mientras la sesión corre en America/Bogota: cualquier
fecha del payload debe compararse como instante UTC explícito y el rango debe
ser medio-abierto [start, end+1d). Comparar la fecha "desnuda" (se interpreta
en hora local -05) corría el rango un día en los bordes.

Usado por analytics (dashboards), export (candado anti-costo) y el exporter
(planificación de jobs).
"""

from .normalize import (
    department_variants,
    expand_station_codes,
    get_dataset,
    validate_required_departments,
)


def can_use_cagg(payload):
    """Los caggs no tienen zonahidrografica ni nombreestacion."""
    filters = payload.catalogFilters or {}
    return not filters.get("hydrologicZones") and not filters.get("stationNames")


def cagg_filters(payload, time_col="dia"):
    """WHERE/params equivalentes a build_filters pero sobre un cagg.

    Sin departamentos = todo el país (permitido solo en lecturas agregadas;
    exports/preview siguen exigiendo >=1 departamento vía build_filters).
    """
    dataset = get_dataset(payload.datasetId)
    clauses = ["source_dataset_id = %(dataset_id)s"]
    params = {"dataset_id": dataset["id"]}

    if payload.departments:
        canonicals = validate_required_departments(payload.departments)
        variants = set()
        for canonical in canonicals:
            variants.update(department_variants(canonical))
        clauses.append("upper(departamento) = ANY(%(departments)s)")
        params["departments"] = sorted(variants)

    filters = payload.catalogFilters or {}
    if filters.get("municipalities"):
        clauses.append("upper(municipio) = ANY(%(municipios)s)")
        params["municipios"] = [str(m).upper() for m in filters["municipalities"]]
    if filters.get("stations"):
        clauses.append("codigoestacion = ANY(%(estaciones)s)")
        params["estaciones"] = expand_station_codes(filters["stations"])

    # Bordes de fecha como instantes UTC explícitos, rango medio-abierto.
    if payload.startDate:
        clauses.append(f"{time_col} >= %(start)s::timestamptz")
        params["start"] = f"{payload.startDate}T00:00:00+00:00"
    if payload.endDate:
        clauses.append(f"{time_col} < %(end)s::timestamptz + interval '1 day'")
        params["end"] = f"{payload.endDate}T00:00:00+00:00"
    return " AND ".join(clauses), params, dataset
