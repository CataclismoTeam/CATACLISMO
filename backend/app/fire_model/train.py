"""
train.py — Pipeline de entrenamiento incremental del predictor de fuego
alineado estrictamente con el esquema de datos `11_ML_DATA_CONTRACT.md`.

Sin variables exógenas (sin viento, pendiente ni NDVI): predice únicamente
a partir de los campos existentes en el contrato (`cell_day` / `observations`
de MODIS y VIIRS en la grilla `ES5K:L0:Y{iy}:X{ix}`).

Modos:
  scratch   Entrena un modelo nuevo con C canales del contrato.
  finetune  Carga un checkpoint (.keras/.h5) y continúa entrenando sus pesos.
  expand    Channel surgery sobre un checkpoint (C_old -> C_new) + entrenamiento
            en dos fases (warmup de la 1ª capa, luego ajuste fino completo).
  demo      Smoke test end-to-end: scratch(C=1) -> finetune -> expand(C=7).

Fuentes de datos (`--data`):
  1. Archivo `cell_day.parquet` o `cell_day.jsonl` con el esquema oficial
     de `11_ML_DATA_CONTRACT.md` (respeta exclusión de `invalid_periods`,
     agregación multi-sensor por celda-día y partición espacial train/val por
     `cell_id` según §6 del contrato).
  2. Archivo `.npz` pre-empaquetado con `X: (N, T, H, W, C)` e `Y: (N, H, W, 1)`.
  3. Si no se pasa `--data`, usa `SyntheticContractGenerator`, que simula
     registros `cell_day` siguiendo el esquema exacto del contrato.
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

import keras
import numpy as np
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

logger = logging.getLogger("fire_train")

# 8-vecindad para difusión isotrópica en la rejilla ES5K
_NEIGHBORS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
_CELL_ID_RE = re.compile(r"^ES5K:L(\d+):Y(-?\d+):X(-?\d+)$")


def _shift(a: np.ndarray, dy: int, dx: int) -> np.ndarray:
    """out[i, j] = a[i - dy, j - dx] con relleno a cero (sin wrap-around)."""
    h, w = a.shape
    out = np.zeros_like(a)
    out[max(dy, 0) : h + min(dy, 0), max(dx, 0) : w + min(dx, 0)] = a[
        max(-dy, 0) : h + min(-dy, 0), max(-dx, 0) : w + min(-dx, 0)
    ]
    return out


# ===========================================================================
# 1. Utilidades del contrato de datos (`11_ML_DATA_CONTRACT.md`)
# ===========================================================================
def parse_cell_id(cell_id: str) -> tuple[int, int, int]:
    """Parsea `ES5K:L{level}:Y{iy}:X{ix}` -> (level, iy, ix)."""
    m = _CELL_ID_RE.match(str(cell_id).strip())
    if not m:
        raise ValueError(f"cell_id inválido según contrato ES5K: {cell_id!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def format_cell_id(iy: int, ix: int, level: int = config.GRID_LEVEL) -> str:
    """Formatea coordenadas de grilla a `ES5K:L{level}:Y{iy}:X{ix}`."""
    return f"ES5K:L{level}:Y{iy}:X{ix}"


def normalize_contract_channels(raw: dict[str, np.ndarray], num_channels: int) -> np.ndarray:
    """Convierte las métricas crudas de `cell_day` a canales normalizados en [0, 1].

    `raw` contiene arrays de igual shape `(..., H, W)` con las magnitudes
    definidas en `11_ML_DATA_CONTRACT.md` §2:
      - frp_sum_mw, frp_max_mw, frp_mean_mw, frp_p50_mw (en MW)
      - n_obs, n_high_conf, n_day, n_night, n_platforms (conteos)
      - confidence_rank_max (0, 1, 2)
      - footprint_max_km (km)
      - product_mix (0.0 a 1.0)
      - n_obs_viirs (opcional, para viirs_obs_share)

    Devuelve tensor `(..., H, W, num_channels)` alineado con `config.CHANNEL_REGISTRY`.
    """
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
        "n_obs": np.clip(np.log1p(n_obs_raw) / obs_scale, 0.0, 1.0),
        "n_high_conf": np.clip(np.log1p(np.maximum(raw["n_high_conf"], 0.0)) / obs_scale, 0.0, 1.0),
        "confidence_rank_max": np.clip(raw["confidence_rank_max"] / 2.0, 0.0, 1.0) * active,
        "n_day_ratio": np.clip(raw["n_day"] / n_obs_denom, 0.0, 1.0) * active,
        "n_night_ratio": np.clip(raw["n_night"] / n_obs_denom, 0.0, 1.0) * active,
        "footprint_max_km": np.clip(raw["footprint_max_km"] / 5.0, 0.0, 1.0) * active,
        "n_platforms": np.clip(raw["n_platforms"] / 3.0, 0.0, 1.0) * active,
        "product_mix": np.clip(raw["product_mix"], 0.0, 1.0) * active,
        "viirs_obs_share": (
            np.clip(raw.get("n_obs_viirs", n_obs_raw * 0.65) / n_obs_denom, 0.0, 1.0) * active
        ),
    }

    names = config.CHANNEL_REGISTRY[:num_channels]
    return np.stack([computed[k].astype(np.float32) for k in names], axis=-1)


# ===========================================================================
# 2. Lector de artefactos reales (`cell_day.parquet` / `cell_day.jsonl`)
# ===========================================================================
def load_contract_cell_day(
    path: str,
    grid_size: int = config.GRID_SIZE,
    time_steps: int = config.TIME_STEPS,
    num_channels: int = config.NUM_CHANNELS,
    invalid_periods: Sequence[str] = ("2026-09",),
    val_split: float = config.VALIDATION_SPLIT,
    seed: int = config.SEED,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Carga `cell_day.parquet` o `cell_day.jsonl` según `11_ML_DATA_CONTRACT.md`.

    - Excluye meses en `invalid_periods` (por defecto `2026-09` según `manifest.json`)
      y filas con flag `partial_period` o `island_domain`.
    - Agrega MODIS y VIIRS por `(cell_id, date)`.
    - Construye parches espaciales `grid_size x grid_size` centrados en clusters
      activos y divide train/val **por `cell_id` de región** (cumpliendo §6:
      nunca mezclar la misma celda entre train y test).

    Devuelve `(X_train, Y_train, X_val, Y_val)`.
    """
    import pandas as pd

    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    elif path.endswith(".jsonl") or path.endswith(".json"):
        df = pd.read_json(path, lines=path.endswith(".jsonl"))
    else:
        raise ValueError(f"Formato no soportado: {path} (use .parquet, .jsonl o .npz)")

    if "level" in df.columns:
        df = df[df["level"] == config.GRID_LEVEL]
    if "year_month" in df.columns and invalid_periods:
        df = df[~df["year_month"].isin(invalid_periods)]
    if "flags" in df.columns:

        def _keep_flags(fl):
            if fl is None or (isinstance(fl, float) and np.isnan(fl)):
                return True
            s = set(fl) if isinstance(fl, list | tuple | np.ndarray) else set()
            return "partial_period" not in s and "island_domain" not in s

        df = df[df["flags"].map(_keep_flags)]

    parsed = df["cell_id"].map(parse_cell_id)
    df = df.copy()
    df["iy"] = [p[1] for p in parsed]
    df["ix"] = [p[2] for p in parsed]
    df["n_obs_viirs"] = np.where(df["sensor"] == "VIIRS", df["n_obs"], 0)
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

    dates = pd.date_range(grouped["date"].min(), grouped["date"].max(), freq="D").strftime(
        "%Y-%m-%d"
    )
    date_to_idx = {d: i for i, d in enumerate(dates)}
    n_days = len(dates)
    if n_days <= time_steps:
        raise ValueError(
            f"Serie temporal insuficiente ({n_days} días) para time_steps={time_steps}"
        )

    # Partición espacial por bloques de celdas (evita fuga entre train y val, §6)
    unique_cells = grouped[["iy", "ix"]].drop_duplicates().to_numpy()
    rng = np.random.default_rng(seed)
    block_ids = [f"{iy // (grid_size // 2)}_{ix // (grid_size // 2)}" for iy, ix in unique_cells]
    unique_blocks = sorted(set(block_ids))
    rng.shuffle(unique_blocks)
    n_val_blocks = max(1, int(len(unique_blocks) * val_split))
    val_blocks = set(unique_blocks[:n_val_blocks])

    raw_keys = [
        "frp_sum_mw",
        "frp_max_mw",
        "frp_mean_mw",
        "frp_p50_mw",
        "n_obs",
        "n_high_conf",
        "confidence_rank_max",
        "n_day",
        "n_night",
        "footprint_max_km",
        "n_platforms",
        "product_mix",
        "n_obs_viirs",
    ]

    x_tr, y_tr, x_va, y_va = [], [], [], []
    half = grid_size // 2

    for b_id in unique_blocks:
        by, bx = (int(v) for v in b_id.split("_"))
        cy, cx = by * half + half // 2, bx * half + half // 2
        y0, x0 = cy - half, cx - half
        sub = grouped[
            (grouped["iy"] >= y0)
            & (grouped["iy"] < y0 + grid_size)
            & (grouped["ix"] >= x0)
            & (grouped["ix"] < x0 + grid_size)
        ]
        if sub.empty:
            continue

        raw_cube = {k: np.zeros((n_days, grid_size, grid_size), np.float32) for k in raw_keys}
        ti = sub["date"].map(date_to_idx).to_numpy()
        yi = (sub["iy"] - y0).to_numpy()
        xi = (sub["ix"] - x0).to_numpy()
        for k in raw_keys:
            raw_cube[k][ti, yi, xi] = sub[k].to_numpy(np.float32)

        features = normalize_contract_channels(raw_cube, num_channels)
        # Target definido por quien entrena (§6): actividad térmica en t+1 (n_obs > 0)
        burning = (raw_cube["n_obs"] > 0).astype(np.float32)

        is_val = b_id in val_blocks
        for s in range(n_days - time_steps):
            win_x = features[s : s + time_steps]
            win_y = burning[s + time_steps][..., None]
            if win_x[..., 0].sum() == 0 and win_y.sum() == 0:
                continue
            if is_val:
                x_va.append(win_x)
                y_va.append(win_y)
            else:
                x_tr.append(win_x)
                y_tr.append(win_y)

    return (
        np.asarray(x_tr, np.float32),
        np.asarray(y_tr, np.float32),
        np.asarray(x_va, np.float32),
        np.asarray(y_va, np.float32),
    )


