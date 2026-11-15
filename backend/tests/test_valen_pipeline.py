"""Pruebas unitarias e integración estándar para el módulo VALEN (Hydrogen xHigh)."""

from __future__ import annotations

import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from app.valen import (
    elevation_client,
    json_output,
    laea,
    meteomatics_client,
    phase1_projection,
    phase2_cell_day,
    rainfall_client,
    roads_client,
    scoring_client,
    vegetation_client,
)


class TestValenLaeaProjection(unittest.TestCase):
    def test_lonlat_epsg3035_roundtrip_iberia(self) -> None:
        points = [
            (-6.54, 37.95),  # Huelva / Aracena
            (-3.70, 40.42),  # Madrid
            (-6.35, 41.78),  # Zamora / Sierra de la Culebra
            (2.17, 41.39),   # Barcelona
        ]
        for lon, lat in points:
            x, y = laea.lonlat_to_epsg3035(lon, lat)
            lon_rt, lat_rt = laea.epsg3035_to_lonlat(x, y)
            self.assertAlmostEqual(lon_rt, lon, delta=1e-4)
            self.assertAlmostEqual(lat_rt, lat, delta=1e-4)

    def test_cell_id_format_parse_and_centroid_1km(self) -> None:
        lon, lat = -6.54, 37.95
        iy, ix = laea.lonlat_to_cell_iy_ix(lon, lat)
        cid = laea.format_cell_id(iy, ix)
        self.assertTrue(cid.startswith("ES1K:L0:Y"))
        self.assertEqual(laea.parse_cell_id(cid), (iy, ix))
        self.assertEqual(laea.lonlat_to_cell_id(lon, lat), cid)

        c_lon, c_lat = laea.cell_centroid_lonlat(iy, ix)
        self.assertEqual(laea.lonlat_to_cell_iy_ix(c_lon, c_lat), (iy, ix))

        south, west, north, east = laea.cell_block_bbox_lonlat(iy, ix, 4, 4)
        self.assertLess(south, north)
        self.assertLess(west, east)

    def test_invalid_cell_id_raises(self) -> None:
        for bad in ("", "ES2K:L0:Y00001:X00001", "ES1K:L0:10:20", "bad"):
            with self.assertRaises(ValueError):
                laea.parse_cell_id(bad)


class TestValenScoringClient(unittest.TestCase):
    def test_normalize_value_modes_and_nan(self) -> None:
        self.assertEqual(scoring_client.normalize_value(None, {"type": "minmax", "min": 0, "max": 10}), 0.0)
        self.assertEqual(scoring_client.normalize_value(float("nan"), {"type": "minmax", "min": 0, "max": 10}), 0.0)
        self.assertAlmostEqual(scoring_client.normalize_value(5, {"type": "minmax", "min": 0, "max": 10}), 0.5)
        self.assertAlmostEqual(scoring_client.normalize_value(20, {"type": "minmax", "min": 0, "max": 10}), 1.0)
        self.assertAlmostEqual(scoring_client.normalize_value(10, {"type": "inverse_minmax", "min": 10, "max": 90}), 1.0)
        self.assertAlmostEqual(scoring_client.normalize_value(90, {"type": "inverse_minmax", "min": 10, "max": 90}), 0.0)
        self.assertEqual(scoring_client.normalize_value(1, {"type": "binary"}), 1.0)
        self.assertEqual(scoring_client.normalize_value(0, {"type": "binary"}), 0.0)
        self.assertAlmostEqual(scoring_client.normalize_value(1.5, {"type": "direct"}), 1.0)

    def test_extract_features_score_and_decisions(self) -> None:
        high_risk_row = pd.Series(
            {
                "sensors_present": "BOTH",
                "confidence_rank_max": 2,
                "n_obs": 10,
                "n_high_conf": 9,
                "fwi": 45.0,
                "wind_speed_10m": 18.0,
                "relative_humidity_2m": 15.0,
                "days_since_rain_1mm": 25.0,
                "dry_spell_max_days": 28.0,
                "precip_30d_mm": 2.0,
                "combined_flammability": 4.8,
                "flags": ["boundary_crossing"],
                "product_mix": 0.9,
            }
        )
        feats_high = scoring_client.extract_features(high_risk_row)
        score_high = scoring_client.valen_compute_score(feats_high)
        self.assertGreater(score_high, 0.7)
        self.assertEqual(scoring_client.valen_decide(score_high), "ACEPTA")

        low_risk_row = pd.Series(
            {
                "sensors_present": "MODIS",
                "confidence_rank_max": 0,
                "n_obs": 1,
                "n_high_conf": 0,
                "fwi": 1.0,
                "wind_speed_10m": 1.0,
                "relative_humidity_2m": 88.0,
                "days_since_rain_1mm": 0.0,
                "dry_spell_max_days": 0.0,
                "precip_30d_mm": 95.0,
                "combined_flammability": 1.0,
                "flags": "[]",
                "product_mix": 0.0,
            }
        )
        score_low = scoring_client.valen_compute_score(scoring_client.extract_features(low_risk_row))
        self.assertLess(score_low, 0.35)
        self.assertEqual(scoring_client.valen_decide(score_low), "RECHAZA")
        self.assertEqual(scoring_client.valen_decide(0.50), "REVISAR_MANUAL")


