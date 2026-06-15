import logging
import unicodedata

logger = logging.getLogger(__name__)


def normalize_label(value):
    """Normalize labels for accent-insensitive comparisons."""
    text = "" if value is None else str(value).strip().upper()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def quote_soql(value):
    """Quote a value for simple Socrata SoQL string literals."""
    return "'" + str(value).replace("'", "''") + "'"


def date_window_clauses(date_column, start_date, end_date):
    """Build two safe SoQL clauses for a [start, end) date window.

    ``date_column`` is an internal/config identifier (interpolated as-is); the
    date literals are escaped via :func:`quote_soql` so a stray or hostile quote
    cannot break or inject the query. Returns the two clauses as a list so the
    caller can join/compose them with any base filters.
    """
    return [
        f"{date_column} >= {quote_soql(f'{start_date}T00:00:00.000')}",
        f"{date_column} < {quote_soql(f'{end_date}T00:00:00.000')}",
    ]


def department_variants(department, mapping):
    """Return configured variants plus normalized fallbacks for a department."""
    variants = set(mapping.get(department, [department]))
    variants.add(department)
    variants.update(normalize_label(v) for v in list(variants))
    return sorted(v for v in variants if v)


def build_department_filter(departments, mapping, column="departamento"):
    """Build a safe upper(column) IN (...) filter and replacement dictionary."""
    variants = []
    replacements = {}
    for department in departments:
        for variant in department_variants(department, mapping):
            variants.append(variant)
            replacements[variant] = department
    unique_variants = sorted(set(variants))
    in_clause = ", ".join(quote_soql(v.upper()) for v in unique_variants)
    return f"upper({column}) IN ({in_clause})", replacements, unique_variants


def discover_department_values(client, dataset_id, retry_func, department=None, limit=50000):
    """Fast grouped query to inspect how a department appears in a Socrata dataset."""
    where = None
    if department:
        needle = normalize_label(department)[:4]
        where = f"upper(departamento) like '%{needle}%'"

    rows = retry_func(
        lambda: client.get(
            dataset_id,
            select="departamento, count(*) as total",
            where=where,
            group="departamento",
            order="departamento",
            limit=limit,
        ),
        f"variantes departamento {dataset_id}",
    )
    return rows or []


def verify_department_coverage(client, dataset_id, department, mapping, retry_func):
    """Compare discovered source values against configured department variants."""
    configured = {normalize_label(v) for v in department_variants(department, mapping)}
    discovered_rows = discover_department_values(client, dataset_id, retry_func, department)
    matched = []
    missing = []

    for row in discovered_rows:
        source_value = row.get("departamento")
        normalized = normalize_label(source_value)
        record = {"departamento": source_value, "normalized": normalized, "total": int(row.get("total", 0))}
        if normalized in configured:
            matched.append(record)
        else:
            missing.append(record)

    total_matched = sum(row["total"] for row in matched)
    total_missing = sum(row["total"] for row in missing)
    logger.info(
        "Cobertura departamento dataset=%s department=%s matched=%s missing=%s",
        dataset_id,
        department,
        total_matched,
        total_missing,
    )
    return {
        "department": department,
        "configured_variants": sorted(configured),
        "matched": matched,
        "unmatched_discovered": missing,
        "matched_rows": total_matched,
        "unmatched_rows": total_missing,
    }