# ===========================================================================
# 3. Generador sintético fiel a `11_ML_DATA_CONTRACT.md` (sin viento ni slope)
# ===========================================================================
class SyntheticContractGenerator:
    """Simula la evolución de puntos calientes MODIS/VIIRS según `11_ML_DATA_CONTRACT.md`.

    No utiliza ninguna variable externa (ni viento, ni pendiente, ni NDVI).
    Toda la dinámica emerge exclusivamente de las propiedades observadas en
    `cell_day` sobre la grilla `ES5K:L0:Y{iy}:X{ix}`.
    """

    def __init__(
        self,
        grid_size: int = config.GRID_SIZE,
        time_steps: int = config.TIME_STEPS,
        num_channels: int = config.NUM_CHANNELS,
        seed: int = config.SEED,
        base_spread: float = 0.24,
        observation_dropout: float = 0.06,
    ):
        if not 1 <= num_channels <= len(config.CHANNEL_REGISTRY):
            raise ValueError(f"num_channels fuera de rango: {num_channels}")
        self.n = grid_size
        self.t = time_steps
        self.c = num_channels
        self.rng = np.random.default_rng(seed)
        self.base_spread = base_spread
        self.observation_dropout = observation_dropout
        yy, xx = np.mgrid[0:grid_size, 0:grid_size] / grid_size
        self._yy, self._xx = yy.astype(np.float32), xx.astype(np.float32)

    def _susceptibility_field(self) -> np.ndarray:
        """Susceptibilidad espacial intrínseca de las celdas L0 (sin exógenos)."""
        f = np.zeros((self.n, self.n), np.float32)
        for _ in range(5):
            fx, fy = self.rng.uniform(-2.5, 2.5, 2)
            phase = self.rng.uniform(0, 2 * np.pi)
            f += self.rng.uniform(0.4, 1.0) * np.cos(
                2 * np.pi * (fx * self._xx + fy * self._yy) + phase
            )
        f -= f.min()
        f = f / (f.max() + 1e-8)
        return np.clip(f * 1.15 - 0.05, 0.0, 1.0).astype(np.float32)

    def simulate_episode(self, n_steps: int) -> tuple[dict[str, np.ndarray], np.ndarray]:
        """Simula `n_steps` días de la grilla `cell_day`.

        Devuelve `(raw_channels_dict, true_burning_mask)`.
        """
        n = self.n
        suscept = self._susceptibility_field()
        duration = (2 + np.round(4 * suscept)).astype(np.int32)

        age = np.full((n, n), -1, np.int32)  # -1: inactivo; >=0: días ardiendo
        candidates = np.argwhere(suscept > 0.45)
        if len(candidates) == 0:
            candidates = np.argwhere(suscept >= 0)
        n_ign = min(len(candidates), int(self.rng.integers(1, 4)))
        for idx in self.rng.choice(len(candidates), size=n_ign, replace=False):
            age[tuple(candidates[idx])] = 0

        raw_keys = [
            "frp_sum_mw",
            "frp_max_mw",
            "frp_mean_mw",
            "frp_p50_mw",
            "n_obs",
            "n_high_conf",
            "confidence_rank_max",
            "n_day",
            "n_night",
            "footprint_max_km",
            "n_platforms",
            "product_mix",
            "n_obs_viirs",
        ]
        raw = {k: np.zeros((n_steps, n, n), np.float32) for k in raw_keys}
        burning_hist = np.zeros((n_steps, n, n), np.float32)

        for step in range(n_steps):
            burning = (age >= 0) & (age < duration)
            burning_hist[step] = burning.astype(np.float32)

            vigor = np.where(
                burning,
                (0.35 + 0.65 * suscept) * (1.0 - (age / np.maximum(duration, 1)) * 0.45),
                0.0,
            ).astype(np.float32)

            observed = burning & (self.rng.random((n, n)) > self.observation_dropout)

            n_obs = np.where(
                observed,
                np.maximum(1, np.round(np.expm1(vigor * 3.8 + self.rng.normal(0, 0.25, (n, n))))),
                0.0,
            ).astype(np.float32)

            viirs_share = np.clip(self.rng.normal(0.68, 0.15, (n, n)), 0.0, 1.0).astype(np.float32)
            n_obs_viirs = np.round(n_obs * viirs_share)

            frp_mean = np.where(
                observed,
                np.maximum(1.5, np.expm1(vigor * 4.2 + self.rng.normal(0, 0.2, (n, n)))),
                0.0,
            ).astype(np.float32)
            frp_sum = (n_obs * frp_mean).astype(np.float32)
            frp_max = np.where(
                observed,
                frp_mean
                * np.clip(
                    1.0 + 0.45 * np.log1p(n_obs) + self.rng.uniform(0, 0.4, (n, n)),
                    1.0,
                    4.5,
                ),
                0.0,
            ).astype(np.float32)
            frp_p50 = (frp_mean * np.clip(self.rng.normal(0.82, 0.08, (n, n)), 0.5, 1.0)).astype(
                np.float32
            )

            high_frac = np.clip(0.2 + 0.65 * vigor + self.rng.normal(0, 0.1, (n, n)), 0.0, 1.0)
            n_high = np.minimum(n_obs, np.round(n_obs * high_frac)).astype(np.float32)
            conf_rank = np.where(
                ~observed, 0.0, np.where(n_high > 0, 2.0, np.where(vigor > 0.25, 1.0, 0.0))
            ).astype(np.float32)

            night_frac = np.clip(0.3 + 0.5 * vigor + self.rng.normal(0, 0.12, (n, n)), 0.0, 1.0)
            n_night = np.round(n_obs * night_frac).astype(np.float32)
            n_day = np.maximum(0.0, n_obs - n_night).astype(np.float32)

            footprint = np.where(
                observed,
                np.clip(
                    0.5
                    + (1.0 - viirs_share) * 2.2
                    + 0.9 * vigor
                    + self.rng.uniform(0, 0.6, (n, n)),
                    0.37,
                    4.8,
                ),
                0.0,
            ).astype(np.float32)
            n_plat = np.where(
                observed, np.clip(1.0 + np.floor(np.log1p(n_obs) * 0.8), 1.0, 3.0), 0.0
            ).astype(np.float32)
            pmix = np.where(
                observed, np.clip(self.rng.beta(1.2, 3.0, (n, n)), 0.0, 1.0), 0.0
            ).astype(np.float32)

            raw["frp_sum_mw"][step] = frp_sum
            raw["frp_max_mw"][step] = frp_max
            raw["frp_mean_mw"][step] = frp_mean
            raw["frp_p50_mw"][step] = frp_p50
            raw["n_obs"][step] = n_obs
            raw["n_high_conf"][step] = n_high
            raw["confidence_rank_max"][step] = conf_rank
            raw["n_day"][step] = n_day
            raw["n_night"][step] = n_night
            raw["footprint_max_km"][step] = footprint
            raw["n_platforms"][step] = n_plat
            raw["product_mix"][step] = pmix
            raw["n_obs_viirs"][step] = n_obs_viirs

            spread_power = vigor * (
                0.65
                + 0.25 * (n_high / np.maximum(n_obs, 1.0))
                + 0.20 * (n_night / np.maximum(n_obs, 1.0))
                + 0.15 * np.clip(footprint / 3.0, 0.0, 1.0)
            )
            no_ignite = np.ones((n, n), np.float32)
            for dy, dx in _NEIGHBORS:
                dist = np.hypot(dy, dx)
                src = _shift(spread_power, dy, dx)
                p = (self.base_spread / dist) * src
                no_ignite *= 1.0 - np.clip(p, 0.0, 1.0)
            p_ignite = (1.0 - no_ignite) * suscept
            new_fire = (age < 0) & (self.rng.random((n, n)) < p_ignite)

            age = np.where(age >= 0, age + 1, age)
            age[new_fire] = 0

        return raw, burning_hist

    def generate(self, n_samples: int) -> tuple[np.ndarray, np.ndarray]:
        """X: (N, T, H, W, C) float32; Y: (N, H, W, 1) máscara de fuego en t+1."""
        x_arr = np.empty((n_samples, self.t, self.n, self.n, self.c), np.float32)
        y_arr = np.empty((n_samples, self.n, self.n, 1), np.float32)
        i = 0
        while i < n_samples:
            ep_len = self.t + 1 + config.SYNTH_EPISODE_EXTRA_STEPS
            raw, burning = self.simulate_episode(ep_len)
            stacked = normalize_contract_channels(raw, self.c)  # (L, H, W, C)
            for s in range(0, ep_len - self.t, 2):
                if i >= n_samples:
                    break
                target = burning[s + self.t]
                if target.sum() == 0 and self.rng.random() < 0.8:
                    continue
                x_arr[i] = stacked[s : s + self.t]
                y_arr[i, ..., 0] = target
                i += 1
        return x_arr, y_arr