class TestValenElevationAndRoads(unittest.TestCase):
    def test_elevation_and_tobler_physics(self) -> None:
        elev = elevation_client.estimate_iberian_elevation_m(-6.54, 37.95, 1750, 2850)
        self.assertGreaterEqual(elev, 5.0)
        self.assertAlmostEqual(elevation_client.tobler_hiking_speed_kmh(0.0, 4.5), 4.5, places=3)
        self.assertLess(elevation_client.tobler_hiking_speed_kmh(0.25, 4.5), 4.5)

        flat_mult = elevation_client.compute_slope_cost_multiplier(0.0, 1000.0, "human")
        steep_mult = elevation_client.compute_slope_cost_multiplier(250.0, 1000.0, "human")
        animal_steep = elevation_client.compute_slope_cost_multiplier(250.0, 1000.0, "animal")
        self.assertLess(flat_mult, steep_mult)
        self.assertGreaterEqual(steep_mult, 0.85)
        self.assertLessEqual(steep_mult, 6.0)
        self.assertGreaterEqual(animal_steep, 0.85)
        self.assertLessEqual(animal_steep, 5.0)

        ramp = np.tile(np.arange(8, dtype=np.float32) * 50.0, (8, 1))
        metrics = elevation_client.compute_block_slope_metrics(ramp)
        self.assertEqual(metrics["slope_pct"].shape, (8, 8))
        self.assertTrue(np.all(metrics["human_slope_factor"] >= 1.0))

    def test_roads_client_constants(self) -> None:
        self.assertEqual(roads_client.ALGORITHM_NAME, "valen")
        self.assertEqual(roads_client.CELL_SIZE_M, 1000.0)

    def test_valen_sqlite_caches_and_phase2_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Caches SQLite locales sin red
            rc = roads_client.RoadsCache(db_path=tmp_path / "roads.sqlite")
            bbox = (-6.6, 37.9, -6.5, 38.0)
            rc.set(bbox, [{"id": 1, "tags": {"highway": "track"}}])
            self.assertEqual(len(rc.get(bbox)), 1)

            mc = meteomatics_client.MeteomaticsCache(db_path=tmp_path / "meteo.sqlite")
            mc.set("t_2m:C", 37.95, -6.54, "2026-07-18T00:00Z", "2026-07-18T12:00Z", "PT1H", {"val": 31.2})
            self.assertEqual(
                mc.get("t_2m:C", 37.95, -6.54, "2026-07-18T00:00Z", "2026-07-18T12:00Z", "PT1H")["val"],
                31.2,
            )

            rfc = rainfall_client.RainfallCache(db_path=tmp_path / "rain.sqlite")
            rfc.set_power_daily(-6.54, 37.95, "2026-07-18", {"PRECTOTCORR": 0.0})
            self.assertEqual(rfc.get_power_daily(-6.54, 37.95, "2026-07-18")["PRECTOTCORR"], 0.0)

        # WorldCover tiling
        tx, ty = vegetation_client.lonlat_to_tile(-6.54, 37.95)
        min_lon, min_lat, max_lon, max_lat = vegetation_client.tile_to_bbox(tx, ty)
        self.assertTrue(min_lon <= -6.54 <= max_lon)
        self.assertTrue(min_lat <= 37.95 <= max_lat)
        self.assertIn("ESA_WorldCover_10m_2021_v100_", vegetation_client.get_worldcover_tile_url(tx, ty))

        # Phase 2 aggregation (cell_id + acq_date + sensor -> 15 campos)
        cid = laea.lonlat_to_cell_id(-6.54, 37.95)
        df_obs = pd.DataFrame(
            [
                {
                    "cell_id_L0": cid,
                    "acq_date": "2026-07-18",
                    "sensor": "VIIRS",
                    "frp": 30.0,
                    "daynight": "D",
                    "platform": "NOAA-20",
                    "confidence_rank": 2,
                    "scan": 0.4,
                    "track": 0.4,
                    "product": "NRT",
                    "flags": [],
                },
                {
                    "cell_id_L0": cid,
                    "acq_date": "2026-07-18",
                    "sensor": "VIIRS",
                    "frp": 50.0,
                    "daynight": "N",
                    "platform": "SNPP",
                    "confidence_rank": 1,
                    "scan": 0.5,
                    "track": 0.4,
                    "product": "SP",
                    "flags": ["boundary_crossing"],
                },
            ]
        )
        df_cd = phase2_cell_day.aggregate_cell_day(df_obs, cell_size=1000.0, grid_prefix="ES1K")
        self.assertEqual(len(df_cd), 1)
        row = df_cd.iloc[0]
        self.assertEqual(row["cell_id"], cid)
        self.assertEqual(row["n_obs"], 2)
        self.assertAlmostEqual(float(row["frp_sum_mw"]), 80.0, places=2)


