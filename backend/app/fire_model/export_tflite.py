"""
export_tflite.py — Conversión y cuantización del modelo a TensorFlow Lite.

Modos de cuantización:
  none     float32 (referencia, máxima precisión)
  dynamic  pesos int8, activaciones float (≈4x más pequeño; recomendado)
  float16  pesos float16 (ideal para GPU delegates móviles)
  int8     cuantización completa con dataset representativo (CPU/NPU edge);
           si alguna op no admite int8 se mantiene en float.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable

import keras
import numpy as np
import tensorflow as tf

try:
    from . import config
except ImportError:
    import config

logger = logging.getLogger("fire_export")

QUANT_MODES = ("none", "dynamic", "float16", "int8")


def _representative_dataset(model: keras.Model, n: int = 64) -> Callable[[], Iterable]:
    """Muestras sintéticas con la misma forma/distribución que la entrada real."""
    try:
        from .train import SyntheticContractGenerator
    except ImportError:
        from train import SyntheticContractGenerator

    _, t, h, w, c = model.input_shape
    x_arr, _ = SyntheticContractGenerator(h, t, c, seed=123).generate(n)

    def gen():
        for i in range(len(x_arr)):
            yield [x_arr[i : i + 1]]

    return gen


def export_to_tflite(
    model_or_path,
    output_path: str = config.DEFAULT_TFLITE_PATH,
    quantization: str = "dynamic",
    batch_size: int = 1,
    representative_data: Callable[[], Iterable] | None = None,
    isolate_int8: bool = True,
) -> str:
    """Convierte un modelo Keras (objeto o ruta) a `.tflite`. Devuelve la ruta.

    La calibración int8 de grafos con bucles WHILE (ConvLSTM) puede abortar el
    proceso con un fallo nativo del conversor (segfault) en algunas versiones
    de TF. Con `isolate_int8=True` se ejecuta en un subproceso y, si muere,
    se recurre automáticamente a cuantización `dynamic`.
    """
    if quantization not in QUANT_MODES:
        raise ValueError(f"quantization debe ser uno de {QUANT_MODES}")
    model = (
        keras.models.load_model(model_or_path, compile=False)
        if isinstance(model_or_path, str)
        else model_or_path
    )

    if quantization == "int8" and isolate_int8 and representative_data is None:
        return _export_int8_isolated(model, model_or_path, output_path, batch_size)
    return _convert(model, output_path, quantization, batch_size, representative_data)


def _export_int8_isolated(model, model_or_path, output_path: str, batch_size: int) -> str:
    tmp_dir = None
    if isinstance(model_or_path, str):
        model_path = model_or_path
    else:
        tmp_dir = tempfile.mkdtemp(prefix="fire_int8_")
        model_path = os.path.join(tmp_dir, "model.keras")
        model.save(model_path)
    cmd = [
        sys.executable,
        os.path.abspath(__file__),
        "--model",
        model_path,
        "--output",
        output_path,
        "--quantization",
        "int8",
        "--batch-size",
        str(batch_size),
        "--no-verify",
        "--no-isolate",
    ]
    try:
        rc = subprocess.run(cmd, check=False).returncode  # noqa: S603
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    if rc == 0 and os.path.exists(output_path):
        return output_path
    logger.warning(
        "Cuantización int8 falló en el conversor (código %s). "
        "Usando cuantización 'dynamic' como alternativa.",
        rc,
    )
    return _convert(model, output_path, "dynamic", batch_size, None)


def _convert(model, output_path, quantization, batch_size, representative_data) -> str:
    """Conversión efectiva (en el proceso actual)."""
    spec = tf.TensorSpec((batch_size, *model.input_shape[1:]), tf.float32, name="chunk_sequence")
    saved_dir = tempfile.mkdtemp(prefix="fire_savedmodel_")
    model.export(saved_dir, format="tf_saved_model", input_signature=[spec], verbose=False)

    def make_converter(select_ops: bool) -> tf.lite.TFLiteConverter:
        conv = tf.lite.TFLiteConverter.from_saved_model(saved_dir)
        ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
        if quantization == "dynamic":
            conv.optimizations = [tf.lite.Optimize.DEFAULT]
        elif quantization == "float16":
            conv.optimizations = [tf.lite.Optimize.DEFAULT]
            conv.target_spec.supported_types = [tf.float16]
        elif quantization == "int8":
            conv.optimizations = [tf.lite.Optimize.DEFAULT]
            conv.representative_dataset = representative_data or _representative_dataset(model)
            ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8, tf.lite.OpsSet.TFLITE_BUILTINS]
        if select_ops:
            ops.append(tf.lite.OpsSet.SELECT_TF_OPS)
            conv._experimental_lower_tensor_list_ops = False
        conv.target_spec.supported_ops = ops
        return conv

    try:
        tflite_model = make_converter(select_ops=False).convert()
        logger.info("Conversión con ops nativas de TFLite: OK")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Ops nativas insuficientes (%s). Reintentando con SELECT_TF_OPS.",
            str(exc).splitlines()[0][:200],
        )
        tflite_model = make_converter(select_ops=True).convert()
    finally:
        shutil.rmtree(saved_dir, ignore_errors=True)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(tflite_model)
    logger.info(
        "TFLite (%s) guardado en %s — %.1f KB",
        quantization,
        output_path,
        len(tflite_model) / 1024,
    )
    return output_path


def run_tflite(tflite_path: str, x: np.ndarray) -> np.ndarray:
    """Inferencia con el intérprete TFLite. x: (batch_fijo, T, H, W, C)."""
    interpreter = tf.lite.Interpreter(model_path=tflite_path)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]
    interpreter.set_tensor(inp["index"], x.astype(inp["dtype"]))
    interpreter.invoke()
    return interpreter.get_tensor(out["index"])


def verify_tflite(tflite_path: str, model: keras.Model, seed: int = 0) -> float:
    """max|Keras - TFLite| sobre una entrada aleatoria (sanity check)."""
    _, t, h, w, c = model.input_shape
    x = np.random.default_rng(seed).random((1, t, h, w, c), dtype=np.float32)
    diff = float(np.max(np.abs(model.predict(x, verbose=0) - run_tflite(tflite_path, x))))
    logger.info("Verificación TFLite: max|Δ| = %.4e", diff)
    return diff


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    p = argparse.ArgumentParser(description="Exporta el modelo CATA de fuego a TFLite")
    p.add_argument("--model", default=config.DEFAULT_MODEL_PATH)
    p.add_argument("--output", default=config.DEFAULT_TFLITE_PATH)
    p.add_argument("--quantization", choices=QUANT_MODES, default="dynamic")
    p.add_argument("--batch-size", type=int, default=1, help="Batch fijo del grafo TFLite")
    p.add_argument("--no-verify", action="store_true")
    p.add_argument("--no-isolate", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args(argv)

    path = export_to_tflite(
        a.model,
        a.output,
        a.quantization,
        batch_size=a.batch_size,
        isolate_int8=not a.no_isolate,
    )
    if not a.no_verify:
        verify_tflite(path, keras.models.load_model(a.model, compile=False))


if __name__ == "__main__":
    main()
