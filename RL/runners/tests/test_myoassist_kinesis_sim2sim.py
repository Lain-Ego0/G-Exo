"""Pure report tests for the MyoAssist-to-Kinesis transfer audit."""

import unittest

from RL.runners.evaluate_myoassist_kinesis_sim2sim import build_transfer_audit


def row(mode: str, mpjpe: float, success: bool = True) -> dict:
    return {
        "mode": mode,
        "motion_id": 8,
        "seed": 0,
        "success": success,
        "mean_mpjpe_mm": mpjpe,
        "mean_absolute_exo_torque_nm": 0.0 if mode == "baseline" else 3.0,
        "action_saturation_ratio": 0.0,
        "cuff_force_p95_n": 100.0,
        "cuff_error_p95_mm": 2.0,
    }


class Sim2SimAuditTest(unittest.TestCase):
    def test_tracking_inside_margin_passes(self) -> None:
        audit = build_transfer_audit(
            {"rows": [row("baseline", 40.0), row("policy", 50.0)]},
            mpjpe_margin_mm=15.0,
        )
        self.assertTrue(audit["passed"])

    def test_policy_failure_fails(self) -> None:
        audit = build_transfer_audit(
            {
                "rows": [
                    row("baseline", 40.0),
                    row("policy", 41.0, success=False),
                ]
            },
            mpjpe_margin_mm=15.0,
        )
        self.assertFalse(audit["passed"])


if __name__ == "__main__":
    unittest.main()
