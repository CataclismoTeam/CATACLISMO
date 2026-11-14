#!/usr/bin/env python3
"""
Entrenamiento OFFLINE completo del algoritmo CATA (ConvLSTM).

Pipeline end-to-end:
1. Carga `validated_cell_day.parquet` (solo decision == "ACEPTA")
2. Construye tensores (B, T=5, H=320, W=320, C=13) sin fuga espacial
3. Entrena con callbacks, early stopping, LR scheduling
4. Exporta a TFLite (dynamic + float16 + int8 opcional)
5. Genera metadata completa con trazabilidad

Uso:
    python train_offline.py \
        --data backend/app/ingestion/output/validated_cell_day.parquet \
        --output artifacts/models/cata_c13.keras \
        --epochs 50 --channels 13 --grid 320
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import keras
import numpy as np
import pandas as pd
import tensorflow as tf

try:
    from . import config
    from .config import ModelConfig
    from .model import (
        compile_model,
        create_model,
        expand_model_channels,
        extract_model_config,
        load_fire_model,
        set_expansion_warmup,
    )
    from .export_tflite import export_to_tflite
except ImportError:
    import config
    from config import ModelConfig
    from model import (
        compile_model,
        create_model,
        expand_model_channels,
        extract_model_config,
        load_fire_model,
        set_expansion_warmup,
    )
    from export_tflite import export_to_tflite

logger = logging.getLogger("cata_train_offline")

# ---------------------------------------------------------------------------
# Configuración por defecto (alineada con config.py actualizado 1km)
# ---------------------------------------------------------------------------

DEFAULT_GRID_SIZE = config.GRID_SIZE      # 320
DEFAULT_TIME_STEPS = config.TIME_STEPS    # 5
DEFAULT_CHANNELS = len(config.CHANNEL_REGISTRY)  # 13
DEFAULT_BATCH_SIZE = config.BATCH_SIZE    # 8
DEFAULT_EPOCHS = config.EPOCHS            # 10 (aumentar para producción)
DEFAULT_LR = config.LEARNING_RATE         # 1e-3

# Regex para cell_id ES1K (1km)
_CELL_ID_RE = re.compile(r"^ES1K:L(\d+):Y(-?\d+):X(-?\d+)$")

# 8-vecindad para difusión
_NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


# ---------------------------------------------------------------------------
# Utilidades de parsing cell_id
# ---------------------------------------------------------------------------

def parse_cell_id(cell_id: str) -> tuple[int, int, int]:
    """Parsea `ES1K:L{level}:Y{iy}:X{ix}` -> (level, iy, ix)."""
    m = _CELL_ID_RE.match(str(cell_id).strip())
    if not m:
        raise ValueError(f"cell_id inválido según contrato ES1K: {cell_id!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_cell_id(iy: int, ix: int, level: int = config.GRID_LEVEL) -> str:
    """Formatea coordenadas de grilla a `ES1K:L{level}:Y{iy}:X{ix}`."""
    return f"ES1K:L{level}:Y{iy}:X{ix}"


# ---------------------------------------------------------------------------
# Normalización de canales (13 canales del contrato)
# ---------------------------------------------------------------------------

def normalize_contract_channels(raw: dict[str, np.ndarray], num_channels: int) -> np.ndarray:
    """Convierte métricas crudas de `cell_day` a canales normalizados en [0, 1]."""
    frp_scale = config.FRP_LOG1P_SCALE
    obs_scale = config.OBS_LOG1P_SCALE

    n_obs_raw = np.maximum(raw["n_obs"], 0.0)
    n_obs_denom = np.maximum(n_obs_raw, 1.0)
    active = (n_obs_raw > 0).astype(np.float32)

    computed: dict[str, np.ndarray] = {
        "frp_sum_mw": np.clip(np.log1p(np.maximum(raw["frp_sum_mw"], 0.0)) / frp_scale, 0.0, 1.0),
        "frp_max_mw": np.clip(np.log1p(np.maximum(raw["frp_max_mw"], 0.0)) / frp_scale, 0.0, 1.0),
        "frp_mean_mw": np.clip(np.log1p(np.maximum(raw["frp_mean_mw"], 0.0)) / frp_scale, 0.0, 1.0),
        "frp_p50_mw": np.clip(np.log1p(np.maximum(raw["frp_p50_mw"], 0.0)) / frp_scale, 0.0, 1.0),
        "n_obs": np.clip(np.log1p(n_obs_raw) / config.OBS_LOG1P_SCALE, 0.0, 1.0),
        "n_high_conf": np.clip(np.log1p(np.maximum(raw["n_high_conf"], 0.0)) / config.OBS_LOG1P_SCALE, 0.0, 1.0),
        "confidence_rank_max": np.clip(raw["confidence_rank_max"] / 2.0, 0.0, 1.0) * active,
        "n_day_ratio": np.clip(raw["n_day"] / n_obs_denom, 0.0, 1.0) * active,
        "n_night_ratio": np.clip(raw["n_night"] / n_obs_denom, 0.0, 1.0) * active,
        "footprint_max_km": np.clip(raw["footprint_max_km"] / 1.0, 0.0, 1.0) * active,  # 1km grid
        "n_platforms": np.clip(raw["n_platforms"] / 3.0, 0.0, 1.0) * active,
        "product_mix": np.clip(raw["product_mix"], 0.0, 1.0) * active,
        "viirs_obs_share": (
            np.clip(raw.get("n_obs_viirs", n_obs_raw * 0.65) / n_obs_denom, 0.0, 1.0) * active
        ),
    }

    names = config.CHANNEL_REGISTRY[:num_channels]
    return np.stack([computed[k].astype(np.float32) for k in names], axis=-1)


# ---------------------------------------------------------------------------
# Carga y preparación de datos OFFLINE
# ---------------------------------------------------------------------------

def load_validated_cell_day(
    path: str | Path,
    grid_size: int = DEFAULT_GRID_SIZE,
    time_steps: int = DEFAULT_TIME_STEPS,
    num_channels: int = DEFAULT_CHANNELS,
    invalid_periods: Sequence[str] = ("2026-09",),
    val_split: float = config.VALIDATION_SPLIT,
    seed: int = config.SEED,
    only_accepted: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Carga `validated_cell_day.parquet`, filtra por decision == "ACEPTA",
    construye tensores (B, T, H, W, C) y divide train/val SIN fuga espacial.

    Returns: (X_train, Y_train, X_val, Y_val)
    """
    logger.info(f"Cargando datos validados desde: {path}")

    df = pd.read_parquet(path)
    logger.info(f"Registros totales: {len(df)}")

    # Filtrar solo ACEPTA
    if only_accepted and "decision" in df.columns:
        before = len(df)
        df = df[df["decision"] == "ACEPTA"].copy()
        logger.info(f"Filtrado ACEPTA: {before} -> {len(df)} ({len(df)/before*100:.1f}%)")

    if len(df) == 0:
        raise ValueError("No hay registros con decision == 'ACEPTA'")

    # Filtrar periodo inválido
    if "year_month" in df.columns and invalid_periods:
        df = df[~df["year_month"].isin(invalid_periods)]

    # Excluir flags problemáticos
    if "flags" in df.columns:
        def _keep_flags(fl):
            if fl is None or (isinstance(fl, float) and np.isnan(fl)):
                return True
            s = set(fl) if isinstance(fl, (list, tuple, np.ndarray)) else set()
            return "partial_period" not in s and "island_domain" not in s
        df = df[df["flags"].map(_keep_flags)]

    # Parse cell_id -> iy, ix
    parsed = df["cell_id"].map(parse_cell_id)
    df = df.copy()
    df["level"] = [p[0] for p in parsed]
    df["iy"] = [p[1] for p in parsed]
    df["ix"] = [p[2] for p in parsed]

    # Solo nivel L0 (1km)
    df = df[df["level"] == config.GRID_LEVEL]

    # Agregar MODIS + VIIRS por (cell_id, date) -> ya vienen separados en validated_cell_day
    # Si vienen juntos, descomentar y usar groupby. Por ahora asumimos ya agregados.

    # Calcular n_obs_viirs para viirs_obs_share
    df["n_obs_viirs"] = np.where(df["sensor"] == "VIIRS", df["n_obs"], 0)

    # Agregar por (iy, ix, date) sumando sensores (como en contrato original)
    df["w_frp_mean"] = df["frp_mean_mw"] * df["n_obs"]
    df["w_frp_p50"] = df["frp_p50_mw"] * df["n_obs"]
    df["w_pmix"] = df["product_mix"] * df["n_obs"]

    grouped = df.groupby(["iy", "ix", "date"], as_index=False).agg(
        frp_sum_mw=("frp_sum_mw", "sum"),
        frp_max_mw=("frp_max_mw", "max"),
        w_frp_mean=("w_frp_mean", "sum"),
        w_frp_p50=("w_frp_p50", "sum"),
        n_obs=("n_obs", "sum"),
        n_high_conf=("n_high_conf", "sum"),
        confidence_rank_max=("confidence_rank_max", "max"),
        n_day=("n_day", "sum"),
        n_night=("n_night", "sum"),
        footprint_max_km=("footprint_max_km", "max"),
        n_platforms=("n_platforms", "sum"),
        w_pmix=("w_pmix", "sum"),
        n_obs_viirs=("n_obs_viirs", "sum"),
    )
    denom = np.maximum(grouped["n_obs"].to_numpy(np.float32), 1.0)
    grouped["frp_mean_mw"] = grouped["w_frp_mean"] / denom
    grouped["frp_p50_mw"] = grouped["w_frp_p50"] / denom
    grouped["product_mix"] = grouped["w_pmix"] / denom

    # Serie temporal continua
    dates = pd.date_range(grouped["date"].min(), grouped["date"].max(), freq="D").strftime("%Y-%m-%d")
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n_days = len(dates)
    if n_days <= time_steps:
        raise ValueError(f"Serie temporal insuficiente ({n_days} días) para time_steps={time_steps}")

    # Partición ESPACIAL por bloques (sin fuga) — §6 del contrato
    unique_cells = grouped[["iy", "ix"]].drop_duplicates().to_numpy()
    rng = np.random.default_rng(seed)
    half = grid_size // 2
    block_ids = [f"{iy // half}_{ix // half}" for iy, ix in unique_cells]
    unique_blocks = sorted(set(block_ids))
    rng.shuffle(unique_blocks)
    n_val_blocks = max(1, int(len(unique_blocks) * config.VALIDATION_SPLIT))
    val_blocks = set(unique_blocks[:n_val_blocks])
    logger.info(f"Bloques totales: {len(unique_blocks)}, val: {n_val_blocks}, train: {len(unique_blocks)-n_val_blocks}")

    raw_keys = [
        "frp_sum_mw", "frp_max_mw", "frp_mean_mw", "frp_p50_mw",
        "n_obs", "n_high_conf", "confidence_rank_max",
        "n_day", "n_night", "footprint_max_km",
        "n_platforms", "product_mix", "n_obs_viirs",
    ]

    x_tr, y_tr, x_va, y_va = [], [], [], []

    for b_id in unique_blocks:
        by, bx = (int(v) for v in b_id.split("_"))
        cy, cx = by * half + half // 2, bx * half + half // 2
        y0, x0 = cy - half, cx - half

        sub = grouped[
            (grouped["iy"] >= y0) & (grouped["iy"] < y0 + grid_size) &
            (grouped["ix"] >= x0) & (grouped["ix"] < x0 + grid_size)
        ]
        if sub.empty:
            continue

        # Cubo crudo (T, H, W) por canal
        raw_cube = {k: np.zeros((n_days, grid_size, grid_size), np.float32) for k in raw_keys}
        ti = sub["date"].map(date_to_idx).to_numpy()
        yi = (sub["iy"] - y0).to_numpy()
        xi = (sub["ix"] - x0).to_numpy()
        for k in raw_keys:
            raw_cube[k][ti, yi, xi] = sub[k].to_numpy(np.float32)

        # Normalizar a 13 canales
        features = normalize_contract_channels(raw_cube, len(config.CHANNEL_REGISTRY))

        # Target: actividad térmica en t+1 (n_obs > 0)
        burning = (raw_cube["n_obs"] > 0).astype(np.float32)

        is_val = b_id in val_blocks
        for s in range(n_days - time_steps):
            win_x = features[s : s + time_steps]      # (T, H, W, C)
            win_y = burning[s + time_steps][..., None] # (H, W, 1)

            # Saltar ventanas vacías (optimización)
            if win_x[..., 0].sum() == 0 and win_y.sum() == 0:
                continue

            if is_val:
                x_va.append(win_x)
                y_va.append(win_y)
            else:
                x_tr.append(win_x)
                y_tr.append(win_y)

    X_train = np.asarray(x_tr, np.float32)
    Y_train = np.asarray(y_tr, np.float32)
    X_val = np.asarray(x_va, np.float32)
    Y_val = np.asarray(y_va, np.float32)

    logger.info(f"Train: X={X_train.shape} Y={Y_train.shape} | Val: X={X_val.shape} Y={Y_val.shape}")
    logger.info(f"Train fire rate: {Y_train.mean():.4f} | Val fire rate: {Y_val.mean():.4f}")

    return X_train, Y_train, X_val, Y_val