# Alias de compatibilidad hacia atrás
SyntheticFireGenerator = SyntheticContractGenerator


# ===========================================================================
# 4. Datos -> tf.data
# ===========================================================================
def load_npz_dataset(path: str) -> tuple[np.ndarray, np.ndarray]:
    with np.load(path) as d:
        x_arr, y_arr = d["X"].astype(np.float32), d["Y"].astype(np.float32)
    if y_arr.ndim == 3:
        y_arr = y_arr[..., None]
    return x_arr, y_arr


def _arrays_to_ds(
    x_arr: np.ndarray,
    y_arr: np.ndarray,
    batch_size: int,
    shuffle: bool,
    seed: int,
) -> tf.data.Dataset:
    ds = tf.data.Dataset.from_tensor_slices((x_arr, y_arr))
    if shuffle:
        ds = ds.shuffle(len(x_arr), seed=seed, reshuffle_each_iteration=True)
    return ds.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def make_datasets(
    x_arr: np.ndarray,
    y_arr: np.ndarray,
    batch_size: int = config.BATCH_SIZE,
    val_split: float = config.VALIDATION_SPLIT,
    seed: int = config.SEED,
) -> tuple[tf.data.Dataset, tf.data.Dataset]:
    if len(x_arr) != len(y_arr):
        raise ValueError("X e Y tienen distinto número de muestras")
    idx = np.random.default_rng(seed).permutation(len(x_arr))
    n_val = max(1, int(len(x_arr) * val_split))
    val_idx, tr_idx = idx[:n_val], idx[n_val:]
    return (
        _arrays_to_ds(x_arr[tr_idx], y_arr[tr_idx], batch_size, True, seed),
        _arrays_to_ds(x_arr[val_idx], y_arr[val_idx], batch_size, False, seed),
    )


