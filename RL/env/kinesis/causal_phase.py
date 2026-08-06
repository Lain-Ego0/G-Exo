"""Causal TCN gait-phase estimator for deployable motor and IMU signals."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

from RL.env.kinesis.oracle_phase import OraclePhase, extract_oracle_phase
from RL.runners.predictors.tcn import ResidualBlock


SENSOR_DIM = 32
DEFAULT_HISTORY = 32
EPSILON = 1.0e-8


@dataclass(frozen=True)
class CausalPhasePrediction:
    """One causal phase estimate aligned to the input trace timeline."""

    phase: np.ndarray
    phase_rate_hz: np.ndarray
    confidence: np.ndarray
    valid: np.ndarray


class CausalPhaseTCN(nn.Module):
    """Map past-only sensor windows to circular phase and phase rate."""

    def __init__(
        self,
        input_dim: int = SENSOR_DIM,
        hidden_dim: int = 32,
        dropout: float = 0.05,
    ) -> None:
        super().__init__()
        self.input_dim = int(input_dim)
        self.hidden_dim = int(hidden_dim)
        self.dropout = float(dropout)
        self.encoder = nn.Sequential(
            ResidualBlock(input_dim, hidden_dim, 1, dropout=dropout),
            ResidualBlock(hidden_dim, hidden_dim, 2, dropout=dropout),
            ResidualBlock(hidden_dim, hidden_dim, 4, dropout=dropout),
            ResidualBlock(hidden_dim, hidden_dim, 8, dropout=dropout),
        )
        # First two outputs encode sin/cos phase.  Softplus converts the last
        # output to a positive stride frequency in Hz.
        self.head = nn.Linear(hidden_dim, 3)

    def forward(self, inputs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if inputs.ndim != 3 or inputs.shape[1] != self.input_dim:
            raise ValueError(
                "Phase-TCN input must have shape "
                f"[batch, {self.input_dim}, time]."
            )
        latent = self.encoder(inputs)[:, :, -1]
        raw = self.head(latent)
        unit_phase = F.normalize(raw[:, :2], dim=1, eps=EPSILON)
        phase_rate_hz = F.softplus(raw[:, 2]) + 0.05
        return unit_phase, phase_rate_hz


class CausalPhaseAdapter:
    """Maintain one deployable sensor history and expose three Actor features."""

    FEATURE_DIM = 3

    def __init__(self, checkpoint: str | Path, *, device: str = "cpu") -> None:
        self.device = device
        self.model, self.statistics = load_phase_checkpoint(
            checkpoint,
            device=device,
        )
        self.history_length = int(self.statistics["history"])
        self._history: deque[np.ndarray] = deque(maxlen=self.history_length)
        self._latest = np.zeros(self.FEATURE_DIM, dtype=np.float32)
        self._confidence = 0.0

    @property
    def ready(self) -> bool:
        return len(self._history) == self.history_length

    @property
    def features(self) -> np.ndarray:
        return self._latest.copy()

    @property
    def confidence(self) -> float:
        return float(self._confidence)

    def reset(self) -> None:
        self._history.clear()
        self._latest.fill(0.0)
        self._confidence = 0.0

    def append(self, sensor_frame: np.ndarray) -> None:
        frame = np.asarray(sensor_frame, dtype=np.float32)
        if frame.shape != (SENSOR_DIM,) or not np.all(np.isfinite(frame)):
            raise ValueError("Phase sensor frame must be a finite 32-D vector.")
        self._history.append(frame.copy())
        if not self.ready:
            return
        prediction = predict_phase(
            self.model,
            self.statistics,
            np.stack(tuple(self._history), axis=0),
            device=self.device,
        )
        phase = float(prediction.phase[-1])
        rate = float(prediction.phase_rate_hz[-1])
        angle = 2.0 * np.pi * phase
        self._latest = np.asarray(
            [np.sin(angle), np.cos(angle), np.clip(rate, 0.0, 2.0)],
            dtype=np.float32,
        )
        self._confidence = float(prediction.confidence[-1])


def circular_phase_target(phase: np.ndarray) -> np.ndarray:
    """Encode phase in a continuous representation around the 0/1 boundary."""

    angle = 2.0 * np.pi * np.asarray(phase, dtype=np.float64)
    return np.stack((np.sin(angle), np.cos(angle)), axis=1).astype(np.float32)


def circular_phase_error(prediction: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Return the shortest absolute error in cycles."""

    delta = np.mod(
        np.asarray(prediction) - np.asarray(target) + 0.5,
        1.0,
    ) - 0.5
    return np.abs(delta)


