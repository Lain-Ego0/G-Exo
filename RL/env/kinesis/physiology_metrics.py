"""Pure NumPy diagnostics for target-muscle loading.

These metrics describe the muscle solution produced by the simulator.  They
are intentionally independent from Gymnasium and the PPO reward so their
numerical behavior can be tested before they influence policy learning.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


EPSILON = 1.0e-8


@dataclass(frozen=True)
class PhysiologyMetrics:
    """Per-muscle and per-joint loading diagnostics for one simulation state."""

    target_activation: np.ndarray
    baseline_target_activation: np.ndarray
    target_activation_squared: np.ndarray
    baseline_target_activation_squared: np.ndarray
    target_muscle_force_n: np.ndarray
    baseline_target_muscle_force_n: np.ndarray
    target_joint_torque_contribution_nm: np.ndarray
    baseline_target_joint_torque_contribution_nm: np.ndarray
    muscle_effort_nm: np.ndarray
    baseline_muscle_effort_nm: np.ndarray
    net_joint_torque_nm: np.ndarray
    baseline_net_joint_torque_nm: np.ndarray
    positive_joint_torque_nm: np.ndarray
    negative_joint_torque_nm: np.ndarray
    baseline_positive_joint_torque_nm: np.ndarray
    baseline_negative_joint_torque_nm: np.ndarray
    co_contraction_abs_nm: np.ndarray
    baseline_co_contraction_abs_nm: np.ndarray
    co_contraction_index: np.ndarray
    baseline_co_contraction_index: np.ndarray
    co_contraction_excess: np.ndarray
    activation_overload: np.ndarray
    activation_overload_topk: float
    activation_cost: float
    baseline_activation_cost: float
    muscle_effort_torque_cost: float
    baseline_muscle_effort_torque_cost: float


def compute_physiology_metrics(
    *,
    activation: np.ndarray,
    baseline_activation: np.ndarray,
    muscle_force_n: np.ndarray,
    baseline_muscle_force_n: np.ndarray,
    target_moment_arm_m: np.ndarray,
    target_mask: np.ndarray | None = None,
    overload_top_k: int = 5,
) -> PhysiologyMetrics:
    """Compute non-cancelling muscle load, co-contraction and local overload.

    ``target_moment_arm_m[i, j] * muscle_force_n[i]`` is muscle ``i``'s
    signed torque contribution at target joint ``j``.  Absolute values are
    accumulated per muscle before averaging, so agonist and antagonist loads
    cannot cancel each other.

    The baseline inputs must describe the unassisted/shadow muscle solution at
    the same state.  This function does not decide whether a time-aligned or a
    same-state baseline is scientifically appropriate; it only computes the
    requested comparison consistently.
    """

    # MuJoCo's integrator can overshoot the muscle state briefly during a
    # sharp excitation switch.  Physiological activation is defined on [0, 1],
    # so diagnostics use the physical value rather than the integrator spike.
    activation = np.clip(
        _vector(activation, "activation"),
        0.0,
        1.0,
    )
    baseline_activation = np.clip(
        _vector(
            baseline_activation,
            "baseline_activation",
            size=activation.size,
        ),
        0.0,
        1.0,
    )
    muscle_force_n = _vector(
        muscle_force_n,
        "muscle_force_n",
        size=activation.size,
    )
    baseline_muscle_force_n = _vector(
        baseline_muscle_force_n,
        "baseline_muscle_force_n",
        size=activation.size,
    )
    moment = np.asarray(target_moment_arm_m, dtype=np.float64)
    if moment.ndim != 2 or moment.shape[0] != activation.size:
        raise ValueError(
            "target_moment_arm_m must have shape [muscle, joint], got "
            f"{moment.shape}."
        )
    if moment.shape[1] < 1 or not np.all(np.isfinite(moment)):
        raise ValueError("target_moment_arm_m must be finite and non-empty.")

    if target_mask is None:
        mask = np.ones(activation.size, dtype=bool)
    else:
        mask = np.asarray(target_mask, dtype=bool)
        if mask.shape != (activation.size,):
            raise ValueError(
                "target_mask must have shape "
                f"({activation.size},), got {mask.shape}."
            )
    if not np.any(mask):
        raise ValueError("target_mask selects no muscles.")
    if overload_top_k < 1:
        raise ValueError("overload_top_k must be positive.")

    target_activation = activation[mask]
    baseline_target_activation = baseline_activation[mask]
    target_force = muscle_force_n[mask]
    baseline_target_force = baseline_muscle_force_n[mask]
    target_moment = moment[mask]

    contribution = target_moment * target_force[:, None]
    baseline_contribution = target_moment * baseline_target_force[:, None]
    muscle_effort = np.sum(np.abs(contribution), axis=1)
    baseline_muscle_effort = np.sum(
        np.abs(baseline_contribution), axis=1
    )

    positive = np.sum(np.maximum(contribution, 0.0), axis=0)
    negative = np.sum(np.maximum(-contribution, 0.0), axis=0)
    baseline_positive = np.sum(
        np.maximum(baseline_contribution, 0.0), axis=0
    )
    baseline_negative = np.sum(
        np.maximum(-baseline_contribution, 0.0), axis=0
    )
    co_abs = np.minimum(positive, negative)
    baseline_co_abs = np.minimum(baseline_positive, baseline_negative)
    co_index = _co_contraction_index(positive, negative)
    baseline_co_index = _co_contraction_index(
        baseline_positive,
        baseline_negative,
    )

    activation_squared = np.square(target_activation)
    baseline_activation_squared = np.square(baseline_target_activation)
    activation_cost = float(np.mean(activation_squared))
    baseline_activation_cost = float(
        np.mean(baseline_activation_squared)
    )
    activation_overload = np.maximum(
        activation_squared - baseline_activation_squared,
        0.0,
    ) / max(baseline_activation_cost, EPSILON)
    top_k = min(int(overload_top_k), activation_overload.size)
    top_values = np.partition(activation_overload, -top_k)[-top_k:]

    return PhysiologyMetrics(
        target_activation=target_activation.copy(),
        baseline_target_activation=baseline_target_activation.copy(),
        target_activation_squared=activation_squared,
        baseline_target_activation_squared=baseline_activation_squared,
        target_muscle_force_n=target_force.copy(),
        baseline_target_muscle_force_n=baseline_target_force.copy(),
        target_joint_torque_contribution_nm=contribution,
        baseline_target_joint_torque_contribution_nm=(
            baseline_contribution
        ),
        muscle_effort_nm=muscle_effort,
        baseline_muscle_effort_nm=baseline_muscle_effort,
        net_joint_torque_nm=np.sum(contribution, axis=0),
        baseline_net_joint_torque_nm=np.sum(
            baseline_contribution, axis=0
        ),
        positive_joint_torque_nm=positive,
        negative_joint_torque_nm=negative,
        baseline_positive_joint_torque_nm=baseline_positive,
        baseline_negative_joint_torque_nm=baseline_negative,
        co_contraction_abs_nm=co_abs,
        baseline_co_contraction_abs_nm=baseline_co_abs,
        co_contraction_index=co_index,
        baseline_co_contraction_index=baseline_co_index,
        co_contraction_excess=np.maximum(
            co_index - baseline_co_index,
            0.0,
        ),
        activation_overload=activation_overload,
        activation_overload_topk=float(np.mean(top_values)),
        activation_cost=activation_cost,
        baseline_activation_cost=baseline_activation_cost,
        muscle_effort_torque_cost=float(np.mean(muscle_effort)),
        baseline_muscle_effort_torque_cost=float(
            np.mean(baseline_muscle_effort)
        ),
    )


def _co_contraction_index(
    positive: np.ndarray,
    negative: np.ndarray,
) -> np.ndarray:
    denominator = positive + negative
    return np.divide(
        2.0 * np.minimum(positive, negative),
        denominator,
        out=np.zeros_like(denominator),
        where=denominator > EPSILON,
    )


def _vector(
    value: np.ndarray,
    name: str,
    *,
    size: int | None = None,
) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 1 or (size is not None and array.size != size):
        expected = "[muscle]" if size is None else f"({size},)"
        raise ValueError(f"{name} must have shape {expected}, got {array.shape}.")
    if array.size < 1 or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite and non-empty.")
    return array


def main() -> None:
    """Run a deterministic formula self-test without MuJoCo."""

    metrics = compute_physiology_metrics(
        activation=np.array([0.4, 0.3, 0.2]),
        baseline_activation=np.array([0.3, 0.3, 0.2]),
        muscle_force_n=np.array([10.0, 8.0, 3.0]),
        baseline_muscle_force_n=np.array([8.0, 8.0, 3.0]),
        target_moment_arm_m=np.array(
            [[1.0, 0.0], [-1.0, 0.0], [0.0, 2.0]]
        ),
        overload_top_k=1,
    )
    np.testing.assert_allclose(metrics.net_joint_torque_nm, [2.0, 6.0])
    np.testing.assert_allclose(
        metrics.positive_joint_torque_nm
        - metrics.negative_joint_torque_nm,
        metrics.net_joint_torque_nm,
    )
    np.testing.assert_allclose(
        metrics.co_contraction_index,
        [16.0 / 18.0, 0.0],
    )
    assert metrics.activation_overload_topk > 0.0
    print("physiology metrics self-test passed")


if __name__ == "__main__":
    main()


__all__ = ["PhysiologyMetrics", "compute_physiology_metrics"]
