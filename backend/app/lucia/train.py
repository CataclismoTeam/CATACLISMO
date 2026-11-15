"""Entrenamiento, expansión modular de canales (channel surgery) y generación GeoJSON de LUCIA.

Uso desde terminal:
  # 1. Entrenar el modelo TensorFlow de LUCIA (C=13 canales) + exportar GeoJSON de rutas desde CATA:
  python -m app.lucia.train --mode train

  # 2. Sólo calcular rutas y exportar GeoJSON desde cata_predictions.json usando el modelo TF:
  python -m app.lucia.train --mode route \
      --cata-input app/cata/artifacts/predictions/cata_predictions.json \
      --geojson-output app/lucia/artifacts/routes/lucia_routes.geojson

  # 3. Expandir canales del modelo TensorFlow de LUCIA (channel surgery):
  python -m app.lucia.train --mode expand \
      --base-model app/lucia/artifacts/models/lucia_c6.keras \
      --num-channels 12
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time

os.environ.setdefault("KERAS_BACKEND", "tensorflow")

import keras
import numpy as np
import tensorflow as tf

# ===========================================================================
# Configuración de Épocas Virtuales, Checkpoints y Smoke Test (DRY_RUN)
# ===========================================================================
DRY_RUN: bool = False
STEPS_PER_EPOCH: int = 500
VALIDATION_STEPS: int = 100
CHECKPOINTS_DIR: str = "checkpoints"

from . import config
from .model import (
    compute_analytic_target_fields,
    compute_distance_to_hazard,
    create_lucia_model,
    expand_lucia_channels,
    extract_lucia_features_from_zone,
    extract_lucia_model_config,
)
from .router import (
    generate_lucia_geojson_from_cata,
    load_elevation_index,
    load_roads_index,
    load_zone_elevation_grids,
    load_zone_road_grids,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. Dataset real (desde CATA) + Generador sintético de escenarios de evacuación
# ===========================================================================
def build_dataset_from_cata_predictions(
    cata_predictions_path: str = config.DEFAULT_CATA_PREDICTIONS_PATH,
    safe_fire_threshold: float = config.SAFE_FIRE_THRESHOLD,
    num_channels: int = config.DEFAULT_NUM_CHANNELS,
    augment_rotations: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Extrae pares `(X, Y)` de entrenamiento a partir de `cata_predictions.json` + OSM + Open-Elevation de VALEN."""
    if not os.path.exists(cata_predictions_path):
        return (
            np.empty((0, config.GRID_SIZE, config.GRID_SIZE, num_channels), dtype=np.float32),
            np.empty((0, config.GRID_SIZE, config.GRID_SIZE, config.OUTPUT_HEAD_CHANNELS), dtype=np.float32),
        )

    with open(cata_predictions_path, encoding="utf-8") as f:
        cata_data = json.load(f)

    roads_index = load_roads_index()
    elevation_index = load_elevation_index()

    cells_by_zone: dict[str, list[dict]] = {}
    for cell in cata_data.get("active_and_predicted_cells", []):
        zid = str(cell.get("zone_id", ""))
        cells_by_zone.setdefault(zid, []).append(cell)

    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []

    for zone in cata_data.get("zones", []):
        zid = str(zone.get("zone_id", ""))
        road_grids = load_zone_road_grids(zone, roads_index, fetch_missing_online=False)
        elevation_grids = load_zone_elevation_grids(
            zone, elevation_index, fetch_missing_online=False
        )
        feat = extract_lucia_features_from_zone(
            zone=zone,
            active_cells_for_zone=cells_by_zone.get(zid, []),
            safe_fire_threshold=safe_fire_threshold,
            num_channels=num_channels,
            road_grids=road_grids,
            elevation_grids=elevation_grids,
        )
        target = compute_analytic_target_fields(feat)
        xs.append(feat)
        ys.append(target)

        if augment_rotations:
            for k in (1, 2, 3):
                xs.append(np.rot90(feat, k=k, axes=(0, 1)).copy())
                ys.append(np.rot90(target, k=k, axes=(0, 1)).copy())
            xs.append(np.fliplr(feat).copy())
            ys.append(np.fliplr(target).copy())

    if not xs:
        return (
            np.empty((0, config.GRID_SIZE, config.GRID_SIZE, num_channels), dtype=np.float32),
            np.empty((0, config.GRID_SIZE, config.GRID_SIZE, config.OUTPUT_HEAD_CHANNELS), dtype=np.float32),
        )

    return np.stack(xs, axis=0), np.stack(ys, axis=0)