def get_data(args, num_channels: int, grid: int, time_steps: int, seed_offset: int = 0):
    """Carga datos del contrato (.parquet/.jsonl/.npz) o sintéticos."""
    seed = args.seed + seed_offset
    if args.data:
        if args.data.endswith(".npz"):
            x_arr, y_arr = load_npz_dataset(args.data)
            x_arr = x_arr[..., :num_channels]
            expected = (time_steps, grid, grid, num_channels)
            if x_arr.shape[1:] != expected:
                raise ValueError(f"Datos {x_arr.shape[1:]} incompatibles con el modelo {expected}")
            logger.info(
                "Datos NPZ: X=%s Y=%s | celdas activas=%.4f",
                x_arr.shape,
                y_arr.shape,
                y_arr.mean(),
            )
            return make_datasets(x_arr, y_arr, args.batch_size, seed=seed)

        x_tr, y_tr, x_va, y_va = load_contract_cell_day(
            args.data,
            grid_size=grid,
            time_steps=time_steps,
            num_channels=num_channels,
            seed=seed,
        )
        logger.info(
            "Datos contrato (%s): train=%s val=%s | celdas activas=%.4f",
            os.path.basename(args.data),
            x_tr.shape,
            x_va.shape,
            y_tr.mean(),
        )
        return (
            _arrays_to_ds(x_tr, y_tr, args.batch_size, True, seed),
            _arrays_to_ds(x_va, y_va, args.batch_size, False, seed),
        )

    gen = SyntheticContractGenerator(grid, time_steps, num_channels, seed=seed)
    x_arr, y_arr = gen.generate(args.samples)
    logger.info(
        "Datos sintéticos (esquema cell_day): X=%s Y=%s | canales=%s | celdas en llamas=%.4f",
        x_arr.shape,
        y_arr.shape,
        list(config.CHANNEL_REGISTRY[:num_channels]),
        y_arr.mean(),
    )
    return make_datasets(x_arr, y_arr, args.batch_size, seed=seed)


