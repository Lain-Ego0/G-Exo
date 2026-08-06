from __future__ import annotations

import ast
import unittest
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import numpy as np

from RL.env.kinesis.physiology_metrics import (
    compute_physiology_metrics as compute_kinesis_metrics,
)
from RL.metrics.physiology import (
    PhysiologyMetrics,
    compute_physiology_metrics,
)
from RL.optimization.contracts import (
    MUSCLE_SNAPSHOT_SCHEMA,
    TARGET_JOINT_COUNT,
    MuscleSnapshot,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SHARED_SOURCE_PATHS = (
    REPOSITORY_ROOT / "RL" / "metrics" / "physiology.py",
    REPOSITORY_ROOT / "RL" / "optimization" / "contracts.py",
)


def _assert_value_error_cases(
    test: unittest.TestCase,
    function: Callable[..., object],
    base: dict[str, object],
    cases: tuple[tuple[str, dict[str, object]], ...],
) -> None:
    for name, override in cases:
        with test.subTest(name=name), test.assertRaises(ValueError):
            function(**(base | override))


def _metric_inputs(muscle_count: int = 22) -> dict[str, object]:
    index = np.arange(muscle_count, dtype=np.float64)
    moment_arm = np.column_stack(
        (
            0.01 + 0.001 * index,
            np.where(index % 2 == 0, -0.02, 0.015),
            np.where(index % 3 == 0, 0.025, -0.01),
            np.where(index % 4 == 0, -0.03, 0.02),
        )
    )
    return {
        "activation": np.linspace(-0.1, 1.1, muscle_count),
        "baseline_activation": np.linspace(0.9, 0.1, muscle_count),
        "muscle_force_n": 20.0 + 1.5 * index,
        "baseline_muscle_force_n": 18.0 + 1.25 * index,
        "target_moment_arm_m": moment_arm,
    }


def _snapshot_inputs(muscle_count: int = 22) -> dict[str, object]:
    index = np.arange(muscle_count, dtype=np.float64)
    return {
        "time_s": 0.25,
        "activation": np.linspace(0.1, 0.9, muscle_count),
        "activation_lower": np.zeros(muscle_count, dtype=np.float64),
        "activation_upper": np.ones(muscle_count, dtype=np.float64),
        "moment_arm_m": np.column_stack(
            (
                0.01 + index * 0.001,
                -0.02 - index * 0.001,
                0.03 + index * 0.001,
                -0.04 - index * 0.001,
            )
        ),
        "target_mask": index % 2 == 0,
        "model_hash": "synthetic-model-sha256",
        "muscle_force_n": 100.0 + index,
        "metadata": {"source": "synthetic", "trial": 3},
    }


class SharedPhysiologyEquivalenceTest(unittest.TestCase):
    def assert_metrics_equal(
        self,
        actual: PhysiologyMetrics,
        expected: object,
    ) -> None:
        self.assertEqual(
            tuple(field.name for field in fields(actual)),
            tuple(field.name for field in fields(expected)),
        )
        for field in fields(actual):
            actual_value = getattr(actual, field.name)
            expected_value = getattr(expected, field.name)
            if isinstance(actual_value, np.ndarray):
                np.testing.assert_array_equal(actual_value, expected_value)
            else:
                self.assertEqual(actual_value, expected_value)

    def test_shared_formula_is_elementwise_equivalent_to_kinesis(self) -> None:
        inputs = _metric_inputs()
        inputs["target_mask"] = np.arange(22) % 3 != 1
        inputs["overload_top_k"] = 7
        original_inputs = {
            name: value.copy() if isinstance(value, np.ndarray) else value
            for name, value in inputs.items()
        }

        shared = compute_physiology_metrics(**inputs)
        kinesis = compute_kinesis_metrics(**inputs)

        self.assert_metrics_equal(shared, kinesis)
        for name, expected in original_inputs.items():
            if isinstance(expected, np.ndarray):
                np.testing.assert_array_equal(inputs[name], expected)

    def test_default_mask_selects_all_22_muscles(self) -> None:
        inputs = _metric_inputs()
        default_metrics = compute_physiology_metrics(**inputs)
        explicit_metrics = compute_physiology_metrics(
            **inputs,
            target_mask=np.ones(22, dtype=bool),
        )

        self.assert_metrics_equal(default_metrics, explicit_metrics)
        self.assertEqual(default_metrics.target_activation.shape, (22,))
        self.assertEqual(
            default_metrics.target_joint_torque_contribution_nm.shape,
            (22, 4),
        )
        self.assertEqual(default_metrics.muscle_effort_nm.shape, (22,))
        self.assertEqual(default_metrics.net_joint_torque_nm.shape, (4,))
        clipped_activation = np.clip(inputs["activation"], 0.0, 1.0)
        self.assertEqual(
            default_metrics.activation_cost,
            float(np.mean(np.square(clipped_activation))),
        )

    def test_manual_antagonist_case_preserves_non_cancelling_load(self) -> None:
        activation = np.full(22, 0.2, dtype=np.float64)
        force = np.zeros(22, dtype=np.float64)
        force[:2] = 10.0
        moment_arm = np.zeros((22, 4), dtype=np.float64)
        moment_arm[0, 0] = 0.1
        moment_arm[1, 0] = -0.1

        metrics = compute_physiology_metrics(
            activation=activation,
            baseline_activation=activation,
            muscle_force_n=force,
            baseline_muscle_force_n=force,
            target_moment_arm_m=moment_arm,
        )

        np.testing.assert_array_equal(metrics.net_joint_torque_nm, np.zeros(4))
        np.testing.assert_array_equal(
            metrics.muscle_effort_nm[:2],
            np.ones(2),
        )
        np.testing.assert_array_equal(
            metrics.co_contraction_abs_nm,
            np.array([1.0, 0.0, 0.0, 0.0]),
        )
        np.testing.assert_array_equal(
            metrics.co_contraction_index,
            np.array([1.0, 0.0, 0.0, 0.0]),
        )
        self.assertEqual(metrics.muscle_effort_torque_cost, 2.0 / 22.0)

    def test_metrics_reject_invalid_shapes_values_masks_and_top_k(self) -> None:
        base = _metric_inputs(muscle_count=3)
        cases = (
            ("activation rank", {"activation": np.zeros((1, 3))}),
            (
                "activation finite",
                {"activation": np.array([0.1, np.nan, 0.3])},
            ),
            ("baseline size", {"baseline_activation": np.zeros(2)}),
            ("force size", {"muscle_force_n": np.zeros(2)}),
            (
                "baseline force finite",
                {"baseline_muscle_force_n": np.array([1.0, np.inf, 2.0])},
            ),
            ("moment rows", {"target_moment_arm_m": np.zeros((2, 4))}),
            ("moment joints", {"target_moment_arm_m": np.zeros((3, 0))}),
            (
                "moment finite",
                {"target_moment_arm_m": np.full((3, 4), np.nan)},
            ),
            ("mask shape", {"target_mask": np.ones(2, dtype=bool)}),
            ("empty mask", {"target_mask": np.zeros(3, dtype=bool)}),
            ("top k", {"overload_top_k": 0}),
        )
        _assert_value_error_cases(
            self,
            compute_physiology_metrics,
            base,
            cases,
        )


class MuscleSnapshotContractTest(unittest.TestCase):
    def test_snapshot_defensively_copies_and_freezes_caller_inputs(self) -> None:
        inputs = _snapshot_inputs()
        expected_arrays = {
            name: value.copy()
            for name, value in inputs.items()
            if isinstance(value, np.ndarray)
        }
        metadata = inputs["metadata"]
        snapshot = MuscleSnapshot(**inputs)

        for value in inputs.values():
            if isinstance(value, np.ndarray):
                value[...] = 0
        metadata["source"] = "changed"
        metadata["new_key"] = True

        for name, expected in expected_arrays.items():
            stored = getattr(snapshot, name)
            np.testing.assert_array_equal(stored, expected)
            self.assertFalse(stored.flags.writeable)
        self.assertEqual(dict(snapshot.metadata), {"source": "synthetic", "trial": 3})
        self.assertEqual(snapshot.muscle_count, 22)
        self.assertEqual(snapshot.schema_version, MUSCLE_SNAPSHOT_SCHEMA)
        self.assertEqual(snapshot.moment_arm_m.shape, (22, TARGET_JOINT_COUNT))

        with self.assertRaises(FrozenInstanceError):
            snapshot.time_s = 1.0
        with self.assertRaises(ValueError):
            snapshot.activation[0] = 0.5
        with self.assertRaises(TypeError):
            snapshot.metadata["trial"] = 4

        resolved = snapshot.resolved_muscle_force_n()
        resolved[0] = -1.0
        self.assertEqual(snapshot.muscle_force_n[0], expected_arrays["muscle_force_n"][0])

    def test_affine_force_model_resolves_default_and_candidate_activation(self) -> None:
        inputs = _snapshot_inputs(muscle_count=3)
        inputs.pop("muscle_force_n")
        gain = np.array([100.0, 200.0, 300.0])
        passive = np.array([10.0, 20.0, 30.0])
        inputs["active_force_gain_n"] = gain
        inputs["passive_force_n"] = passive
        snapshot = MuscleSnapshot(**inputs)
        gain.fill(0.0)
        passive.fill(0.0)

        np.testing.assert_array_equal(
            snapshot.resolved_muscle_force_n(),
            snapshot.passive_force_n + snapshot.active_force_gain_n * snapshot.activation,
        )
        self.assertFalse(snapshot.active_force_gain_n.flags.writeable)
        self.assertFalse(snapshot.passive_force_n.flags.writeable)
        candidate = np.array([0.2, 0.4, 0.6])
        np.testing.assert_array_equal(
            snapshot.resolved_muscle_force_n(candidate),
            np.array([30.0, 100.0, 210.0]),
        )
        with self.assertRaisesRegex(ValueError, "outside the snapshot bounds"):
            snapshot.resolved_muscle_force_n(np.array([0.2, 0.4, 1.1]))

        measured_only = MuscleSnapshot(**_snapshot_inputs(muscle_count=3))
        with self.assertRaisesRegex(RuntimeError, "no affine force model"):
            measured_only.resolved_muscle_force_n(candidate)

    def test_snapshot_rejects_invalid_contract_states(self) -> None:
        base = _snapshot_inputs(muscle_count=3)
        cases = (
            ("time", {"time_s": np.nan}),
            ("activation rank", {"activation": np.zeros((1, 3))}),
            (
                "activation finite",
                {"activation": np.array([0.1, np.inf, 0.2])},
            ),
            ("lower size", {"activation_lower": np.zeros(2)}),
            (
                "bounds range",
                {"activation_lower": np.array([-0.1, 0.0, 0.0])},
            ),
            (
                "bounds order",
                {
                    "activation_lower": np.array([0.0, 0.8, 0.0]),
                    "activation_upper": np.array([1.0, 0.7, 1.0]),
                },
            ),
            ("activation bounds", {"activation": np.array([0.1, 0.5, 1.1])}),
            ("moment shape", {"moment_arm_m": np.zeros((3, 3))}),
            (
                "moment finite",
                {"moment_arm_m": np.full((3, 4), np.nan)},
            ),
            ("mask shape", {"target_mask": np.ones(2, dtype=bool)}),
            ("empty mask", {"target_mask": np.zeros(3, dtype=bool)}),
            ("force size", {"muscle_force_n": np.ones(2)}),
            (
                "negative force",
                {"muscle_force_n": np.array([1.0, -1.0, 1.0])},
            ),
            ("no force model", {"muscle_force_n": None}),
            (
                "partial force model",
                {
                    "muscle_force_n": None,
                    "active_force_gain_n": np.ones(3),
                },
            ),
            (
                "negative gain",
                {
                    "muscle_force_n": None,
                    "active_force_gain_n": np.array([1.0, -1.0, 1.0]),
                    "passive_force_n": np.ones(3),
                },
            ),
            (
                "negative passive",
                {
                    "muscle_force_n": None,
                    "active_force_gain_n": np.ones(3),
                    "passive_force_n": np.array([1.0, -1.0, 1.0]),
                },
            ),
            ("model hash", {"model_hash": "  "}),
            ("schema", {"schema_version": "future-schema"}),
            ("valid reason", {"validity_reason": "unexpected"}),
            ("invalid reason", {"valid": False}),
        )
        _assert_value_error_cases(self, MuscleSnapshot, base, cases)

        invalid = MuscleSnapshot(
            **(base | {"valid": False, "validity_reason": "solver failed"})
        )
        self.assertFalse(invalid.valid)
        self.assertEqual(invalid.validity_reason, "solver failed")

    def test_snapshot_normalizes_scalars_and_rejects_wrong_status_types(self) -> None:
        base = _snapshot_inputs(muscle_count=3)
        snapshot = MuscleSnapshot(
            **(
                base
                | {
                    "time_s": np.float32(0.5),
                    "valid": np.bool_(False),
                    "validity_reason": "  solver failed  ",
                }
            )
        )
        self.assertIs(type(snapshot.time_s), float)
        self.assertIs(type(snapshot.valid), bool)
        self.assertEqual(snapshot.validity_reason, "solver failed")

        cases = (
            ("array time", {"time_s": np.array([0.5])}),
            ("boolean time", {"time_s": True}),
            ("string time", {"time_s": "0.5"}),
            ("complex time", {"time_s": np.complex128(0.5 + 0.1j)}),
            ("string valid", {"valid": "yes"}),
            (
                "non-string reason",
                {"valid": False, "validity_reason": 7},
            ),
        )
        for name, override in cases:
            with self.subTest(name=name), self.assertRaises(TypeError):
                MuscleSnapshot(**(base | override))

        with self.assertRaises(ValueError):
            MuscleSnapshot(
                **(base | {"valid": False, "validity_reason": "   "})
            )


class SharedModuleBoundaryTest(unittest.TestCase):
    def test_shared_sources_use_only_standard_library_and_numpy_imports(self) -> None:
        allowed_roots = {
            "__future__",
            "dataclasses",
            "numbers",
            "types",
            "typing",
            "numpy",
        }
        forbidden_names = ("kinesis", "myoassist", "mujoco", "gymnasium")

        for path in SHARED_SOURCE_PATHS:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
                imported_roots = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported_roots.update(
                            alias.name.split(".", maxsplit=1)[0]
                            for alias in node.names
                        )
                    elif isinstance(node, ast.ImportFrom):
                        self.assertEqual(node.level, 0)
                        if node.module is not None:
                            imported_roots.add(node.module.split(".", maxsplit=1)[0])

                self.assertLessEqual(imported_roots, allowed_roots)
                lowered = source.lower()
                for forbidden in forbidden_names:
                    self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
