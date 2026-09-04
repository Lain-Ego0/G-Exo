"""Load SB3 policies saved with newer NumPy/SB3 in older sim environments."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import zipfile

import numpy as np


def saved_space_shapes(model_path: str | Path) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Read Box shapes from SB3 JSON without unpickling versioned objects."""

    path = Path(model_path).expanduser().resolve(strict=True)
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read("data"))
    observation_shape = tuple(data["observation_space"]["_shape"])
    action_shape = tuple(data["action_space"]["_shape"])
    return observation_shape, action_shape


def load_ppo_for_inference(model_path: str | Path, *, device: str):
    """Load policy weights while replacing incompatible serialized metadata."""

    _install_numpy_core_aliases()
    observation_shape, action_shape = saved_space_shapes(model_path)

    from gymnasium import spaces
    from stable_baselines3 import PPO

    custom_objects = {
        "observation_space": spaces.Box(
            -np.inf,
            np.inf,
            shape=observation_shape,
            dtype=np.float32,
        ),
        "action_space": spaces.Box(
            -1.0,
            1.0,
            shape=action_shape,
            dtype=np.float32,
        ),
        # These schedules are training-only. Explicit replacements avoid
        # deserializing newer SB3 FloatSchedule classes during inference.
        "clip_range": lambda _: 0.2,
        "lr_schedule": lambda _: 0.0,
    }
    return PPO.load(
        model_path,
        device=device,
        custom_objects=custom_objects,
    )


def _install_numpy_core_aliases() -> None:
    """Map NumPy 2.x pickle module names onto NumPy 1.x equivalents."""

    try:
        importlib.import_module("numpy._core")
        return
    except ModuleNotFoundError:
        pass
    core = importlib.import_module("numpy.core")
    sys.modules.setdefault("numpy._core", core)
    for name in (
        "numeric",
        "multiarray",
        "_multiarray_umath",
        "umath",
        "fromnumeric",
        "shape_base",
        "overrides",
    ):
        try:
            module = importlib.import_module(f"numpy.core.{name}")
        except ImportError:
            continue
        sys.modules.setdefault(f"numpy._core.{name}", module)


__all__ = ["load_ppo_for_inference", "saved_space_shapes"]