# ===========================================================================
# 5. Bucle de entrenamiento común
# ===========================================================================
def build_callbacks(out_path: str, tag: str, patience: int):
    os.makedirs(config.LOG_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return [
        keras.callbacks.ModelCheckpoint(out_path, monitor="val_loss", save_best_only=True),
        keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=patience, restore_best_weights=True
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5, patience=config.REDUCE_LR_PATIENCE, min_lr=1e-6
        ),
        keras.callbacks.CSVLogger(os.path.join(config.LOG_DIR, f"{tag}.csv"), append=True),
        keras.callbacks.TerminateOnNaN(),
    ]


def fit(model, train_ds, val_ds, epochs: int, out_path: str, tag: str, patience: int) -> dict:
    if epochs <= 0:
        return {}
    history = model.fit(
        train_ds,
        validation_data=val_ds,
        epochs=epochs,
        callbacks=build_callbacks(out_path, tag, patience),
        verbose=2,
    )
    model.save(out_path)
    return {k: [float(v) for v in vals] for k, vals in history.history.items()}


def save_metadata(
    model_path: str,
    model: keras.Model,
    mode: str,
    history: dict,
    parent: str | None = None,
):
    """Sidecar JSON con el contrato de E/S alineado con `11_ML_DATA_CONTRACT.md`."""
    cfg = extract_model_config(model)
    meta = {
        "algorithm": config.ALGORITHM_NAME,
        "schema_reference": "11_ML_DATA_CONTRACT.md",
        "grid_id": config.GRID_ID,
        "crs": config.CRS,
        "grid_level": config.GRID_LEVEL,
        "cell_size_m": config.CHUNK_SIZE_M,
        "model_path": os.path.abspath(model_path),
        "mode": mode,
        "parent_checkpoint": parent,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "input_shape": [None, *cfg.input_shape],
        "output_shape": [None, cfg.height, cfg.width, 1],
        "channels": list(cfg.channel_names),
        "architecture": asdict(cfg),
        "final_metrics": {k: v[-1] for k, v in history.items()} if history else {},
    }
    with open(os.path.splitext(model_path)[0] + ".meta.json", "w") as f:
        json.dump(meta, f, indent=2)


