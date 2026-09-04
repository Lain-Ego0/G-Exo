"""Convert MyoAssist muscle state to the shared pure-array contract."""

from __future__ import annotations

import hashlib
import json
from typing import Final

import mujoco
import numpy as np

from RL.optimization.contracts import MuscleSnapshot


MUSCLE_COUNT: Final = 22
ACTIVATION_SIDE_ORDER: Final = ("left", "right")
TARGET_ACTIVATION_MUSCLE_STEMS: Final = frozenset(
    {
        "hamstrings",
        "bifemsh",
        "glutmax",
        "iliopsoas",
        "rectfem",
        "vasti",
        "gastroc",
    }
)
TARGET_JOINT_NAMES: Final = (
    "hip_flexion_l",
    "knee_angle_l",
    "hip_flexion_r",
    "knee_angle_r",
)
# MyoAssist knee coordinates are extension-positive; deployment is flexion-positive.
TARGET_JOINT_SIGNS: Final = np.asarray(
    [1.0, -1.0, 1.0, -1.0],
    dtype=np.float64,
)
DEFAULT_ACTIVATION_HORIZON_S: Final = 0.02
_FORCE_TOLERANCE_N: Final = 1.0e-8


class MyoAssistMuscleAdapter:
    """Read 22 muscles without exposing MuJoCo objects to shared code."""

    def __init__(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        *,
        model_hash: str,
        activation_horizon_s: float = DEFAULT_ACTIVATION_HORIZON_S,
    ) -> None:
        if not isinstance(model_hash, str) or not model_hash.strip():
            raise ValueError("model_hash must be a non-empty string.")
        if model.nu < MUSCLE_COUNT or model.na != MUSCLE_COUNT:
            raise ValueError("Expected a model with 22 muscle activation states.")
        if data.act.size != model.na or data.ctrl.size != model.nu:
            raise ValueError("MjData dimensions do not match the supplied model.")

        self.model = model
        self.data = data
        self.model_hash = model_hash.strip()
        self.muscle_actuator_ids = np.arange(MUSCLE_COUNT, dtype=np.int32)
        self.activation_ids = np.asarray(
            model.actuator_actadr[self.muscle_actuator_ids],
            dtype=np.int32,
        )
        if not np.array_equal(
            self.activation_ids,
            np.arange(MUSCLE_COUNT, dtype=np.int32),
        ):
            raise ValueError(
                "The first 22 actuators must map one-to-one to activation state."
            )

        muscle_type = int(mujoco.mjtDyn.mjDYN_MUSCLE)
        if np.any(
            model.actuator_dyntype[self.muscle_actuator_ids] != muscle_type
        ):
            raise ValueError("The first 22 actuators must use muscle dynamics.")
        if np.any(
            model.actuator_ctrllimited[self.muscle_actuator_ids] == 0
        ):
            raise ValueError("Every muscle actuator must have a control range.")

        self.excitation_lower = np.asarray(
            model.actuator_ctrlrange[self.muscle_actuator_ids, 0],
            dtype=np.float64,
        ).copy()
        self.excitation_upper = np.asarray(
            model.actuator_ctrlrange[self.muscle_actuator_ids, 1],
            dtype=np.float64,
        ).copy()
        if (
            np.any(self.excitation_lower < 0.0)
            or np.any(self.excitation_upper > 1.0)
            or np.any(self.excitation_lower > self.excitation_upper)
        ):
            raise ValueError("Muscle excitation ranges must lie within [0, 1].")

        self.muscle_names = tuple(
            mujoco.mj_id2name(
                model,
                mujoco.mjtObj.mjOBJ_ACTUATOR,
                int(actuator_id),
            )
            for actuator_id in self.muscle_actuator_ids
        )
        if any(name is None for name in self.muscle_names) or len(
            set(self.muscle_names)
        ) != MUSCLE_COUNT:
            raise ValueError("The first 22 muscle names must be present and unique.")
        self.target_activation_masks = target_activation_masks(self.muscle_names)

        self.target_dof_ids = np.empty(len(TARGET_JOINT_NAMES), dtype=np.int32)
        for index, joint_name in enumerate(TARGET_JOINT_NAMES):
            joint_id = mujoco.mj_name2id(
                model,
                mujoco.mjtObj.mjOBJ_JOINT,
                joint_name,
            )
            if joint_id < 0:
                raise ValueError(f"Missing target joint: {joint_name}.")
            if model.jnt_type[joint_id] != mujoco.mjtJoint.mjJNT_HINGE:
                raise ValueError(f"Target joint {joint_name} must be a hinge.")
            self.target_dof_ids[index] = int(model.jnt_dofadr[joint_id])

        physics_dt_s = float(model.opt.timestep)
        if not np.isfinite(activation_horizon_s) or activation_horizon_s <= 0.0:
            raise ValueError("activation_horizon_s must be finite and positive.")
        step_ratio = float(activation_horizon_s) / physics_dt_s
        self.activation_substeps = int(round(step_ratio))
        if self.activation_substeps < 1 or not np.isclose(
            step_ratio,
            self.activation_substeps,
            atol=1.0e-10,
            rtol=0.0,
        ):
            raise ValueError(
                "activation_horizon_s must be an integer number of physics steps."
            )
        self.physics_dt_s = physics_dt_s
        self.activation_horizon_s = float(activation_horizon_s)
        self.target_mask = np.ones(MUSCLE_COUNT, dtype=bool)
        self.physiology_signature = self._physiology_signature()

    def snapshot(self) -> MuscleSnapshot:
        """Capture one immutable snapshot after the caller has run mj_forward."""

        activation = np.asarray(
            self.data.act[self.activation_ids],
            dtype=np.float64,
        ).copy()
        if (
            not np.all(np.isfinite(activation))
            or np.any(activation < 0.0)
            or np.any(activation > 1.0)
        ):
            raise ValueError("Muscle activation must be finite and in [0, 1].")

        activation_lower, activation_upper = (
            self._reachable_activation_bounds(activation)
        )
        dense_moment = self._dense_muscle_moment()
        moment_arm_m = (
            -dense_moment[:, self.target_dof_ids]
            * TARGET_JOINT_SIGNS[np.newaxis, :]
        )
        passive_force_n, active_force_gain_n = self._force_terms()
        measured_force_n = self._nonnegative_tension(
            -np.asarray(
                self.data.actuator_force[self.muscle_actuator_ids],
                dtype=np.float64,
            ),
            "measured muscle force",
        )
        affine_force_n = passive_force_n + active_force_gain_n * activation
        if not np.allclose(
            measured_force_n,
            affine_force_n,
            atol=1.0e-7,
            rtol=1.0e-9,
        ):
            raise RuntimeError(
                "Muscle force is stale or inconsistent; call mj_forward first."
            )

        return MuscleSnapshot(
            time_s=float(self.data.time),
            activation=activation,
            activation_lower=activation_lower,
            activation_upper=activation_upper,
            moment_arm_m=moment_arm_m,
            target_mask=self.target_mask,
            model_hash=self.model_hash,
            muscle_force_n=measured_force_n,
            active_force_gain_n=active_force_gain_n,
            passive_force_n=passive_force_n,
            metadata={
                "backend": "myoassist",
                "muscle_names": self.muscle_names,
                "activation_side_order": ACTIVATION_SIDE_ORDER,
                "target_activation_muscle_stems": tuple(
                    sorted(TARGET_ACTIVATION_MUSCLE_STEMS)
                ),
                "target_joint_names": TARGET_JOINT_NAMES,
                "target_joint_signs": tuple(TARGET_JOINT_SIGNS.tolist()),
                "activation_horizon_s": self.activation_horizon_s,
                "physics_timestep_s": self.physics_dt_s,
                "physiology_signature": self.physiology_signature,
            },
        )

    def _physiology_signature(self) -> str:
        """Identify the muscle model while allowing unrelated URDF bodies."""

        ids = self.muscle_actuator_ids
        payload = {
            "schema": "gexo_myoassist_physiology_v1",
            "muscle_names": self.muscle_names,
            "target_joint_names": TARGET_JOINT_NAMES,
            "target_joint_signs": TARGET_JOINT_SIGNS.tolist(),
            "control_range": self.model.actuator_ctrlrange[ids].tolist(),
            "dynamic_parameters": self.model.actuator_dynprm[ids].tolist(),
            "gain_parameters": self.model.actuator_gainprm[ids].tolist(),
            "bias_parameters": self.model.actuator_biasprm[ids].tolist(),
            "length_range": self.model.actuator_lengthrange[ids].tolist(),
            "physics_timestep_s": self.physics_dt_s,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


    def _dense_muscle_moment(self) -> np.ndarray:
        raw = np.asarray(self.data.actuator_moment, dtype=np.float64)
        if raw.size == self.model.nu * self.model.nv:
            return raw.reshape(self.model.nu, self.model.nv)[
                self.muscle_actuator_ids
            ].copy()

        dense = np.zeros((MUSCLE_COUNT, self.model.nv), dtype=np.float64)
        for local_id, actuator_id in enumerate(self.muscle_actuator_ids):
            start = int(self.data.moment_rowadr[actuator_id])
            stop = start + int(self.data.moment_rownnz[actuator_id])
            columns = np.asarray(
                self.data.moment_colind[start:stop],
                dtype=np.int32,
            )
            dense[local_id, columns] = raw[start:stop]
        if not np.all(np.isfinite(dense)):
            raise ValueError("Muscle actuator moment contains NaN or Inf.")
        return dense

    def _force_terms(self) -> tuple[np.ndarray, np.ndarray]:
        passive = np.empty(MUSCLE_COUNT, dtype=np.float64)
        active_gain = np.empty(MUSCLE_COUNT, dtype=np.float64)
        for local_id, actuator_id in enumerate(self.muscle_actuator_ids):
            length_range = self.model.actuator_lengthrange[actuator_id]
            acceleration = self.model.actuator_acc0[actuator_id]
            passive[local_id] = -mujoco.mju_muscleBias(
                self.data.actuator_length[actuator_id],
                length_range,
                acceleration,
                self.model.actuator_biasprm[actuator_id, :9],
            )
            active_gain[local_id] = -mujoco.mju_muscleGain(
                self.data.actuator_length[actuator_id],
                self.data.actuator_velocity[actuator_id],
                length_range,
                acceleration,
                self.model.actuator_gainprm[actuator_id, :9],
            )
        return (
            self._nonnegative_tension(passive, "passive muscle force"),
            self._nonnegative_tension(active_gain, "active muscle gain"),
        )

    def _reachable_activation_bounds(
        self,
        activation: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        at_lower = self._integrate_activation(
            activation,
            self.excitation_lower,
        )
        at_upper = self._integrate_activation(
            activation,
            self.excitation_upper,
        )
        lower = np.minimum(at_lower, at_upper)
        upper = np.maximum(at_lower, at_upper)
        if np.any(activation < lower - 1.0e-12) or np.any(
            activation > upper + 1.0e-12
        ):
            raise RuntimeError("Muscle dynamics bounds do not contain current state.")
        return np.minimum(lower, activation), np.maximum(upper, activation)

    def _integrate_activation(
        self,
        activation: np.ndarray,
        excitation: np.ndarray,
    ) -> np.ndarray:
        result = activation.copy()
        for _ in range(self.activation_substeps):
            derivative = np.empty(MUSCLE_COUNT, dtype=np.float64)
            for local_id, actuator_id in enumerate(self.muscle_actuator_ids):
                derivative[local_id] = mujoco.mju_muscleDynamics(
                    float(excitation[local_id]),
                    float(result[local_id]),
                    self.model.actuator_dynprm[actuator_id, :3],
                )
            result = np.clip(
                result + self.physics_dt_s * derivative,
                0.0,
                1.0,
            )
        return result

    @staticmethod
    def _nonnegative_tension(value: np.ndarray, name: str) -> np.ndarray:
        if not np.all(np.isfinite(value)):
            raise ValueError(f"{name} contains NaN or Inf.")
        if np.any(value < -_FORCE_TOLERANCE_N):
            raise ValueError(f"{name} violates the tensile-force sign contract.")
        return np.maximum(value, 0.0)


def target_activation_masks(
    muscle_names: tuple[str, ...],
) -> np.ndarray:
    """Return fixed left/right masks for muscles spanning a G-Exo joint."""

    if len(muscle_names) != MUSCLE_COUNT or len(set(muscle_names)) != MUSCLE_COUNT:
        raise ValueError("Expected 22 unique MyoAssist muscle names.")
    masks = np.zeros((len(ACTIVATION_SIDE_ORDER), MUSCLE_COUNT), dtype=bool)
    suffixes = ("_l", "_r")
    for side_index, suffix in enumerate(suffixes):
        for muscle_index, name in enumerate(muscle_names):
            if not name.endswith(suffix):
                continue
            stem = name[: -len(suffix)]
            masks[side_index, muscle_index] = (
                stem in TARGET_ACTIVATION_MUSCLE_STEMS
            )
    expected_count = len(TARGET_ACTIVATION_MUSCLE_STEMS)
    if np.any(np.sum(masks, axis=1) != expected_count):
        raise ValueError(
            "MyoAssist must provide every target hip/knee muscle on both sides."
        )
    return masks


def target_activation_costs(snapshot: MuscleSnapshot) -> np.ndarray:
    """Mean squared activation for left and right hip/knee muscle groups."""

    names = snapshot.metadata.get("muscle_names")
    if not isinstance(names, (tuple, list)):
        raise ValueError("Muscle snapshot has no ordered muscle_names metadata.")
    masks = target_activation_masks(tuple(names))
    squared = np.square(snapshot.activation)
    return np.asarray(
        [float(np.mean(squared[mask])) for mask in masks],
        dtype=np.float64,
    )


__all__ = [
    "ACTIVATION_SIDE_ORDER",
    "DEFAULT_ACTIVATION_HORIZON_S",
    "MUSCLE_COUNT",
    "MyoAssistMuscleAdapter",
    "TARGET_ACTIVATION_MUSCLE_STEMS",
    "TARGET_JOINT_NAMES",
    "TARGET_JOINT_SIGNS",
    "target_activation_costs",
    "target_activation_masks",
]
