"""TensorFlow/Keras plumbing shared by every model: quiet logs, reproducible seeds, early
stopping with checkpoints, and where the saved `.keras` files go.

Import this module before building models: it hides TensorFlow's start-up chatter.
"""

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")  # errors only, before TF is imported

from datetime import UTC, datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import keras  # noqa: E402
import tensorflow as tf  # noqa: E402

tf.get_logger().setLevel("ERROR")  # no retracing chatter when predicting several sets

ML_DIR = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ML_DIR / "artifacts"


def set_seeds(seed: int) -> None:
    """Same seed, same data -> same model (Python, NumPy and TensorFlow, deterministic ops)."""
    keras.utils.set_random_seed(seed)
    tf.config.experimental.enable_op_determinism()


def new_version(now: datetime | None = None) -> str:
    """A sortable version name for a training run, e.g. "20261116-1328"."""
    return (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M")


def artifact_path(use_case: str, model_name: str, version: str) -> Path:
    """ml/artifacts/<use case>/<model>/<version>.keras (not committed to Git)."""
    return ARTIFACT_DIR / use_case / model_name / f"{version}.keras"


def relative_to_ml(path: Path) -> str:
    """How the registry stores a path: relative to ml/, with forward slashes."""
    try:
        return path.resolve().relative_to(ML_DIR).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def training_callbacks(
    checkpoint: Path, *, patience: int, monitor: str = "val_loss"
) -> list[keras.callbacks.Callback]:
    """Stop when the validation loss stops improving and keep the best epoch's weights
    (also written to `checkpoint`)."""
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    return [
        keras.callbacks.EarlyStopping(
            monitor=monitor, patience=patience, restore_best_weights=True
        ),
        keras.callbacks.ModelCheckpoint(checkpoint, monitor=monitor, save_best_only=True),
    ]


def save_model(model: keras.Model, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    model.save(path)
    return path


def load_model(path: Path) -> keras.Model:
    if not path.exists():
        raise FileNotFoundError(f"no saved model at {path}; train it first")
    return keras.models.load_model(path)