def evaluate(model, val_ds, label: str) -> dict[str, float]:
    res = model.evaluate(val_ds, verbose=0, return_dict=True)
    logger.info("[%s] %s", label, "  ".join(f"{k}={v:.4f}" for k, v in res.items()))
    return res


# ===========================================================================
# 6. Modos de ejecución (Algoritmo CATA)
# ===========================================================================
def run_scratch(args) -> str:
    cfg = ModelConfig(
        num_channels=args.channels,
        time_steps=args.time_steps,
        height=args.grid,
        width=args.grid,
    )
    out = args.output or os.path.join(config.MODEL_DIR, f"cata_c{cfg.num_channels}.keras")
    model = create_model(cfg, args.lr or config.LEARNING_RATE)
    model.summary(print_fn=logger.info)
    train_ds, val_ds = get_data(args, cfg.num_channels, cfg.height, cfg.time_steps)
    hist = fit(
        model, train_ds, val_ds, args.epochs, out, f"scratch_c{cfg.num_channels}", args.patience
    )
    save_metadata(out, model, "scratch", hist)
    logger.info("Modelo CATA guardado en %s", out)
    return out


def run_finetune(args) -> str:
    _require_checkpoint(args)
    model = load_fire_model(args.checkpoint, learning_rate=args.lr or config.FINETUNE_LR)
    cfg = extract_model_config(model)
    out = args.output or args.checkpoint
    train_ds, val_ds = get_data(
        args, cfg.num_channels, cfg.height, cfg.time_steps, seed_offset=1000
    )
    evaluate(model, val_ds, "antes de fine-tuning")
    hist = fit(
        model, train_ds, val_ds, args.epochs, out, f"finetune_c{cfg.num_channels}", args.patience
    )
    evaluate(model, val_ds, "después de fine-tuning")
    save_metadata(out, model, "finetune", hist, parent=args.checkpoint)
    logger.info("Modelo CATA ajustado guardado en %s", out)
    return out