def trace_oracle_phase(trace: dict) -> OraclePhase:
    """Create offline supervision labels from one collected trace."""

    return extract_oracle_phase(
        trace["touch"],
        dt=float(np.asarray(trace["control_dt"]).item()),
        on_threshold=float(np.asarray(trace["contact_on_threshold"]).item()),
        off_threshold=float(np.asarray(trace["contact_off_threshold"]).item()),
    )


def phase_windows(
    traces: list[dict],
    *,
    history: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build past-only windows and oracle labels from baseline traces."""

    windows = []
    phase_targets = []
    rate_targets = []
    for trace in traces:
        sensors = _sensor_array(trace)
        oracle = trace_oracle_phase(trace)
        for end in np.flatnonzero(oracle.valid):
            start = int(end) - history + 1
            if start < 0:
                continue
            window = sensors[start : int(end) + 1]
            if np.all(np.isfinite(window)):
                windows.append(window.T)
                phase_targets.append(oracle.phase[int(end)])
                rate_targets.append(oracle.phase_rate_hz[int(end)])
    if not windows:
        raise ValueError("No valid causal phase windows are available.")
    return (
        np.asarray(windows, dtype=np.float32),
        circular_phase_target(np.asarray(phase_targets)),
        np.asarray(rate_targets, dtype=np.float32),
    )


def fit_phase_tcn(
    traces: list[dict],
    *,
    history: int = DEFAULT_HISTORY,
    hidden_dim: int = 32,
    dropout: float = 0.05,
    epochs: int = 300,
    learning_rate: float = 3.0e-3,
    rate_loss_weight: float = 0.2,
    seed: int = 0,
    device: str = "cpu",
) -> tuple[CausalPhaseTCN, dict]:
    """Fit a compact phase model on zero-assistance baseline traces only."""

    if history < 2 or epochs < 1 or learning_rate <= 0.0:
        raise ValueError("Phase-TCN training settings are invalid.")
    torch.manual_seed(int(seed))
    np.random.seed(int(seed))
    windows, phase_target, rate_target = phase_windows(
        traces,
        history=history,
    )
    input_mean = windows.transpose(0, 2, 1).reshape(-1, SENSOR_DIM).mean(axis=0)
    input_std = np.maximum(
        windows.transpose(0, 2, 1).reshape(-1, SENSOR_DIM).std(axis=0),
        1.0e-5,
    )
    normalized = (
        (windows - input_mean[None, :, None]) / input_std[None, :, None]
    ).astype(np.float32)

    torch_device = torch.device(device)
    model = CausalPhaseTCN(
        hidden_dim=hidden_dim,
        dropout=dropout,
    ).to(torch_device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    inputs = torch.from_numpy(normalized).to(torch_device)
    phase_labels = torch.from_numpy(phase_target).to(torch_device)
    rate_labels = torch.from_numpy(rate_target).to(torch_device)

    model.train()
    final_loss = float("nan")
    for _ in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        predicted_phase, predicted_rate = model(inputs)
        phase_loss = torch.mean((predicted_phase - phase_labels) ** 2)
        rate_loss = torch.mean(
            ((predicted_rate - rate_labels) / rate_labels.clamp_min(0.1)) ** 2
        )
        loss = phase_loss + rate_loss_weight * rate_loss
        loss.backward()
        optimizer.step()
        final_loss = float(loss.detach().cpu())

    statistics = {
        "schema_version": 1,
        "history": int(history),
        "input_dim": SENSOR_DIM,
        "hidden_dim": int(hidden_dim),
        "dropout": float(dropout),
        "input_mean": input_mean.astype(np.float32),
        "input_std": input_std.astype(np.float32),
        "training_samples": int(len(windows)),
        "training_seed": int(seed),
        "final_loss": final_loss,
    }
    model.eval()
    model.requires_grad_(False)
    return model, statistics


def predict_phase(
    model: CausalPhaseTCN,
    statistics: dict,
    sensor_frame: np.ndarray,
    *,
    device: str = "cpu",
) -> CausalPhasePrediction:
    """Run causal sliding-window inference without touch or future samples."""

    sensors = np.asarray(sensor_frame, dtype=np.float32)
    if sensors.ndim != 2 or sensors.shape[1] != SENSOR_DIM:
        raise ValueError(f"sensor_frame must have shape [time, {SENSOR_DIM}].")
    history = int(statistics["history"])
    mean = np.asarray(statistics["input_mean"], dtype=np.float32)
    std = np.asarray(statistics["input_std"], dtype=np.float32)
    length = len(sensors)
    phase = np.full(length, np.nan, dtype=np.float64)
    phase_rate = np.full(length, np.nan, dtype=np.float64)
    confidence = np.zeros(length, dtype=np.float64)
    valid = np.zeros(length, dtype=bool)
    if length < history:
        return CausalPhasePrediction(phase, phase_rate, confidence, valid)

    windows = np.lib.stride_tricks.sliding_window_view(
        sensors,
        window_shape=history,
        axis=0,
    )
    # NumPy returns [sample, channel, history] for a 2-D input and axis=0.
    normalized = (windows - mean[None, :, None]) / std[None, :, None]
    inputs = torch.from_numpy(np.ascontiguousarray(normalized)).to(device)
    with torch.inference_mode():
        unit, rate = model(inputs)
        unit_np = unit.cpu().numpy()
        rate_np = rate.cpu().numpy()
    predicted = np.mod(
        np.arctan2(unit_np[:, 0], unit_np[:, 1]) / (2.0 * np.pi),
        1.0,
    )
    indices = np.arange(history - 1, length)
    phase[indices] = predicted
    phase_rate[indices] = rate_np
    # The pre-normalization magnitude is unavailable after model.forward;
    # temporal agreement provides a causal confidence proxy instead.
    if predicted.size:
        delta = np.abs(
            np.mod(np.diff(predicted, prepend=predicted[0]) + 0.5, 1.0) - 0.5
        )
        expected = rate_np / 50.0
        confidence[indices] = np.exp(-20.0 * np.abs(delta - expected))
    valid[indices] = np.isfinite(phase[indices]) & np.isfinite(phase_rate[indices])
    return CausalPhasePrediction(phase, phase_rate, confidence, valid)


def save_phase_checkpoint(
    path: str | Path,
    model: CausalPhaseTCN,
    statistics: dict,
    *,
    held_out_seed: int | None,
) -> None:
    """Store one versioned phase model and its fixed normalization."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            **statistics,
            "held_out_seed": held_out_seed,
            "model_state_dict": model.state_dict(),
        },
        output,
    )


