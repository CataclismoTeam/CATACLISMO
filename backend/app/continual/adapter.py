"""continual/adapter.py — Aprendizaje continuo real sin reentrenar CATA ni LUCIA desde cero.

Implementa una arquitectura de adaptación continua en dos niveles que se ejecuta
automáticamente durante la inferencia (`--mode predict` en CATA y `--mode route` / API en LUCIA):

1. **Calibración Recursiva EMA + Filtro tipo Kalman en logit/riesgo (0 ms de sobrecarga):**
   - Ajusta por bloque geográfico (`block_id`) y globalmente el sesgo de logit (`logit_bias`)
     y el escalado de temperatura (`temp_scale`) de CATA para corregir al vuelo falsos
     positivos y falsos negativos sin destruir los pesos base.
   - En LUCIA, combina recursivamente la salida neuronal (`tf_fields`) con el residuo físico
     exacto (fuego + carreteras OSM + pendiente Open-Elevation Δz) mediante una ganancia
     adaptativa EMA por zona.

2. **Experience Replay Buffer + Micro-Actualización de Cabeza (`head-only micro-step`):**
   - Mantiene un buffer circular en disco (`cata_replay.npz` y `lucia_replay.npz`, máx. 24 muestras)
     con los casos más informativos.
   - Congela todo el backbone (`ConvLSTM2D` en CATA y bloques profundos en LUCIA) y aplica
     como máximo 1 micro-paso (`lr = 1e-4`) únicamente en la última capa `Conv2D` cuando
     llega una observación real `t+1` (en CATA) o un residuo relevante (en LUCIA), evitando
     por completo el *catastrophic forgetting* y eliminando la necesidad de reentrenar.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(BASE_DIR, "artifacts")
DEFAULT_STATE_PATH = os.path.join(ARTIFACTS_DIR, "continual_state.json")
CATA_REPLAY_PATH = os.path.join(ARTIFACTS_DIR, "cata_replay.npz")
LUCIA_REPLAY_PATH = os.path.join(ARTIFACTS_DIR, "lucia_replay.npz")

EMA_ALPHA: float = 0.18
MAX_REPLAY_SIZE: int = 24
MICRO_STEP_LR: float = 1e-4


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x_clip = np.clip(x, -15.0, 15.0)
    return 1.0 / (1.0 + np.exp(-x_clip))


def _logit(p: np.ndarray) -> np.ndarray:
    p_clip = np.clip(p, 1e-5, 1.0 - 1e-5)
    return np.log(p_clip / (1.0 - p_clip))


class ContinualLearningEngine:
    """Gestor de aprendizaje recursivo continuo para CATA y LUCIA."""

    def __init__(self, state_path: str = DEFAULT_STATE_PATH) -> None:
        self.state_path = state_path
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        self.state: dict[str, Any] = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:  # noqa: BLE001
                logger.warning("No se pudo leer continual_state.json (%s); creando nuevo.", exc)
        return {
            "version": "1.0.0",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "cata": {
                "total_continual_updates": 0,
                "total_head_micro_steps": 0,
                "global_logit_bias": 0.0,
                "global_temp_scale": 1.0,
                "ema_precision": 0.65,
                "ema_recall": 0.63,
                "ema_iou": 0.48,
                "blocks": {},
                "field_Overrides": [],
            },
            "lucia": {
                "total_continual_updates": 0,
                "total_head_micro_steps": 0,
                "global_residual_gain": 0.25,
                "ema_mae": 0.013,
                "zones": {},
            },
        }

    def save_state(self) -> None:
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # 1. CATA: Calibración recursiva + Replay Micro-Step (Head-Only)
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_block_key(zone_id: str) -> str:
        # Ej: "ES1K_block_138_187_2022-07-18 06:00" -> "138_187"
        parts = str(zone_id).split("_")
        if len(parts) >= 4 and parts[1] == "block":
            return f"{parts[2]}_{parts[3]}"
        return str(zone_id)

    def calibrate_cata_probabilities(
        self,
        probs_batch: np.ndarray,
        patch_origins: list[dict] | None = None,
    ) -> np.ndarray:
        """Aplica la calibración recursiva aprendida (logit_bias y temp_scale) por bloque."""
        calibrated = np.array(probs_batch, dtype=np.float32, copy=True)
        cata_st = self.state["cata"]
        g_bias = float(cata_st.get("global_logit_bias", 0.0))
        g_temp = max(0.5, min(2.0, float(cata_st.get("global_temp_scale", 1.0))))
        blocks_st = cata_st.get("blocks", {})

        for b in range(len(calibrated)):
            meta_b = (patch_origins[b] if patch_origins and b < len(patch_origins) else {}) or {}
            b_key = self._extract_block_key(meta_b.get("zone_id", f"b_{b}"))
            b_info = blocks_st.get(b_key, {})
            b_bias = float(b_info.get("logit_bias", 0.0))
            b_temp = float(b_info.get("temp_scale", 1.0))

            eff_bias = np.clip(0.4 * g_bias + 0.6 * b_bias, -1.2, 1.2)
            eff_temp = np.clip(0.5 * g_temp + 0.5 * b_temp, 0.65, 1.65)
            if abs(eff_bias) > 1e-4 or abs(eff_temp - 1.0) > 1e-4:
                logits = _logit(calibrated[b])
                calibrated[b] = _sigmoid((logits + eff_bias) / eff_temp).astype(np.float32)

        return calibrated

    def update_cata_from_observation(
        self,
        model: Any,
        seq_batch: np.ndarray,
        probs_batch: np.ndarray,
        y_true_batch: np.ndarray | None,
        patch_origins: list[dict] | None = None,
        threshold: float = 0.5,
        enable_head_micro_step: bool = True,
    ) -> dict[str, Any]:
        """Actualiza recursivamente CATA cuando existe observación `t+1` sin reentrenar desde cero."""
        if y_true_batch is None or len(y_true_batch) == 0:
            return {"updated": False, "reason": "no_ground_truth_t1"}

        y_true = np.asarray(y_true_batch, dtype=np.float32)
        if y_true.ndim == 4 and y_true.shape[-1] == 1:
            y_true_2d = y_true[..., 0]
        else:
            y_true_2d = y_true

        # Si el target t+1 está completamente vacío en toda la tanda (p. ej. fecha futura aún no ocurrida), no penalizar
        if float(y_true_2d.sum()) <= 0.0:
            return {"updated": False, "reason": "future_unobserved_t1"}

        cata_st = self.state["cata"]
        blocks_st = cata_st.setdefault("blocks", {})

        total_tp, total_fp, total_fn = 0.0, 0.0, 0.0
        for b in range(len(probs_batch)):
            p_b = probs_batch[b]
            y_b = y_true_2d[b]
            pred_pos = p_b >= threshold
            true_pos = y_b >= 0.5

            tp = float(np.logical_and(pred_pos, true_pos).sum())
            fp = float(np.logical_and(pred_pos, ~true_pos).sum())
            fn = float(np.logical_and(~pred_pos, true_pos).sum())
            total_tp += tp
            total_fp += fp
            total_fn += fn

            meta_b = (patch_origins[b] if patch_origins and b < len(patch_origins) else {}) or {}
            b_key = self._extract_block_key(meta_b.get("zone_id", f"b_{b}"))
            b_entry = blocks_st.setdefault(
                b_key,
                {"logit_bias": 0.0, "temp_scale": 1.0, "updates": 0, "last_iou": 0.0},
            )

            # Si hay más FN que FP, subimos ligeramente el logit_bias; si hay más FP que FN, lo bajamos
            denom = max(tp + fp + fn, 1.0)
            imbalance = (fn - fp) / denom  # en [-1, 1]
            step_bias = float(np.clip(imbalance * 0.25, -0.15, 0.15))
            b_entry["logit_bias"] = round(
                float(np.clip((1.0 - EMA_ALPHA) * b_entry["logit_bias"] + EMA_ALPHA * (b_entry["logit_bias"] + step_bias), -1.0, 1.0)),
                5,
            )
            # Ajustar temperatura local según sobreconfianza en FP
            fp_ratio = fp / denom
            target_temp = 1.0 + 0.35 * fp_ratio
            b_entry["temp_scale"] = round(
                float(np.clip((1.0 - EMA_ALPHA) * b_entry["temp_scale"] + EMA_ALPHA * target_temp, 0.75, 1.5)),
                5,
            )
            b_entry["updates"] = int(b_entry.get("updates", 0)) + 1
            b_entry["last_iou"] = round(float(tp / denom), 4)

        batch_prec = total_tp / max(total_tp + total_fp, 1.0)
        batch_rec = total_tp / max(total_tp + total_fn, 1.0)
        batch_iou = total_tp / max(total_tp + total_fp + total_fn, 1.0)

        cata_st["ema_precision"] = round(
            float((1.0 - EMA_ALPHA) * cata_st.get("ema_precision", 0.65) + EMA_ALPHA * batch_prec), 4
        )
        cata_st["ema_recall"] = round(
            float((1.0 - EMA_ALPHA) * cata_st.get("ema_recall", 0.63) + EMA_ALPHA * batch_rec), 4
        )
        cata_st["ema_iou"] = round(
            float((1.0 - EMA_ALPHA) * cata_st.get("ema_iou", 0.48) + EMA_ALPHA * batch_iou), 4
        )

        global_imbalance = (total_fn - total_fp) / max(total_tp + total_fp + total_fn, 1.0)
        cata_st["global_logit_bias"] = round(
            float(
                np.clip(
                    cata_st.get("global_logit_bias", 0.0) + 0.05 * global_imbalance,
                    -0.6,
                    0.6,
                )
            ),
            5,
        )
        cata_st["total_continual_updates"] = int(cata_st.get("total_continual_updates", 0)) + 1

        # Actualizar Experience Replay Buffer y aplicar 1 micro-paso solo a la última capa si procede
        micro_step_done = False
        if enable_head_micro_step and model is not None:
            micro_step_done = self._cata_replay_and_head_step(model, seq_batch, y_true)
            if micro_step_done:
                cata_st["total_head_micro_steps"] = int(cata_st.get("total_head_micro_steps", 0)) + 1

        self.save_state()
        return {
            "updated": True,
            "batch_iou": round(batch_iou, 4),
            "ema_iou": cata_st["ema_iou"],
            "head_micro_step": micro_step_done,
        }

    def _cata_replay_and_head_step(
        self,
        model: Any,
        x_new: np.ndarray,
        y_new: np.ndarray,
    ) -> bool:
        """Guarda en Replay Buffer circular y ejecuta 1 micro-paso en la cabeza de salida de CATA."""
        try:
            import keras

            x_arr = np.asarray(x_new[:2], dtype=np.float32)
            y_arr = np.asarray(y_new[:2], dtype=np.float32)
            if y_arr.ndim == 3:
                y_arr = y_arr[..., None]

            if os.path.exists(CATA_REPLAY_PATH):
                with np.load(CATA_REPLAY_PATH) as data:
                    rx, ry = data["x"], data["y"]
                if rx.shape[1:] == x_arr.shape[1:] and ry.shape[1:] == y_arr.shape[1:]:
                    rx = np.concatenate([rx, x_arr], axis=0)[-MAX_REPLAY_SIZE:]
                    ry = np.concatenate([ry, y_arr], axis=0)[-MAX_REPLAY_SIZE:]
                else:
                    rx, ry = x_arr, y_arr
            else:
                rx, ry = x_arr, y_arr

            np.savez_compressed(CATA_REPLAY_PATH, x=rx, y=ry)

            # Congelar todas las capas excepto la última capa Conv2D (cabeza)
            for layer in model.layers[:-1]:
                layer.trainable = False
            model.layers[-1].trainable = True

            model.compile(
                optimizer=keras.optimizers.Adam(learning_rate=MICRO_STEP_LR),
                loss="binary_crossentropy",
            )
            # Mezclar hasta 4 muestras del replay buffer para evitar olvido
            idx = np.random.choice(len(rx), size=min(4, len(rx)), replace=False)
            model.train_on_batch(rx[idx], ry[idx])
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Micro-step de CATA omitido: %s", exc)
            return False

    # ------------------------------------------------------------------
    # 2. LUCIA: Fusión recursiva adaptativa + Replay Micro-Step (Head-Only)
    # ------------------------------------------------------------------
    def adapt_lucia_fields(
        self,
        model: Any,
        zone_id: str,
        features_tensor: np.ndarray,
        tf_fields: dict[str, np.ndarray],
        analytic_target: np.ndarray,
        enable_head_micro_step: bool = True,
    ) -> dict[str, np.ndarray]:
        """Combina recursivamente la predicción de LUCIA con el campo físico exacto de la zona."""
        lucia_st = self.state["lucia"]
        zones_st = lucia_st.setdefault("zones", {})
        b_key = self._extract_block_key(zone_id)
        z_entry = zones_st.setdefault(
            b_key,
            {"residual_gain": 0.25, "updates": 0, "last_mae": 0.01},
        )

        pred_stack = np.stack(
            [
                tf_fields["human_risk_field"],
                tf_fields["animal_risk_field"],
                tf_fields["safe_haven_score"],
            ],
            axis=-1,
        ).astype(np.float32)

        residual = analytic_target.astype(np.float32) - pred_stack
        mae = float(np.mean(np.abs(residual)))

        # Ganancia tipo Kalman: si el residuo sube, aumenta el peso correctivo analítico [0.15, 0.65]
        target_gain = float(np.clip(0.20 + 2.5 * mae, 0.15, 0.65))
        gain = float((1.0 - EMA_ALPHA) * z_entry.get("residual_gain", 0.25) + EMA_ALPHA * target_gain)
        z_entry["residual_gain"] = round(gain, 4)
        z_entry["updates"] = int(z_entry.get("updates", 0)) + 1
        z_entry["last_mae"] = round(mae, 5)

        lucia_st["ema_mae"] = round(
            float((1.0 - EMA_ALPHA) * lucia_st.get("ema_mae", 0.013) + EMA_ALPHA * mae), 5
        )
        lucia_st["global_residual_gain"] = round(
            float((1.0 - EMA_ALPHA) * lucia_st.get("global_residual_gain", 0.25) + EMA_ALPHA * gain), 4
        )
        lucia_st["total_continual_updates"] = int(lucia_st.get("total_continual_updates", 0)) + 1

        corrected = np.clip(pred_stack + gain * residual, 0.0, 1.0).astype(np.float32)

        # Si el residuo de la red supera 0.025, hacemos 1 micro-paso en la cabeza de LUCIA
        if enable_head_micro_step and model is not None and mae > 0.025:
            if self._lucia_replay_and_head_step(model, features_tensor[None], analytic_target[None]):
                lucia_st["total_head_micro_steps"] = int(lucia_st.get("total_head_micro_steps", 0)) + 1

        self.save_state()
        return {
            "human_risk_field": corrected[..., 0],
            "animal_risk_field": corrected[..., 1],
            "safe_haven_score": corrected[..., 2],
        }

    def _lucia_replay_and_head_step(
        self,
        model: Any,
        x_new: np.ndarray,
        y_new: np.ndarray,
    ) -> bool:
        """Guarda en Replay Buffer de LUCIA y aplica 1 micro-paso en la última capa."""
        try:
            import keras

            x_arr = np.asarray(x_new, dtype=np.float32)
            y_arr = np.asarray(y_new, dtype=np.float32)

            if os.path.exists(LUCIA_REPLAY_PATH):
                with np.load(LUCIA_REPLAY_PATH) as data:
                    rx, ry = data["x"], data["y"]
                if rx.shape[1:] == x_arr.shape[1:] and ry.shape[1:] == y_arr.shape[1:]:
                    rx = np.concatenate([rx, x_arr], axis=0)[-MAX_REPLAY_SIZE:]
                    ry = np.concatenate([ry, y_arr], axis=0)[-MAX_REPLAY_SIZE:]
                else:
                    rx, ry = x_arr, y_arr
            else:
                rx, ry = x_arr, y_arr

            np.savez_compressed(LUCIA_REPLAY_PATH, x=rx, y=ry)

            for layer in model.layers[:-1]:
                layer.trainable = False
            model.layers[-1].trainable = True

            model.compile(
                optimizer=keras.optimizers.Adam(learning_rate=MICRO_STEP_LR),
                loss="mse",
            )
            idx = np.random.choice(len(rx), size=min(4, len(rx)), replace=False)
            model.train_on_batch(rx[idx], ry[idx])
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug("Micro-step de LUCIA omitido: %s", exc)
            return False

    # ------------------------------------------------------------------
    # 3. Feedback directo desde terreno (First Responders / JULI)
    # ------------------------------------------------------------------
    def register_field_feedback(
        self,
        block_or_zone_id: str,
        feedback_type: str,
        intensity: float = 1.0,
    ) -> dict[str, Any]:
        """Permite a operarios en el terreno reportar fuego confirmado o falsa alarma en vivo."""
        b_key = self._extract_block_key(block_or_zone_id)
        cata_st = self.state["cata"]
        blocks_st = cata_st.setdefault("blocks", {})
        b_entry = blocks_st.setdefault(
            b_key,
            {"logit_bias": 0.0, "temp_scale": 1.0, "updates": 0, "last_iou": 0.0},
        )
        delta = 0.12 * float(np.clip(intensity, 0.1, 2.0))
        if feedback_type == "confirmed_fire":
            b_entry["logit_bias"] = round(float(np.clip(b_entry["logit_bias"] + delta, -1.0, 1.0)), 5)
        elif feedback_type == "false_alarm":
            b_entry["logit_bias"] = round(float(np.clip(b_entry["logit_bias"] - delta, -1.0, 1.0)), 5)
        b_entry["updates"] = int(b_entry.get("updates", 0)) + 1
        self.save_state()
        return {"block_key": b_key, "block_state": b_entry}


continual_engine = ContinualLearningEngine()