def generate_synthetic_lucia_scenarios(
    n_samples: int = 160,
    grid_size: int = config.GRID_SIZE,
    num_channels: int = config.DEFAULT_NUM_CHANNELS,
    safe_fire_threshold: float = config.SAFE_FIRE_THRESHOLD,
    seed: int = config.SEED,
) -> tuple[np.ndarray, np.ndarray]:
    """Genera escenarios variados de incendio (quemado, quemándose, sin quemar + VALEN) para entrenar LUCIA."""
    rng = np.random.default_rng(seed)
    xs = np.zeros((n_samples, grid_size, grid_size, num_channels), dtype=np.float32)
    ys = np.zeros(
        (n_samples, grid_size, grid_size, config.OUTPUT_HEAD_CHANNELS), dtype=np.float32
    )

    rr, cc = np.meshgrid(np.arange(grid_size), np.arange(grid_size), indexing="ij")
    dist_to_border = np.minimum(
        np.minimum(rr, grid_size - 1 - rr), np.minimum(cc, grid_size - 1 - cc)
    ).astype(np.float32)
    max_border = max(1.0, float(grid_size / 2.0))

    for i in range(n_samples):
        already_burned = np.zeros((grid_size, grid_size), dtype=np.float32)
        burning_active = np.zeros((grid_size, grid_size), dtype=np.float32)
        prob_t1 = rng.uniform(0.0, 0.12, size=(grid_size, grid_size)).astype(np.float32)

        n_clusters = int(rng.integers(1, 4))
        for _ in range(n_clusters):
            cr = int(rng.integers(4, grid_size - 4))
            cc_i = int(rng.integers(4, grid_size - 4))
            rad_burned = float(rng.uniform(1.8, 5.0))
            rad_active = rad_burned + float(rng.uniform(1.0, 2.8))
            dist_c = np.sqrt((rr - cr) ** 2 + (cc - cc_i) ** 2, dtype=np.float32)

            already_burned[dist_c <= rad_burned] = 1.0
            ring_active = (dist_c > rad_burned) & (dist_c <= rad_active)
            burning_active[ring_active] = 1.0
            prob_t1 = np.maximum(
                prob_t1,
                np.clip(np.exp(-((dist_c - rad_burned) / 3.2) ** 2), 0.0, 1.0),
            )

        is_burning_or_thresh = ((burning_active > 0.5) | (prob_t1 >= safe_fire_threshold)).astype(
            np.float32
        )
        is_already_burned = ((already_burned > 0.5) & (is_burning_or_thresh < 0.5)).astype(
            np.float32
        )
        is_safe_unburned = ((is_already_burned < 0.5) & (is_burning_or_thresh < 0.5)).astype(
            np.float32
        )

        hazard_mask = (is_already_burned > 0.5) | (is_burning_or_thresh > 0.5)
        dist_fire = compute_distance_to_hazard(hazard_mask)
        prox_risk = np.exp(-dist_fire / 3.5).astype(np.float32)
        urgency = np.clip(prob_t1 * 0.8 + prox_risk * 0.4, 0.0, 1.0).astype(np.float32)

        veg = rng.uniform(0.15, 0.95, size=(grid_size, grid_size)).astype(np.float32)
        wind = np.full((grid_size, grid_size), float(rng.uniform(0.1, 0.85)), dtype=np.float32)
        fwi_temp = np.clip(0.5 * veg + 0.5 * wind, 0.0, 1.0).astype(np.float32)
        human_base = np.clip(0.35 * veg + 0.55 * prob_t1, 0.0, 1.0).astype(np.float32)
        animal_base = np.clip(0.20 * veg + 0.25 * wind + 0.55 * prob_t1, 0.0, 1.0).astype(
            np.float32
        )
        border_aff = (
            (1.0 - dist_to_border / max_border) * is_safe_unburned * (1.0 - prox_risk)
        ).astype(np.float32)

        # Simular corredores de carreteras y pistas forestales (OSM)
        road_access = rng.uniform(0.0, 0.25, size=(grid_size, grid_size)).astype(np.float32)
        for _ in range(int(rng.integers(2, 5))):
            if rng.random() < 0.5:
                r_line = int(rng.integers(1, grid_size - 1))
                road_access[r_line, :] = np.maximum(road_access[r_line, :], rng.uniform(0.65, 1.0))
            else:
                c_line = int(rng.integers(1, grid_size - 1))
                road_access[:, c_line] = np.maximum(road_access[:, c_line], rng.uniform(0.65, 1.0))

        # Simular relieve continuo de elevación y pendiente (Open-Elevation)
        hr_c = int(rng.integers(4, grid_size - 4))
        hc_c = int(rng.integers(4, grid_size - 4))
        hill_dist = np.sqrt((rr - hr_c) ** 2 + (cc - hc_c) ** 2, dtype=np.float32)
        elevation_norm = np.clip(
            0.20
            + 0.65 * np.exp(-((hill_dist / float(rng.uniform(5.0, 11.0))) ** 2))
            + rng.normal(0.0, 0.03, size=(grid_size, grid_size)),
            0.0,
            1.0,
        ).astype(np.float32)
        gy, gx = np.gradient(elevation_norm)
        slope_steepness = np.clip(np.hypot(gy, gx) * 5.0, 0.0, 1.0).astype(np.float32)

        ch_list = [
            is_safe_unburned,
            is_burning_or_thresh,
            is_already_burned,
            prob_t1,
            prox_risk,
            urgency,
            human_base,
            animal_base,
            veg,
            wind,
            fwi_temp,
            border_aff,
            road_access,
            elevation_norm,
            slope_steepness,
        ]
        full = np.stack(ch_list, axis=-1).astype(np.float32)
        feat = full[..., :num_channels]
        xs[i] = feat
        ys[i] = compute_analytic_target_fields(feat)

    return xs, ys