# ---------------------------------------------------------------------------
# Dataset tf.data optimizado
# ---------------------------------------------------------------------------

def make_tf_dataset(
    X: np.ndarray,
    Y: np.ndarray,
    batch_size: int,
    shuffle: bool,
    seed: int,
    cache: bool = True,
) -> tf.data.Dataset:
    ds = tf.data.Dataset.from_tensor_slices((X, Y))
    if shuffle:
        ds = ds.shuffle(len(X), seed=seed, reshuffle_each_iteration=True)
    if cache:
        ds = ds.cache()
    ds = ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)
    return ds


# ---------------------------------------------------------------------------
# Callbacks de entrenamiento
# ---------------------------------------------------------------------------

def build_callbacks(model_path: str, log_dir: str, tag: str, patience: int):
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(model_path)), exist_ok=True)

    return [
        keras.callbacks.ModelCheckpoint(
            model_path, monitor="val_loss", save_best_only=True, verbose=1
        ),
        keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=patience, restore_best_weights=True, verbose=1
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=config.REDUCE_LR_PATIENCE,
            min_lr=1e-6, verbose=1
        ),
        keras.callbacks.CSVLogger(os.path.join(log_dir, f"{tag}.csv"), append=True),
        keras.callbacks.TerminateOnNaN(),
        keras.callbacks.TensorBoard(
            log_dir=os.path.join(log_dir, "tb", tag),
            histogram_freq=1, write_graph=True, update_freq="epoch"
        ),
    ]


