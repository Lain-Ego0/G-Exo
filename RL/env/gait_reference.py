from __future__ import annotations

import numpy as np


class CyclicGaitReference:
    """
    Time-indexed reference trajectory for the human controller.

    q and dq use the same coordinate order as state["tracking_q"]
    and state["tracking_dq"].

    human_control is the nominal human joint control from Moco or
    another offline gait generator. It is not visible to Actor.
    """

    def __init__(
        self,
        time_s: np.ndarray,
        q: np.ndarray,
        dq: np.ndarray,
        human_control: np.ndarray,
        *,
        cyclic: bool = True,
    ) -> None:
        self.time_s = np.asarray(
            time_s,
            dtype=np.float32,
        )

        self.q = np.asarray(
            q,
            dtype=np.float32,
        )

        self.dq = np.asarray(
            dq,
            dtype=np.float32,
        )

        self.human_control = np.asarray(
            human_control,
            dtype=np.float32,
        )

        self.cyclic = cyclic

        self.start_time_s = float(self.time_s[0])
        self.end_time_s = float(self.time_s[-1])
        self.period_s = (
            self.end_time_s
            - self.start_time_s
        )

    def sample(
        self,
        time_s: float,
    ) -> dict[str, np.ndarray | float]:
        sample_time_s = self._resolve_time(
            time_s
        )

        return {
            "q": self._interpolate(
                self.q,
                sample_time_s,
            ),
            "dq": self._interpolate(
                self.dq,
                sample_time_s,
            ),
            "human_control": self._interpolate(
                self.human_control,
                sample_time_s,
            ),
            "phase": self._phase(sample_time_s),
        }

    def _resolve_time(
        self,
        time_s: float,
    ) -> float:
        if not self.cyclic:
            return float(
                np.clip(
                    time_s,
                    self.start_time_s,
                    self.end_time_s,
                )
            )

        return float(
            self.start_time_s
            + np.mod(
                time_s - self.start_time_s,
                self.period_s,
            )
        )

    def _phase(
        self,
        time_s: float,
    ) -> float:
        return float(
            (time_s - self.start_time_s)
            / self.period_s
        )

    def _interpolate(
        self,
        values: np.ndarray,
        time_s: float,
    ) -> np.ndarray:
        return np.asarray(
            [
                np.interp(
                    time_s,
                    self.time_s,
                    values[:, index],
                )
                for index in range(values.shape[1])
            ],
            dtype=np.float64,
        )