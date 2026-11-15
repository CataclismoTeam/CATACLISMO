"""Pruebas estándar para CATA, LUCIA, Aprendizaje Continuo y Live NRT (Hydrogen xHigh)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from app import live_nrt
from app.cata import config as cata_config
from app.cata import model as cata_model
from app.cata import train as cata_train
from app.continual import adapter as continual_adapter
from app.lucia import config as lucia_config
from app.lucia import model as lucia_model
from app.lucia import prototype_astar
from app.lucia import router as lucia_router


class TestCataPipeline(unittest.TestCase):
    def test_normalize_contract_channels_bounds(self) -> None:
        shape = (2, 4, 4)
        zeros = np.zeros(shape, dtype=np.float32)
        n_obs = np.full(shape, 5.0, dtype=np.float32)
        raw = {
            "frp_sum_mw": np.full(shape, 120.0, dtype=np.float32),
            "frp_max_mw": np.full(shape, 60.0, dtype=np.float32),
            "frp_mean_mw": np.full(shape, 24.0, dtype=np.float32),
            "frp_p50_mw": np.full(shape, 18.0, dtype=np.float32),
            "n_obs": n_obs,
            "n_high_conf": np.full(shape, 3.0, dtype=np.float32),
            "confidence_rank_max": np.full(shape, 2.0, dtype=np.float32),
            "n_day": np.full(shape, 3.0, dtype=np.float32),
            "n_night": np.full(shape, 2.0, dtype=np.float32),
            "footprint_max_km": np.full(shape, 1.5, dtype=np.float32),
            "n_platforms": np.full(shape, 2.0, dtype=np.float32),
            "product_mix": np.full(shape, 0.5, dtype=np.float32),
            "fwi": np.full(shape, 35.0, dtype=np.float32),
            "wind_speed_ms": np.full(shape, 10.0, dtype=np.float32),
            "humidity_pct": np.full(shape, 25.0, dtype=np.float32),
            "temp_c": np.full(shape, 34.0, dtype=np.float32),
            "days_since_rain_1mm": np.full(shape, 15.0, dtype=np.float32),
            "dry_spell_max_days": np.full(shape, 20.0, dtype=np.float32),
            "precip_30d_mm": np.full(shape, 5.0, dtype=np.float32),
            "combined_flammability": np.full(shape, 4.0, dtype=np.float32),
            "valen_score": np.full(shape, 0.8, dtype=np.float32),
        }
        tensor = cata_train.normalize_contract_channels(raw, cata_config.NUM_CHANNELS)
        self.assertEqual(tensor.shape, (2, 4, 4, 22))
        self.assertTrue(np.all(tensor >= 0.0) and np.all(tensor <= 1.0))

        # Celda sin detecciones debe dejar canales satelitales a cero
        for k in ("frp_sum_mw", "frp_max_mw", "frp_mean_mw", "frp_p50_mw", "n_obs", "n_high_conf"):
            raw[k] = zeros
        tensor_zero = cata_train.normalize_contract_channels(raw, cata_config.NUM_CHANNELS)
        self.assertTrue(np.all(tensor_zero[..., :13] == 0.0))

    def test_classify_cata_quadrants_states(self) -> None:
        seq = np.zeros((5, 4, 4, 22), dtype=np.float32)
        seq[-1, 0, 0, 0] = 0.6  # Quemado real que persiste
        seq[-1, 0, 1, 0] = 0.5  # Quemado real que se apaga
        seq[0, 1, 0, 0] = 0.4  # Quemado histórico en t=0

        probs = np.zeros((4, 4), dtype=np.float32)
        probs[0, 0] = 0.85  # estado 3 (PERSISTENT)
        probs[0, 1] = 0.10  # estado 2 (CONFIRMED_BURNED)
        probs[2, 2] = 0.75  # estado 1 (PREDICTED_FIRE)

        res_hist = cata_model.classify_cata_quadrants(
            seq, probs, threshold=0.5, include_history_burned=True
        )
        sm = res_hist["state_matrix"]
        self.assertEqual(int(sm[0, 0]), cata_config.QUADRANT_STATE_PERSISTENT)
        self.assertEqual(int(sm[0, 1]), cata_config.QUADRANT_STATE_BURNED_REAL)
        self.assertEqual(int(sm[1, 0]), cata_config.QUADRANT_STATE_BURNED_REAL)
        self.assertEqual(int(sm[2, 2]), cata_config.QUADRANT_STATE_PREDICTED)
        self.assertEqual(int(sm[3, 3]), cata_config.QUADRANT_STATE_SAFE)

        res_last = cata_model.classify_cata_quadrants(
            seq, probs, threshold=0.5, include_history_burned=False
        )
        self.assertEqual(int(res_last["state_matrix"][1, 0]), cata_config.QUADRANT_STATE_SAFE)

    def test_build_cata_model_forward_loss_and_export(self) -> None:
        cfg = cata_config.ModelConfig(
            height=8,
            width=8,
            time_steps=3,
            num_channels=22,
            convlstm_filters=(4,),
            head_filters=(4,),
            dropout=0.0,
        )
        model = cata_model.build_cata_model(cfg)
        x = np.zeros((1, 3, 8, 8, 22), dtype=np.float32)
        x[0, -1, 3, 3, 0] = 0.7
        out = cata_model.cata_predict(model, x[0])
        self.assertEqual(out.shape, (8, 8))
        self.assertTrue(np.all(out >= 0.0) and np.all(out <= 1.0))

        loss_fn = cata_model.BCEDiceLoss()
        y_true = np.zeros((1, 8, 8, 1), dtype=np.float32)
        y_true[0, 3, 3, 0] = 1.0
        loss_val = float(loss_fn(y_true, out[None, ..., None]).numpy())
        self.assertTrue(np.isfinite(loss_val) and loss_val >= 0.0)

        with tempfile.TemporaryDirectory() as tmp:
            out_json = os.path.join(tmp, "cata_predictions.json")
            state_path = os.path.join(tmp, "continual.json")
            temp_engine = continual_adapter.ContinualLearningEngine(state_path=state_path)
            with mock.patch("app.continual.continual_engine", temp_engine):
                payload = cata_model.export_cata_predictions_for_lucia(
                    model=model,
                    sequence=x,
                    output_path=out_json,
                    patch_origins=[
                        {
                            "zone_id": "ES1K_block_1750_2850_test",
                            "origin_iy": 1750,
                            "origin_ix": 2850,
                        }
                    ],
                )
            self.assertTrue(os.path.exists(out_json))
            self.assertEqual(len(payload["zones"]), 1)
            self.assertEqual(len(payload["zones"][0]["state_matrix"]), 8)


class TestLuciaRouting(unittest.TestCase):
    @staticmethod
    def _build_zone(h: int = 10, w: int = 10) -> dict:
        state = np.zeros((h, w), dtype=np.int8)
        probs = np.full((h, w), 0.02, dtype=np.float32)
        arrival = np.full((h, w), 24.0, dtype=np.float32)

        # Foco central (filas 4..5, cols 4..5)
        state[4:6, 4:6] = lucia_config.QUADRANT_STATE_PERSISTENT
        probs[4:6, 4:6] = 0.92
        arrival[4:6, 4:6] = 0.0

        # Franja de riesgo por encima de threshold en col 3
        probs[4:6, 3] = 0.40
        arrival[4:6, 3] = 2.0

        return {
            "zone_id": "ES1K_block_1750_2850_unit",
            "origin_iy": 1750,
            "origin_ix": 2850,
            "cell_size_m": 1000.0,
            "state_matrix": state.tolist(),
            "fire_probability_grid": probs.tolist(),
            "estimated_fire_arrival_hours": arrival.tolist(),
            "human_traversal_cost_grid": np.ones((h, w), dtype=np.float32).tolist(),
            "animal_traversal_cost_grid": np.ones((h, w), dtype=np.float32).tolist(),
        }

    def test_safety_classification_and_evacuation_route(self) -> None:
        zone = self._build_zone()
        safety = lucia_router.classify_zone_fire_safety(zone, safe_fire_threshold=0.25)
        self.assertEqual(int(safety["category_code"][4, 4]), 3)  # BURNING_ACTIVE
        self.assertEqual(int(safety["category_code"][4, 3]), 1)  # THRESHOLD_BUFFER_UNSAFE
        self.assertEqual(int(safety["category_code"][0, 9]), 0)  # SAFE_UNBURNED

        feats = lucia_model.extract_lucia_features_from_zone(zone)
        targets = lucia_model.compute_analytic_target_fields(feats)
        tf_fields = {
            "human_risk_field": targets[..., 0],
            "animal_risk_field": targets[..., 1],
            "safe_haven_score": targets[..., 2],
        }
        havens = lucia_router.identify_safe_havens(
            safety,
            np.asarray(zone["fire_probability_grid"], dtype=np.float32),
            tf_fields["safe_haven_score"],
        )
        self.assertIn((9, 9), havens)

        route = lucia_router.find_safe_evacuation_route(
            zone=zone,
            tf_fields=tf_fields,
            start_rc=(4, 2),
            profile="human",
            target_havens=havens,
            safe_fire_threshold=0.25,
        )
        self.assertIsNotNone(route)
        path_rc = [tuple(p) for p in route["path_grid_rc"]]
        self.assertEqual(path_rc[0], (4, 2))
        self.assertIn(path_rc[-1], havens)
        # No debe pisar jamás fuego ni threshold buffer
        for r, c in path_rc:
            self.assertEqual(int(safety["category_code"][r, c]), 0)

    def test_prototype_astar_escape(self) -> None:
        mapa = [
            ".......",
            "..FFF..",
            ".......",
            ".S.....",
            "......E",
        ]
        geo = prototype_astar.GeoReferencia(
            lat_origen=37.95, lon_origen=-6.54, resolucion_metros=1000.0
        )
        lat, lon = geo.grid_a_latlon(1, 2)
        self.assertEqual(geo.latlon_a_grid(lat, lon), (1, 2))
        ruta, tiempo_fuego = prototype_astar.encontrar_via_escape(mapa, velocidad_persona=4.0)
        self.assertIsNotNone(ruta)
        self.assertEqual(ruta[0], (3, 1))
        self.assertEqual(ruta[-1], (4, 6))
        self.assertEqual(len(tiempo_fuego), len(mapa))
        for r, c in ruta:
            self.assertNotEqual(mapa[r][c], "F")


class TestContinualLearningAndLiveNRT(unittest.TestCase):
    def test_continual_engine_isolated_calibration_and_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "continual_state.json")
            engine = continual_adapter.ContinualLearningEngine(state_path=state_path)

            fb1 = engine.register_field_feedback(
                "ES1K_block_1750_2850_t1", "confirmed_fire", intensity=1.5
            )
            bias1 = fb1["block_state"]["logit_bias"]
            self.assertGreater(bias1, 0.0)

            probs = np.full((1, 4, 4), 0.45, dtype=np.float32)
            origins = [{"zone_id": "ES1K_block_1750_2850_t1"}]
            cal = engine.calibrate_cata_probabilities(probs, origins)
            self.assertGreater(float(cal[0, 0, 0]), float(probs[0, 0, 0]))

            # Feedback falsa alarma reduce el sesgo
            fb2 = engine.register_field_feedback(
                "ES1K_block_1750_2850_t1", "false_alarm", intensity=2.0
            )
            self.assertLess(fb2["block_state"]["logit_bias"], bias1)
            # Regresión: register_field_feedback no debe compartir referencia entre fb1 y fb2
            self.assertIsNot(fb1["block_state"], fb2["block_state"])

            # Target futuro todo a cero debe devolver updated=False
            res_empty = engine.update_cata_from_observation(
                model=None,
                seq_batch=np.zeros((1, 3, 4, 4, 22), dtype=np.float32),
                probs_batch=probs,
                y_true_batch=np.zeros((1, 4, 4), dtype=np.float32),
                patch_origins=origins,
                enable_head_micro_step=False,
            )
            self.assertFalse(res_empty["updated"])
            self.assertEqual(res_empty["reason"], "future_unobserved_t1")

            # Con target positivo actualiza métricas
            y_pos = np.zeros((1, 4, 4), dtype=np.float32)
            y_pos[0, 1, 1] = 1.0
            res_ok = engine.update_cata_from_observation(
                model=None,
                seq_batch=np.zeros((1, 3, 4, 4, 22), dtype=np.float32),
                probs_batch=probs,
                y_true_batch=y_pos,
                patch_origins=origins,
                enable_head_micro_step=False,
            )
            self.assertTrue(res_ok["updated"])

    def test_live_nrt_firms_aggregation_and_error_paths(self) -> None:
        sample_rows = [
            {
                "latitude": "37.95",
                "longitude": "-6.54",
                "acq_date": "2026-07-18",
                "acq_time": "1430",
                "confidence": "h",
                "frp": "42.5",
                "scan": "0.4",
                "track": "0.4",
                "daynight": "D",
                "satellite": "N20",
                "_source": "VIIRS_NOAA20_NRT",
            },
            {
                "latitude": "37.95",
                "longitude": "-6.54",
                "acq_date": "2026-07-18",
                "acq_time": "1610",
                "confidence": "85",
                "frp": "18.0",
                "scan": "1.1",
                "track": "1.0",
                "daynight": "D",
                "satellite": "Terra",
                "_source": "MODIS_NRT",
            },
        ]
        fake_meteo = {"temperature": 36.0, "humidity": 18.0, "wind_speed": 7.5, "fwi": 44.0}
        with mock.patch.object(live_nrt, "fetch_open_meteo_current", return_value=fake_meteo):
            df_6h, meteo = live_nrt.build_live_cell_6h_from_firms(sample_rows)

        self.assertEqual(len(df_6h), 2)  # VIIRS y MODIS en slot "2026-07-18 12:00"
        self.assertTrue(all(cid.startswith("ES1K:L0:") for cid in df_6h["cell_id"]))
        self.assertTrue(all(dt == "2026-07-18 12:00" for dt in df_6h["date"]))
        self.assertEqual(len(meteo), 2)

        with tempfile.TemporaryDirectory() as tmp:
            status_path = os.path.join(tmp, "live_status.json")
            with (
                mock.patch.object(live_nrt, "LIVE_STATUS_PATH", status_path),
                mock.patch.object(live_nrt, "_get_firms_map_key", return_value=""),
            ):
                with self.assertRaises(RuntimeError):
                    live_nrt.run_live_nrt_cycle(days=1)

            with (
                mock.patch.object(live_nrt, "LIVE_STATUS_PATH", status_path),
                mock.patch.object(live_nrt, "_get_firms_map_key", return_value="TESTKEY"),
                mock.patch.object(live_nrt, "fetch_firms_nrt_csv", return_value=[]),
            ):
                res = live_nrt.run_live_nrt_cycle(days=1)
                self.assertEqual(res["status"], "no_active_fires_in_iberia")
                self.assertTrue(os.path.exists(status_path))


if __name__ == "__main__":
    unittest.main()