# ---------------------------------------------------------------------------
# Entrenamiento
# ---------------------------------------------------------------------------

def train_model(
    model: keras.Model,
    train_ds: tf.data.Dataset,
    val_ds: tf.data.Dataset,
    epochs: int,
    model_path: str,
    tag: str,
    patience: int,
    log_dir: str,
) -> dict:
    callbacks = build_callbacks(model_path, log_dir, tag, patience)
    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=epochs,
        callbacks=callbacks,
        verbose=2,
    )
    # Guardar mejor modelo (ya lo hace ModelCheckpoint, pero aseguramos)
    model.save(model_path)
    return {k: [float(v) for v in vals] for k, vals in history.history.items()}


# ---------------------------------------------------------------------------
# Exportación TFLite post-entrenamiento
# ---------------------------------------------------------------------------

def export_all_tflite(
    model_path: str,
    output_dir: str,
    quant_modes: list[str] = None,
) -> dict[str, str]:
    """Exporta a TFLite en múltiples modos de cuantización."""
    if quant_modes is None:
        quant_modes = ["dynamic", "float16"]  # int8 opcional, más lento

    os.makedirs(output_dir, exist_ok=True)
    results = {}

    for mode in quant_modes:
        out_path = os.path.join(output_dir, f"cata_{mode}.tflite")
        logger.info(f"Exportando TFLite ({mode}) -> {out_path}")
        try:
            result = export_to_tflite(
                model_path,
                output_path=out_path,
                quantization=mode,
                batch_size=1,
            )
            results[mode] = result
            logger.info(f"  OK: {result}")
        except Exception as e:
            logger.error(f"  ERROR exportando {mode}: {e}")
            results[mode] = f"ERROR: {e}"

    return results


