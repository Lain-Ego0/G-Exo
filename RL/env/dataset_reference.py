from __future__ import annotations

from pathlib import Path

import numpy as np

ANGLE_COLUMNS = (
    "hip_flexion_l",
    "knee_angle_l",
    "hip_flexion_r",
    "knee_angle_r",
)

VELOCITY_COLUMNS = (
    "hip_flexion_l_velocity",
    "knee_angle_l_velocity",
    "hip_flexion_r_velocity",
    "knee_angle_r_velocity",
)

class DatasetTrajectoryReference:
    def __init__(
        self,
        trial_dir:str | Path,
        *,
        joint_signs:np.ndarray| tuple[float,...] = (
            1.0,
            1.0,
            1.0,
            1.0,
        ),
        joint_offsets_rad:np.ndarray | tuple[float,...] = (
            0.0,
            0.0,
            0.0,
            0.0,
        ),
        cyclic:bool = False,
    ) -> None:
        self.trial_dir = Path(trial_dir)
        self.cyclic = bool(cyclic)
        
        signs = np.asarray(
            joint_signs,
            dtype=np.float64,
        )

        offsets = np.asarray(
            joint_offsets_rad,
            dtype=np.float64,
        )

        if signs.shape != (4,):
            raise ValueError(
                "joint_signs must have shape (4,)."
            )

        if offsets.shape != (4,):
            raise ValueError(
                "joint_offsets_rad must have shape (4,)."
            )

        angle_table = self._read_csv(
            "*_angle_filt.csv"
        )

        velocity_table = self._read_csv(
            "*_velocity.csv"
        )

        activity_table = self._read_csv(
            "*_activity_flag.csv"
        )
        
        angle_time = np.asarray(
            angle_table["time"],
            dtype=np.float64,
        )

        velocity_time = np.asarray(
            velocity_table["time"],
            dtype=np.float64,
        )

        activity_time = np.asarray(
            activity_table["time"],
            dtype=np.float64,
        )
        
        if not (
            np.allclose(
                angle_time,
                velocity_time,
                rtol = 0.0,
                atol = 1.0e-9,
            )
            and np.allclose(
                angle_time,
                activity_time,
                rtol = 0.0,
                atol = 1.0e-9,
            )
        ):
            raise ValueError(
                "Angle, velocity, and activity timestamps "
                "are not aligned."
            )
            
        q_deg = np.column_stack(
            [
                np.asarray(
                    angle_table[column],
                    dtype=np.float64,
                )
                for column in ANGLE_COLUMNS
            ]
        )
        
        dq_deg_s = np.column_stack(
            [
                np.asarray(
                    velocity_table[column],
                    dtype=np.float64,
                )
                for column in VELOCITY_COLUMNS
            ]
        )
        
        left_active = np.asarray(
            activity_table["left"],
            dtype=np.float64,
        )

        right_active = np.asarray(
            activity_table["right"],
            dtype=np.float64,
        )
        
        valid = (
            np.all(np.isfinite(q_deg),axis = 1)
            & np.all(np.isfinite(dq_deg_s),axis = 1)
            & np.isfinite(left_active)
            & np.isfinite(right_active)
            & (left_active > 0.5)
            & (right_active > 0.5) #这是什么意思？>0.5意味着什么？
        )
        
        active_slice = self._longest_true_run(
            valid
        )
        
        source_time_s = angle_time[active_slice]
        
        q_rad = np.deg2rad(
            q_deg[active_slice]
        )

        dq_rad_s = np.deg2rad(
            dq_deg_s[active_slice]
        )

        # 将数据集原始时间转换为从0开始的仿真时间。
        self.time_s = (
            source_time_s - source_time_s[0]
        )

        # signs和offsets用于适配数据集与当前OpenSim模型
        # 之间的关节正方向和零点差异。
        self.q = q_rad * signs + offsets
        self.dq = dq_rad_s * signs

        self.duration_s = float(
            self.time_s[-1]
        )

        if self.duration_s <= 0.0:
            raise ValueError(
                "The active trajectory has no positive duration."
            )

    def sample(
        self,
        time_s:float,
    ) -> dict[str,np.ndarray | float]:
        sample_time = self._resolve_time(
            float(time_s)
        )
        
        return {
            "q":self._interpolate(
                self.q,
                sample_time,
            ),
            
            "dq":self._interpolate(
                self.dq,
                sample_time,
            ),
            
            "human_control":np.zeros(
                4,
                dtype = np.float32
            ),
            
            "phase":float(
                sample_time / self.duration_s
            ),
        }
        
    def _resolve_time(
        self,
        time_s:float,
    ) -> float:
        if self.cyclic:
            return float(
                np.mod(
                    time_s,
                    self.duration_s,
                )
            )
            
        return float(np.clip(
            time_s,
            0.0,
            self.duration_s,
        ))
        
    def _interpolate(
        self,
        values:np.ndarray,
        time_s:float,
    ) -> np.ndarray:
        return np.asarray(
            [
                np.interp(
                    time_s,
                    self.time_s,
                    values[:, index],
                )for index in range(
                    values.shape[1],
                )
            ],
            dtype = np.float32,
        )
        
    def _read_csv(
        self,
        pattern: str,
    ) -> np.ndarray:
        matches = list(
            self.trial_dir.glob(pattern)
        )

        if len(matches) != 1:
            raise FileNotFoundError(
                f"Expected one '{pattern}' in "
                f"{self.trial_dir}, found {len(matches)}."
            )

        return np.genfromtxt(
            matches[0],
            delimiter=",",
            names=True,
            dtype=np.float64,
            encoding="utf-8",
        )
        
    @staticmethod
    def _longest_true_run(
        mask: np.ndarray,
    ) -> slice:#slice是什么？
        
        padded = np.concatenate(
            (
            [False],
            mask,
            [False],
            )
        )
        
        transition = np.flatnonzero(
            padded[1:] != padded[:-1]
        )
        
        ###以上一大段我没看懂
        
        if transition.size == 0:
            raise ValueError(
                "The trial has no valid active samples."
            )
            
        starts = transition[0::2]
        ends = transition[1::2]
        
        run_index = int(
            np.argmax(#argmax是什么来着……
                ends - starts,
            )
        )
        
        return slice(
            int(starts[run_index]),
            int(ends[run_index]),
        )      
        