def run_expand(args) -> str:
    _require_checkpoint(args)
    model = expand_model_channels(
        args.checkpoint,
        args.new_channels,
        new_channel_init=args.init,
        learning_rate=config.EXPAND_WARMUP_LR,
    )
    cfg = extract_model_config(model)
    out = args.output or os.path.join(config.MODEL_DIR, f"cata_c{cfg.num_channels}.keras")
    train_ds, val_ds = get_data(
        args, cfg.num_channels, cfg.height, cfg.time_steps, seed_offset=2000
    )
    evaluate(model, val_ds, "tras surgery (sin entrenar)")

    history: dict = {}
    if args.warmup_epochs > 0:
        set_expansion_warmup(model, True)
        compile_model(model, args.lr or config.EXPAND_WARMUP_LR)
        history["warmup"] = fit(
            model,
            train_ds,
            val_ds,
            args.warmup_epochs,
            out,
            f"expand_c{cfg.num_channels}_warmup",
            args.patience,
        )
    set_expansion_warmup(model, False)
    compile_model(model, config.EXPAND_LR)
    history["full"] = fit(
        model,
        train_ds,
        val_ds,
        args.epochs,
        out,
        f"expand_c{cfg.num_channels}_full",
        args.patience,
    )
    if not os.path.exists(out):
        model.save(out)
    evaluate(model, val_ds, "tras expansión + entrenamiento")
    save_metadata(
        out,
        model,
        "expand",
        history.get("full") or history.get("warmup") or {},
        parent=args.checkpoint,
    )
    logger.info("Modelo CATA expandido guardado en %s", out)
    return out


