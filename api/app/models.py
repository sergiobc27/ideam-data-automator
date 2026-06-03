"""Modelos de request (los responses son dicts con la forma de ideamContracts.ts)."""

from pydantic import BaseModel, Field


class QueryPayload(BaseModel):
    """Cuerpo común de catalog-options/bundle, stations-helper, coverage, preview, export."""

    datasetId: str
    departments: list[str] = Field(default_factory=list)
    catalogFilters: dict[str, list[str]] | None = None
    startDate: str | None = None
    endDate: str | None = None


class CatalogOptionsPayload(QueryPayload):
    attributeKey: str
    cacheOnly: bool | None = None


class CatalogBundlePayload(BaseModel):
    datasetId: str
    departments: list[str] = Field(default_factory=list)
    warm: bool | None = None
    forceRefresh: bool | None = None


class ExportPagePayload(BaseModel):
    datasetId: str
    planIndex: int = 0
    where: str | None = None
    offset: int = 0
    limit: int = 10000
    departments: list[str] = Field(default_factory=list)
    catalogFilters: dict[str, list[str]] | None = None
    startDate: str | None = None
    endDate: str | None = None
    replacements: dict[str, str] | None = None


class CreateJobPayload(QueryPayload):
    formats: list[str] = Field(default_factory=list)
    exportPlan: dict | None = None


class TimeseriesPayload(QueryPayload):
    interval: str = "month"  # day | month | year
    metric: str = "avg"      # avg | sum | min | max | count
