from __future__ import annotations

import unittest

import numpy as np

from RL.controllers.delayed_prediction_audit import DelayedPredictionAudit


class DelayedPredictionAuditTest(unittest.TestCase):
    def test_prediction_is_compared_with_state_exactly_five_steps_later(
        self,
    ) -> None:
        audit = DelayedPredictionAudit(horizon_steps=5)
        q_errors = []
        dq_errors = []

        for step in range(6):
            q_error, dq_error = audit.update(
                current_q=np.full(4, 0.15 * step, dtype=np.float32),
                current_dq=np.full(4, 0.30 * step, dtype=np.float32),
                predicted_q=np.full(4, 0.15 * step + 1.0, dtype=np.float32),
                predicted_dq=np.full(4, 0.30 * step + 2.0, dtype=np.float32),
            )
            q_errors.append(q_error)
            dq_errors.append(dq_error)

        q_errors = np.asarray(q_errors)
        dq_errors = np.asarray(dq_errors)
        self.assertTrue(np.isnan(q_errors[:5]).all())
        self.assertTrue(np.isnan(dq_errors[:5]).all())
        np.testing.assert_allclose(
            q_errors[5],
            -0.25,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            dq_errors[5],
            -0.50,
            atol=1.0e-6,
        )

    def test_censored_prediction_is_not_used_in_error_metric(self) -> None:
        audit = DelayedPredictionAudit(horizon_steps=2)
        zeros = np.zeros(4, dtype=np.float32)
        audit.update(
            current_q=zeros,
            current_dq=zeros,
            predicted_q=np.full(4, 5.0, dtype=np.float32),
            predicted_dq=np.full(4, 5.0, dtype=np.float32),
            prediction_valid=False,
        )
        audit.update(
            current_q=zeros,
            current_dq=zeros,
            predicted_q=zeros,
            predicted_dq=zeros,
        )
        q_error, dq_error = audit.update(
            current_q=zeros,
            current_dq=zeros,
            predicted_q=zeros,
            predicted_dq=zeros,
        )
        self.assertTrue(np.isnan(q_error).all())
        self.assertTrue(np.isnan(dq_error).all())


if __name__ == "__main__":
    unittest.main()