# ===========================================================================
# 2. Persistencia de metadatos y entrenamiento
# ===========================================================================
def save_lucia_metadata(model: keras.Model, model_path: str, extra: dict | None = None) -> str:
    cfg = extract_lucia_model_config(model)
    meta = {
        "algorithm": config.ALGORITHM_NAME,
        "pipeline": list(config.PIPELINE_CHAIN),
        "model_path": os.path.basename(model_path),
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "grid_size": cfg.grid_size,
        "num_channels": cfg.num_channels,
        "channel_names": list(cfg.channel_names),
        "conv_filters": list(cfg.conv_filters),
        "kernel_size": list(cfg.kernel_size),
        "dropout_rate": cfg.dropout_rate,
        "safe_fire_threshold": config.SAFE_FIRE_THRESHOLD,
        **(extra or {}),
    }
    meta_path = os.path.splitext(model_path)[0] + ".meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    return meta_path


def run_lucia_training_pipeline(
    cata_predictions_path: str = config.DEFAULT_CATA_PREDICTIONS_PATH,
    save_model_path: str = config.DEFAULT_MODEL_PATH,
    output_geojson_path: str = config.DEFAULT_GEOJSON_OUTPUT_PATH,
    num_channels: int = config.DEFAULT_NUM_CHANNELS,
    safe_fire_threshold: float = config.SAFE_FIRE_THRESHOLD,
    epochs: int = config.EPOCHS,
    batch_size: int = config.BATCH_SIZE,
) -> dict:
    """Entrena el modelo TensorFlow de LUCIA y genera inmediatamente `lucia_routes.geojson`."""
    keras.utils.set_random_seed(config.SEED)

    x_real, y_real = build_dataset_from_cata_predictions(
        cata_predictions_path=cata_predictions_path,
        safe_fire_threshold=safe_fire_threshold,
        num_channels=num_channels,
        augment_rotations=True,
    )
    x_syn, y_syn = generate_synthetic_lucia_scenarios(
        n_samples=160,
        grid_size=config.GRID_SIZE,
        num_channels=num_channels,
        safe_fire_threshold=safe_fire_threshold,
        seed=config.SEED,
    )

    if len(x_real) > 0:
        # Sobremuestrear las zonas reales de CATA para anclar el aprendizaje a los incendios reales
        x_all = np.concatenate([np.repeat(x_real, 3, axis=0), x_syn], axis=0)
        y_all = np.concatenate([np.repeat(y_real, 3, axis=0), y_syn], axis=0)
    else:
        x_all, y_all = x_syn, y_syn

    rng = np.random.default_rng(config.SEED)
    perm = rng.permutation(len(x_all))
    x_all, y_all = x_all[perm], y_all[perm]

    n_val = max(8, int(len(x_all) * 0.15))
    x_train, y_train = x_all[:-n_val], y_all[:-n_val]
    x_val, y_val = x_all[-n_val:], y_all[-n_val:]

    model = create_lucia_model(
        grid_size=config.GRID_SIZE,
        num_channels=num_channels,
    )
    os.makedirs(os.path.dirname(os.path.abspath(save_model_path)), exist_ok=True)
    os.makedirs(CHECKPOINTS_DIR, exist_ok=True)

    train_ds = (
        tf.data.Dataset.from_tensor_slices((x_train, y_train))
        .shuffle(len(x_train), seed=config.SEED, reshuffle_each_iteration=True)
        .batch(batch_size)
        .repeat()
        .prefetch(tf.data.AUTOTUNE)
    )
    val_ds = (
        tf.data.Dataset.from_tensor_slices((x_val, y_val))
        .batch(batch_size)
        .repeat()
        .prefetch(tf.data.AUTOTUNE)
    )

    steps_per_epoch = STEPS_PER_EPOCH
    validation_steps = VALIDATION_STEPS if val_ds is not None else None
    if DRY_RUN:
        epochs = 2
        steps_per_epoch = 5
        validation_steps = 2 if val_ds is not None else None

    monitor_metric = "val_loss" if val_ds is not None else "loss"
    callbacks = [
        tf.keras.callbacks.ModelCheckpoint(
            filepath=os.path.join(CHECKPOINTS_DIR, "best_model.keras"),
            monitor=monitor_metric,
            save_best_only=True,
            save_weights_only=False,
            verbose=1,
        ),
        tf.keras.callbacks.ModelCheckpoint(
            filepath=os.path.join(CHECKPOINTS_DIR, "latest_backup.keras"),
            save_freq=500,
            save_best_only=False,
        ),
        tf.keras.callbacks.EarlyStopping(
            monitor=monitor_metric,
            patience=5,
            restore_best_weights=True,
            verbose=1,
        ),
        tf.keras.callbacks.CSVLogger(
            filename="training_log.csv",
            append=True,
        ),
    ]

    try:
        history = model.fit(
            train_ds,
            validation_data=val_ds,
            epochs=epochs,
            steps_per_epoch=steps_per_epoch,
            validation_steps=validation_steps,
            callbacks=callbacks,
            verbose=1,
        )
    except KeyboardInterrupt:
        interrupted_path = os.path.join(CHECKPOINTS_DIR, "interrupted_model.keras")
        print(f"\n[LUCIA] Entrenamiento interrumpido manualmente (Ctrl+C). Guardando estado en '{interrupted_path}'...")
        model.save(interrupted_path)
        print(f"[LUCIA] Modelo guardado limpiamente en '{interrupted_path}'. Saliendo sin errores.")
        return {
            "model_path": interrupted_path,
            "geojson_path": None,
            "final_metrics": {},
            "interrupted": True,
        }

    model.save(save_model_path)
    final_metrics = {k: float(v[-1]) for k, v in history.history.items()}
    save_lucia_metadata(
        model,
        save_model_path,
        extra={
            "mode": "train",
            "real_cata_samples_augmented": int(len(x_real)),
            "synthetic_samples": int(len(x_syn)),
            "final_metrics": final_metrics,
        },
    )

    geojson_payload = generate_lucia_geojson_from_cata(
        cata_predictions_path=cata_predictions_path,
        output_geojson_path=output_geojson_path,
        model_path=save_model_path,
        safe_fire_threshold=safe_fire_threshold,
    )
    return {
        "model_path": save_model_path,
        "geojson_path": output_geojson_path,
        "final_metrics": final_metrics,
        "geojson_metadata": geojson_payload["metadata"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="LUCIA — Modelo TensorFlow modular y enrutador GeoJSON de evacuación segura"
    )
    p.add_argument(
        "--mode",
        choices=("train", "expand", "route"),
        default="train",
        help="train: entrena TF + genera GeoJSON | expand: channel surgery | route: sólo genera GeoJSON",
    )
    p.add_argument("--cata-input", default=config.DEFAULT_CATA_PREDICTIONS_PATH)
    p.add_argument("--save-path", default=config.DEFAULT_MODEL_PATH)
    p.add_argument("--base-model", default=None)
    p.add_argument("--geojson-output", default=config.DEFAULT_GEOJSON_OUTPUT_PATH)
    p.add_argument("--num-channels", type=int, default=config.DEFAULT_NUM_CHANNELS)
    p.add_argument("--safe-fire-threshold", type=float, default=config.SAFE_FIRE_THRESHOLD)
    p.add_argument("--epochs", type=int, default=config.EPOCHS)
    p.add_argument("--batch-size", type=int, default=config.BATCH_SIZE)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    args = parse_args(argv)

    if args.mode == "train":
        res = run_lucia_training_pipeline(
            cata_predictions_path=args.cata_input,
            save_model_path=args.save_path,
            output_geojson_path=args.geojson_output,
            num_channels=args.num_channels,
            safe_fire_threshold=args.safe_fire_threshold,
            epochs=args.epochs,
            batch_size=args.batch_size,
        )
        logger.info("Entrenamiento y enrutamiento LUCIA completados: %s", res["geojson_metadata"])
    elif args.mode == "expand":
        if not args.base_model:
            raise SystemExit("--mode expand requiere --base-model")
        model = expand_lucia_channels(
            old_model_path=args.base_model,
            new_num_channels=args.num_channels,
            save_path=args.save_path,
        )
        save_lucia_metadata(model, args.save_path, extra={"mode": "expand", "expanded_from": args.base_model})
        logger.info("Modelo LUCIA expandido guardado en %s", args.save_path)
    elif args.mode == "route":
        payload = generate_lucia_geojson_from_cata(
            cata_predictions_path=args.cata_input,
            output_geojson_path=args.geojson_output,
            model_path=args.save_path,
            safe_fire_threshold=args.safe_fire_threshold,
        )
        logger.info("GeoJSON de LUCIA generado: %s", payload["metadata"])


if __name__ == "__main__":
    main()
