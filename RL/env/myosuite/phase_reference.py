"""读取Phase1/2人体轨迹，并按任意仿真时间返回参考状态。"""

from __future__ import annotations

from pathlib import Path

import numpy as np


# 直接采用MyoSuite中的关节顺序：先右腿，再左腿。
JOINT_NAMES = (
    "hip_flexion_r",
    "hip_adduction_r",
    "hip_rotation_r",
    "knee_angle_r",
    "ankle_angle_r",
    "subtalar_angle_r",
    "hip_flexion_l",
    "hip_adduction_l",
    "hip_rotation_l",
    "knee_angle_l",
    "ankle_angle_l",
    "subtalar_angle_l",
)

# Phase数据的膝屈曲为负，MyoSuite的膝屈曲为正。
# 角度、速度和力矩使用同一组符号，以保持机械功率不变。
JOINT_SIGNS = np.asarray(
    (
        1.0, 1.0, 1.0, -1.0, 1.0, 1.0,
        1.0, 1.0, 1.0, -1.0, 1.0, 1.0,
    ),
    dtype=np.float32,
)

ANGLE_COLUMNS = JOINT_NAMES

VELOCITY_COLUMNS = tuple(
    f"{joint}_velocity"
    for joint in JOINT_NAMES
)

MOMENT_COLUMNS = tuple(
    f"{joint}_moment"
    for joint in JOINT_NAMES
)


class PhaseReference:
    """一条Phase1/2人体行走参考轨迹。"""

    def __init__(
        self,
        trial_dir: str | Path,
        *,
        cyclic: bool = False,
    ) -> None:
        self.trial_dir = Path(trial_dir)
        self.cyclic = cyclic

        angle_table = self._read_csv("*_angle_filt.csv")
        velocity_table = self._read_csv("*_velocity.csv")
        moment_table = self._read_csv("*_moment_filt_bio.csv")

        angle_time = np.asarray(
            angle_table["time"],
            dtype=np.float64,
        )
        velocity_time = np.asarray(
            velocity_table["time"],
            dtype=np.float64,
        )
        moment_time = np.asarray(
            moment_table["time"],
            dtype=np.float64,
        )

        # 三种标签必须描述相同的一组采样时刻。
        for other_time in (velocity_time, moment_time):
            if (
                angle_time.shape != other_time.shape
                or not np.allclose(
                    angle_time,
                    other_time,
                    atol=1.0e-6,
                    rtol=0.0,
                )
            ):
                raise ValueError("Phase reference timestamps are not aligned.")

        if (
            len(angle_time) < 2
            or np.any(np.diff(angle_time) <= 0.0)
        ):
            raise ValueError("Reference time must be strictly increasing.")

        q_deg = self._read_columns(
            angle_table,
            ANGLE_COLUMNS,
        )
        dq_deg_s = self._read_columns(
            velocity_table,
            VELOCITY_COLUMNS,
        )
        moment_nm_kg = self._read_columns(
            moment_table,
            MOMENT_COLUMNS,
        )

        if (
            not np.all(np.isfinite(q_deg))
            or not np.all(np.isfinite(dq_deg_s))
        ):
            raise ValueError("Reference position or velocity contains NaN.")

        # Phase关节角单位为degree，MyoSuite使用rad。
        self.q = (
            np.deg2rad(q_deg).astype(np.float32)
            * JOINT_SIGNS
        )
        self.dq = (
            np.deg2rad(dq_deg_s).astype(np.float32)
            * JOINT_SIGNS
        )

        # 生物关节力矩单位为Nm/kg。
        # 缺失力矩先存为0，但必须结合moment_mask使用。
        self.moment_mask = np.isfinite(moment_nm_kg)
        self.moment_nm_kg = (
            np.nan_to_num(
                moment_nm_kg,
                nan=0.0,
            ).astype(np.float32)
            * JOINT_SIGNS
        )

        # 将数据集绝对时间转换为从0开始。
        self.time_s = (
            angle_time - angle_time[0]
        ).astype(np.float64)

        self.duration_s = float(self.time_s[-1])

    def sample(
        self,
        time_s: float,
    ) -> dict[str, float | np.ndarray]:
        """对轨迹进行线性插值，返回指定时刻的参考状态。"""

        sample_time = self._resolve_time(time_s)
        left, right, weight = self._interpolation_indices(
            sample_time
        )

        q = self._interpolate(
            self.q,
            left,
            right,
            weight,
        )
        dq = self._interpolate(
            self.dq,
            left,
            right,
            weight,
        )
        moment = self._interpolate(
            self.moment_nm_kg,
            left,
            right,
            weight,
        )

        # 两个相邻原始样本都有标签时，插值力矩才有效。
        moment_mask = (
            self.moment_mask[left]
            & self.moment_mask[right]
        )

        # 无效力矩保持为0，后续损失通过mask忽略。
        moment = np.where(
            moment_mask,
            moment,
            0.0,
        ).astype(np.float32)

        return {
            "time_s": float(sample_time),
            "phase": float(sample_time / self.duration_s),
            "q": q,
            "dq": dq,
            "moment_nm_kg": moment,
            "moment_mask": moment_mask.copy(),
        }

    def _resolve_time(self, time_s: float) -> float:
        """将外部时间转换到轨迹有效范围。"""

        if self.cyclic:
            return float(np.mod(time_s, self.duration_s))

        return float(np.clip(
            time_s,
            0.0,
            self.duration_s,
        ))

    def _interpolation_indices(
        self,
        time_s: float,
    ) -> tuple[int, int, float]:
        """找到time_s左右两侧的原始数据帧。"""

        if time_s <= 0.0:
            return 0, 0, 0.0

        if time_s >= self.duration_s:
            last = len(self.time_s) - 1
            return last, last, 0.0

        right = int(np.searchsorted(
            self.time_s,
            time_s,
            side="right",
        ))
        left = right - 1

        interval = self.time_s[right] - self.time_s[left]
        weight = (time_s - self.time_s[left]) / interval

        return left, right, float(weight)

    @staticmethod
    def _interpolate(
        values: np.ndarray,
        left: int,
        right: int,
        weight: float,
    ) -> np.ndarray:
        """在左右两帧之间做线性插值。"""

        result = (
            values[left] * (1.0 - weight)
            + values[right] * weight
        )

        return np.asarray(result, dtype=np.float32)

    def _read_csv(self, pattern: str) -> np.ndarray:
        """查找并读取trial中的一个CSV文件。"""

        matches = list(self.trial_dir.glob(pattern))

        if len(matches) != 1:
            raise FileNotFoundError(
                f"Expected one {pattern!r} in {self.trial_dir}, "
                f"found {len(matches)}."
            )

        return np.genfromtxt(
            matches[0],
            delimiter=",",
            names=True,
            dtype=np.float64,
            encoding="utf-8-sig",
        )

    @staticmethod
    def _read_columns(
        table: np.ndarray,
        columns: tuple[str, ...],
    ) -> np.ndarray:
        """按照固定关节顺序将结构化CSV转换为二维矩阵。"""

        return np.column_stack([
            np.asarray(table[column], dtype=np.float64)
            for column in columns
        ])
