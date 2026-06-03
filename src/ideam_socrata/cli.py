"""Command line entrypoint for IDEAM Hydrology Data Automator."""

from __future__ import annotations

import argparse
import json

from .config import CLIENT, MAPEO_DEPARTAMENTOS
from .core import intentar
from .main import main as interactive_main
from .query_validation import build_department_filter, verify_department_coverage


def _verify_atlantico(args: argparse.Namespace) -> int:
    where, _replacements, variants = build_department_filter([args.department], MAPEO_DEPARTAMENTOS)
    bounded_where = (
        f"{where} AND "
        f"{args.date_column} >= '{args.start_date}T00:00:00.000' AND "
        f"{args.date_column} < '{args.end_date}T00:00:00.000'"
    )
    sample_rows = CLIENT.get(
        args.dataset_id,
        select=f"departamento, municipio, codigoestacion, {args.date_column}",
        where=bounded_where,
        order=args.date_column,
        limit=args.limit,
    )
    catalog_coverage = verify_department_coverage(
        CLIENT,
        args.catalog_dataset_id,
        args.department,
        MAPEO_DEPARTAMENTOS,
        intentar,
    )
    print(
        json.dumps(
            {
                "dataset_id": args.dataset_id,
                "department": args.department,
                "variants": variants,
                "sample_rows": sample_rows,
                "catalog_coverage": catalog_coverage,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ideam-socrata",
        description="Automatiza extraccion, validacion y organizacion de datos IDEAM/Socrata.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("interactive", help="Abre el asistente interactivo de descarga.")

    subparsers.add_parser("datasets", help="Lista los datasets IDEAM disponibles y sus IDs.")

    download = subparsers.add_parser(
        "download",
        help="Descarga no interactiva (scriptable): dataset + departamentos + rango de fechas.",
    )
    download.add_argument("--dataset", required=True, help="ID Socrata, ej. s54a-sgyg (ver 'datasets')")
    download.add_argument(
        "--department", action="append", required=True,
        help="Departamento (repetible: --department ATLANTICO --department BOLIVAR)",
    )
    download.add_argument("--start-date", required=True, help="YYYY-MM-DD (inclusive)")
    download.add_argument("--end-date", required=True, help="YYYY-MM-DD (exclusivo)")
    download.add_argument("--csv", action="store_true", help="Exportar tambien copias CSV")
    download.add_argument("--output-dir", default="data", help="Carpeta destino (default: data)")
    download.add_argument("--workers", type=int, default=None, help="Bloques mensuales en paralelo")

    verify = subparsers.add_parser(
        "verify-atlantico",
        help="Ejecuta una verificacion rapida y acotada de precipitacion para Atlantico.",
    )
    verify.add_argument("--dataset-id", default="s54a-sgyg")
    verify.add_argument("--catalog-dataset-id", default="hp9r-jxuu")
    verify.add_argument("--department", default="ATLANTICO")
    verify.add_argument("--date-column", default="fechaobservacion")
    verify.add_argument("--start-date", default="2024-01-01")
    verify.add_argument("--end-date", default="2024-02-01")
    verify.add_argument("--limit", type=int, default=5)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "interactive"):
        interactive_main()
        return 0
    if args.command == "datasets":
        from .batch import list_datasets

        list_datasets()
        return 0
    if args.command == "download":
        from .batch import download

        download(
            dataset_id=args.dataset,
            departments=args.department,
            start_date=args.start_date,
            end_date=args.end_date,
            include_csv=args.csv,
            base_dir=args.output_dir,
            workers=args.workers,
        )
        return 0
    if args.command == "verify-atlantico":
        return _verify_atlantico(args)

    parser.error(f"Comando no soportado: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
