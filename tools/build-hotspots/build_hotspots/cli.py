"""Línea de órdenes: `build-hotspots --in data/raw --out frontend/public/data`."""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import SPAIN_BBOX, Config, Grid
from .export import INCIDENTS, write_json, write_outputs
from .harmonize import harmonize
from .incidents import Regions, build_incidents
from .ingest import DiscardLog, apply_filters, find_inputs, read_records

KM_PER_DEGREE = 111.32


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="build-hotspots",
        description="Armoniza las detecciones FIRMS de MODIS y VIIRS y genera agregados "
        "mensuales por celda para la web.",
    )
    p.add_argument("--in", dest="src", type=Path, required=True, help="carpeta con los JSON")
    p.add_argument("--out", type=Path, required=True, help="carpeta de salida publicada")
    p.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("OESTE", "SUR", "ESTE", "NORTE"),
        default=SPAIN_BBOX,
        help="área en grados (por defecto, España completa)",
    )
    size = p.add_mutually_exclusive_group()
    size.add_argument("--cell-deg", type=float, help="lado de celda en grados (por defecto 0,05)")
    size.add_argument("--cell-km", type=float, help="lado de celda aproximado en km")
    p.add_argument("--types", type=int, nargs="+", default=[0], help="tipos FIRMS que cuentan")
    p.add_argument("--modis-min-confidence", type=int, default=30)
    p.add_argument("--keep-viirs-low", action="store_true", help="no descartar VIIRS 'l'")
    p.add_argument("--recent-days", type=int, default=90)
    p.add_argument("--interim", type=Path, help="carpeta para la tabla Parquet normalizada")
    p.add_argument(
        "--regions",
        type=Path,
        help="carpeta con spain-communities.geojson y spain-provinces.geojson; "
        "sin ella no se generan los incendios por comunidad autónoma",
    )
    p.add_argument("--seed", type=int, default=Config().seed)
    p.add_argument("--generated", help="fecha ISO de generación (por defecto, ahora en UTC)")
    return p.parse_args(argv)


def config_from(args: argparse.Namespace) -> Config:
    if args.cell_km:
        # Se redondea a milésimas de grado para que la rejilla sea reproducible
        cell = round(args.cell_km / KM_PER_DEGREE, 3)
    else:
        cell = args.cell_deg or 0.05
    return Config(
        grid=Grid(*args.bbox, cell_deg=cell),
        types=tuple(args.types),
        modis_min_confidence=args.modis_min_confidence,
        viirs_drop_low=not args.keep_viirs_low,
        recent_days=args.recent_days,
        seed=args.seed,
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    cfg = config_from(args)
    log = DiscardLog()

    raw = read_records(find_inputs(args.src), log)
    read_count = raw.height + log.total()
    if args.interim:
        args.interim.mkdir(parents=True, exist_ok=True)
        raw.write_parquet(args.interim / "detections.parquet", compression="zstd")

    df = apply_filters(raw, cfg, log)
    result = harmonize(df, cfg)
    generated = args.generated or datetime.now(UTC).replace(microsecond=0).isoformat()
    manifest = write_outputs(args.out, df, result, cfg, log, read_count, generated)

    if args.regions:
        regions = Regions(
            args.regions / "spain-communities.geojson", args.regions / "spain-provinces.geojson"
        )
        since = df["date"].max() - timedelta(days=cfg.recent_days - 1)
        incidents = build_incidents(df, regions, since)
        info = write_json(args.out, INCIDENTS, incidents)
        print(
            f"Incendios: {len(incidents['incendios'])} en {len(incidents['comunidades'])} "
            f"comunidades ({info['bytes'] // 1024} KB)"
        )

    print(f"Leídas {read_count} detecciones; usadas {df.height}; descartadas {log.total()}:")
    for row in log.rows:
        print(f"  - {row['descartadas']:>7}  {row['sensor']:<6} {row['paso']}")
    metodo = manifest["metodo"]
    print(f"Factor global MODIS/VIIRS: {metodo['factorGlobal']}")
    print("Factores por mes (ene-dic):", " ".join(f"{k:.3f}" for k in metodo["factores"]))
    print("Diagnóstico:", metodo["diagnostico"])
    total_kb = sum(f["bytes"] for f in manifest["ficheros"] + manifest["anios"]) / 1024
    print(f"Escritos {len(manifest['anios']) + 3} ficheros en {args.out} ({total_kb:.0f} KB)")


if __name__ == "__main__":
    main()