class TestValenPhase1AndJsonOutput(unittest.TestCase):
    def test_parse_acq_time_confidence_and_product(self) -> None:
        self.assertEqual(phase1_projection.parse_acq_time("1345"), 13 * 60 + 45)
        self.assertEqual(phase1_projection.parse_acq_time("0015"), 15)
        self.assertIsNone(phase1_projection.parse_acq_time("2599"))
        self.assertIsNone(phase1_projection.parse_acq_time(float("nan")))

        self.assertEqual(phase1_projection.confidence_to_rank("MODIS", "90"), 2)
        self.assertEqual(phase1_projection.confidence_to_rank("MODIS", "50"), 1)
        self.assertEqual(phase1_projection.confidence_to_rank("MODIS", "10"), 0)
        self.assertEqual(phase1_projection.confidence_to_rank("VIIRS", "h"), 2)
        self.assertEqual(phase1_projection.confidence_to_rank("VIIRS", "nominal"), 1)
        self.assertEqual(phase1_projection.confidence_to_rank("VIIRS", "l"), 0)

        self.assertEqual(phase1_projection.infer_product_from_filename("firms_archive_2022.json"), "SP")
        self.assertEqual(phase1_projection.infer_product_from_filename("firms_nrt_live.json"), "NRT")

    def test_json_array_writer_direct_and_jsonl_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            out_json = tmp_path / "arr_direct.json"
            with json_output.JSONArrayWriter(out_json) as writer:
                writer.write({"id": 1, "val": "a"})
                writer.write_batch([{"id": 2, "val": "b"}, {"id": 3, "val": "c"}])

            loaded = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual([r["id"] for r in loaded], [1, 2, 3])

            jsonl_file = tmp_path / "sample.jsonl"
            jsonl_file.write_text('{"k": 1}\n{"k": 2}\n', encoding="utf-8")
            converted = tmp_path / "sample.json"
            count = json_output.jsonl_to_json_array(jsonl_file, converted)
            self.assertEqual(count, 2)
            self.assertEqual(json.loads(converted.read_text(encoding="utf-8")), [{"k": 1}, {"k": 2}])

    def test_json_array_output_helper_enters_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_json = Path(tmp) / "arr_helper.json"
            with json_output.json_array_output(out_json) as writer:
                writer.write({"id": 1})
            loaded = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(loaded, [{"id": 1}])


if __name__ == "__main__":
    unittest.main()