def run_demo(args) -> None:
    """Smoke test rápido de los tres modos encadenados sobre el contrato."""
    demo_dir = os.path.join(config.MODEL_DIR, "demo")
    base = os.path.join(demo_dir, "cata_c1.keras")

    args.channels, args.output = 1, base
    run_scratch(args)

    args.checkpoint, args.output = base, os.path.join(demo_dir, "cata_c1_finetuned.keras")
    run_finetune(args)

    args.checkpoint = args.output
    args.new_channels = args.new_channels or config.EXPANDED_NUM_CHANNELS
    args.output = os.path.join(demo_dir, f"cata_c{args.new_channels}.keras")
    run_expand(args)
    logger.info("DEMO CATA OK — artefactos en %s", demo_dir)


def _require_checkpoint(args):
    if not args.checkpoint:
        raise SystemExit(f"--checkpoint es obligatorio en modo '{args.mode}'")


# ===========================================================================
# 7. CLI
# ===========================================================================
def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Entrenamiento del algoritmo CATA (ConvLSTM, 11_ML_DATA_CONTRACT.md)"
    )
    p.add_argument("--mode", choices=["scratch", "finetune", "expand", "demo"], default="scratch")
    p.add_argument("--channels", type=int, default=config.NUM_CHANNELS, help="C para modo scratch")
    p.add_argument("--new-channels", type=int, default=None, help="C nuevo para modo expand")
    p.add_argument(
        "--init",
        choices=["zeros", "glorot_uniform", "he_normal"],
        default="zeros",
        help="Inicialización de los pesos de los canales nuevos",
    )
    p.add_argument("--checkpoint", type=str, default=None, help="Modelo previo (.keras/.h5)")
    p.add_argument("--output", type=str, default=None, help="Ruta de salida del modelo")
    p.add_argument(
        "--data",
        type=str,
        default=None,
        help="Ruta a cell_day.parquet / cell_day.jsonl (contrato) o dataset .npz",
    )
    p.add_argument("--samples", type=int, default=config.SYNTH_NUM_SAMPLES)
    p.add_argument("--grid", type=int, default=config.GRID_SIZE)
    p.add_argument("--time-steps", type=int, default=config.TIME_STEPS)
    p.add_argument("--epochs", type=int, default=config.EPOCHS)
    p.add_argument("--warmup-epochs", type=int, default=2)
    p.add_argument("--batch-size", type=int, default=config.BATCH_SIZE)
    p.add_argument("--lr", type=float, default=None, help="Sobrescribe el LR del modo")
    p.add_argument("--patience", type=int, default=config.EARLY_STOPPING_PATIENCE)
    p.add_argument("--seed", type=int, default=config.SEED)
    args = p.parse_args(argv)

    if args.mode == "demo":
        if args.samples == config.SYNTH_NUM_SAMPLES:
            args.samples = 96
        if args.epochs == config.EPOCHS:
            args.epochs = 2
        args.warmup_epochs = min(args.warmup_epochs, 1)
    if args.mode == "expand" and not args.new_channels:
        args.new_channels = config.EXPANDED_NUM_CHANNELS
    return args


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = parse_args(argv)
    keras.utils.set_random_seed(args.seed)
    {
        "scratch": run_scratch,
        "finetune": run_finetune,
        "expand": run_expand,
        "demo": run_demo,
    }[args.mode](args)


if __name__ == "__main__":
    main()