def load_phase_checkpoint(
    path: str | Path,
    *,
    device: str = "cpu",
) -> tuple[CausalPhaseTCN, dict]:
    """Load one phase checkpoint in both legacy and current PyTorch."""

    checkpoint_path = Path(path)
    try:
        checkpoint = torch.load(
            checkpoint_path,
            map_location=device,
            weights_only=False,
        )
    except TypeError:
        checkpoint = torch.load(checkpoint_path, map_location=device)
    if int(checkpoint.get("schema_version", -1)) != 1:
        raise ValueError(f"Unsupported phase checkpoint: {checkpoint_path}")
    model = CausalPhaseTCN(
        input_dim=int(checkpoint["input_dim"]),
        hidden_dim=int(checkpoint["hidden_dim"]),
        dropout=float(checkpoint["dropout"]),
    ).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    model.requires_grad_(False)
    return model, checkpoint


def _sensor_array(trace: dict) -> np.ndarray:
    if "sensor_frame" not in trace:
        raise KeyError(
            "Trace has no deployable sensor_frame. Re-run "
            "collect_oracle_phase_rollouts.py."
        )
    sensors = np.asarray(trace["sensor_frame"], dtype=np.float32)
    if sensors.ndim != 2 or sensors.shape[1] != SENSOR_DIM:
        raise ValueError(
            f"sensor_frame must have shape [time, {SENSOR_DIM}], got {sensors.shape}."
        )
    return sensors