# ---------------------------------------------------------------------------
# Metadata completa
# ---------------------------------------------------------------------------

def save_full_metadata(
    model_path: str,
    model: keras.Model,
    history: dict,
    train_config: dict,
    data_stats: dict,
    parent: str | None = None,
):
    """Guarda metadata completa alineada con 11_ML_DATA_CONTRACT.md"""
    cfg = extract_model_config(model)
    meta = {
        "algorithm": config.ALGORITHM_NAME,
        "schema_reference": "11_ML_DATA_CONTRACT.md",
        "grid_id": config.GRID_ID,
        "crs": config.CRS,
        "grid_level": config.GRID_LEVEL,
        "cell_size_m": config.CHUNK_SIZE_M,
        "model_path": os.path.abspath(model_path),
        "mode": "offline_training",
        "parent_checkpoint": parent,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "input_shape": [None, *cfg.input_shape],
        "output_shape": [None, cfg.height, cfg.width, 1],
        "channels": list(cfg.channel_names),
        "architecture": asdict(cfg),
        "train_config": train_config,
        "data_stats": data_stats,
        "final_metrics": {k: v[-1] for k, v in history.items()} if history else {},
    }
    meta_path = os.path.splitext(model_path)[0] + ".meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info(f"Metadata guardada: {meta_path}")


