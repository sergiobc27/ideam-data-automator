"""Modelos de request (los responses son dicts con la forma de ideamContracts.ts).

Límites defensivos (hallazgo de auditoría): listas y strings acotados para que
un payload patológico (100k entradas en catalogFilters, fechas malformadas) no
infle los ANY(...) de SQL ni produzca 500 crudos — Pydantic responde 400.
"""

from typing import Annotated

from pydantic import BaseModel, Field, field_validator

# Colombia tiene 33 departamentos; el front manda nombres canónicos cortos.
_Departments = Annotated[list[Annotated[str, Field(max_length=80)]], Field(max_length=40)]
# Fecha ISO simple; el resto del pipeline le concatena la hora. El string
# vacío se acepta (el front lo manda cuando no hay rango) y los filtros lo
# ignoran igual que a None.
_DateStr = Annotated[str, Field(pattern=r"^$|^\d{4}-\d{2}-\d{2}$")]

_MAX_FILTER_VALUES = 500   # estaciones seleccionables a mano: holgado pero finito
_MAX_FILTER_LENGTH = 160   # nombres de estación/municipio reales caben de sobra


class _BoundedFilters(BaseModel):
    """Mixin: acota catalogFilters en los payloads que lo tienen."""

    @field_validator("catalogFilters", check_fields=False)
    @classmethod
    def _bounded_filters(cls, value):
        if value is None:
            return value
        for key, items in value.items():
            if len(items) > _MAX_FILTER_VALUES:
                raise ValueError(
                    f"El filtro '{key}' tiene {len(items)} valores; el maximo es {_MAX_FILTER_VALUES}."
                )
            for item in items:
                if len(str(item)) > _MAX_FILTER_LENGTH:
                    raise ValueError(f"Valor demasiado largo en el filtro '{key}'.")
        return value


class QueryPayload(_BoundedFilters):
    """Cuerpo común de catalog-options/bundle, stations-helper, coverage, preview, export."""

    datasetId: Annotated[str, Field(max_length=20)]
    departments: _Departments = Field(default_factory=list)
    catalogFilters: dict[str, list[str]] | None = None
    startDate: _DateStr | None = None
    endDate: _DateStr | None = None


class CatalogOptionsPayload(QueryPayload):
    attributeKey: Annotated[str, Field(max_length=40)]
    cacheOnly: bool | None = None


class CatalogBundlePayload(BaseModel):
    datasetId: Annotated[str, Field(max_length=20)]
    departments: _Departments = Field(default_factory=list)
    warm: bool | None = None
    forceRefresh: bool | None = None


class ExportPagePayload(_BoundedFilters):
    datasetId: Annotated[str, Field(max_length=20)]
    planIndex: int = 0
    where: str | None = None
    offset: Annotated[int, Field(ge=0)] = 0
    limit: Annotated[int, Field(ge=1)] = 10000
    departments: _Departments = Field(default_factory=list)
    catalogFilters: dict[str, list[str]] | None = None
    startDate: _DateStr | None = None
    endDate: _DateStr | None = None
    replacements: dict[str, str] | None = None


class CreateJobPayload(QueryPayload):
    formats: Annotated[list[Annotated[str, Field(max_length=10)]], Field(max_length=5)] = Field(
        default_factory=list
    )
    exportPlan: dict | None = None


class TimeseriesPayload(QueryPayload):
    interval: Annotated[str, Field(max_length=10)] = "month"  # day | month | year
    metric: Annotated[str, Field(max_length=10)] = "avg"      # avg | sum | min | max | count


class SpiPayload(QueryPayload):
    scale: Annotated[int, Field(ge=1, le=24)] = 12  # meses de acumulación (3 | 6 | 12)


class HistogramPayload(QueryPayload):
    bins: Annotated[int, Field(ge=5, le=60)] = 20