# ---------------------------------------------------------------------------
# CLI principal
# ---------------------------------------------------------------------------

def build_arg_parser():
    p = argparse.ArgumentParser(description="Entrenamiento OFFLINE CATA (ConvLSTM) + TFLite export")
    p.add_argument("--data", type=Path, required=True,
                   help="Ruta a validated_cell_day.parquet")
    p.add_argument("--output", type=Path, required=True,
                   help="Ruta salida modelo .keras")
    p.add_argument("--epochs", type=int, default=50, help="Épocas (producción: 50-100)")
    p.add_argument("--channels", type=int, default=DEFAULT_CHANNELS,
                   help="Número de canales (1-13)")
    p.add_argument("--grid", type=int, default=DEFAULT_GRID_SIZE,
                   help="Tamaño grid H=W (320 para 1km)")
    p.add_argument("--time-steps", type=int, default=DEFAULT_TIME_STEPS)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--lr", type=float, default=DEFAULT_LR)
    p.add_argument("--patience", type=int, default=config.EARLY_STOPPING_PATIENCE)
    p.add_argument("--seed", type=int, default=config.SEED)
    p.add_argument("--val-split", type=float, default=config.VALIDATION_SPLIT)
    p.add_argument("--export-tflite", action="store_true",
                   help="Exportar a TFLite tras entrenar")
    p.add_argument("--tflite-modes", nargs="+", default=["dynamic", "float16"],
                   choices=["none", "dynamic", "float16", "int8"],
                   help="Modos de cuantización TFLite")
    p.add_argument("--only-accepted", action="store_true", default=True,
                   help="Solo usar decision == ACEPTA")
    p.add_argument("--log-dir", type=Path, default=Path(config.LOG_DIR))
    return p


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    args = build_arg_parser().parse_args(argv)
    keras.utils.set_random_seed(args.seed)

    # 1. Cargar datos
    logger.info("=== Cargando datos validados ===")
    X_tr, Y_tr, X_va, Y_va = load_validated_cell_day(
        args.data,
        grid_size=args.grid,
        time_steps=args.time_steps,
        num_channels=args.channels,
        val_split=args.val_split,
        seed=args.seed,
        only_accepted=args.only_accepted,
    )

    # 2. Crear datasets tf.data
    train_ds = make_tf_dataset(X_tr, Y_tr, args.batch_size, True, args.seed)
    val_ds = make_tf_dataset(X_va, Y_va, args.batch_size, False, args.seed)

    # 3. Construir modelo
    cfg = ModelConfig(
        num_channels=args.channels,
        time_steps=args.time_steps,
        height=args.grid,
        width=args.grid,
    )
    model = create_model(cfg, args.lr)
    model.summary(print_fn=logger.info)

    # 4. Entrenar
    tag = f"cata_c{args.channels}_g{args.grid}_t{args.time_steps}"
    model_path = str(args.output)
    log_dir = str(args.log_dir)

    logger.info(f"=== Entrenando {tag} ===")
    history = train_model(
        model, train_ds, val_ds, args.epochs,
        model_path, tag, args.patience, str(args.log_dir)
    )

    # 5. Metadata
    train_config = {
        "epochs": args.epochs, "batch_size": args.batch_size,
        "lr": args.lr, "patience": args.patience,
        "seed": args.seed, "val_split": args.val_split,
    }
    data_stats = {
        "train_samples": len(X_tr), "val_samples": len(X_va),
        "train_fire_rate": float(Y_tr.mean()), "val_fire_rate": float(Y_va.mean()),
        "grid_size": args.grid, "time_steps": args.time_steps,
        "channels": args.channels,
    }
    save_full_metadata(str(args.output), model, history, train_config, data_stats)

    # 6. Export TFLite
    if args.export_tflite:
        logger.info("=== Exportando TFLite ===")
        tflite_dir = Path(args.output).parent / "tflite"
        results = export_all_tflite(str(args.output), str(tflite_dir), args.tflite_modes)
        logger.info(f"TFLite exportado a: {tflite_dir}")
        for mode, path in results.items():
            logger.info(f"  {mode}: {path}")

    logger.info("=== ENTRENAMIENTO COMPLETO ===")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())