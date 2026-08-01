from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

VARIABLE_SPEED_TARGETS = (
    "motion_rate_rad_s",
    "delta_motion_rate_rad_s",
    "nominal_speed_m_s",
)


class TCNDataset(Dataset):
    def __init__(
        self,
        root:Path,
        split:str,
        *,
        history:int = 50,
        horizons:tuple[int,...] = (5,10),
        statistics:dict[str,np.ndarray] | None = None,
        include_auxiliary: bool = False,
    ) -> None:
        self.history = history
        self.horizons = horizons
        self.include_auxiliary = include_auxiliary
        
        files = sorted(
            (root / split).glob("*/*.npz")
        )
        
        if not files:
            raise FileNotFoundError(
                f"No NPZ files in {root / split}"
            )
            
        self.trials = []
        
        for path in files:
            with np.load(path) as data:
                activity = (
                    str(data["activity"].item())
                    if "activity" in data
                    else "fixed_speed_walk"
                )
                nominal_speed = (
                    float(data["nominal_speed_m_s"].item())
                    if "nominal_speed_m_s" in data
                    else float("nan")
                )
                self.trials.append({
                    "input":data["input"].copy(),
                    "target":data["target"].copy(),
                    "input_valid":data["input_valid"].copy(),
                    "target_mask":data["target_mask"].copy(),
                    "subject": str(data["subject"].item()),
                    "trial": str(data["trial"].item()),
                    "condition": str(data["condition"].item()),
                    "assist_condition": (
                        str(data["assist_condition"].item())
                        if "assist_condition" in data
                        else str(data["condition"].item())
                    ),
                    "activity": activity,
                    "nominal_speed_m_s": nominal_speed,
                    "motion_rate": (
                        data["motion_rate"].copy()
                        if "motion_rate" in data
                        else None
                    ),
                    "motion_rate_mask": (
                        data["motion_rate_mask"].copy()
                        if "motion_rate_mask" in data
                        else None
                    ),
                    "path": str(path),
                })

        if include_auxiliary and any(
            trial["motion_rate"] is None
            for trial in self.trials
        ):
            raise ValueError(
                "Variable-speed dataset needs motion_rate arrays. "
                "Regenerate it with preprocess_tcn.py."
            )

        self.samples:list[tuple[int,int]] = []
        
        max_horizon = max(horizons)
        
        for trial_index, trial in enumerate(self.trials):
            length = len(trial["input"])
            
            for end in range(
                history - 1,
                length - max_horizon,
            ):
                start = end - history + 1
                
                if trial["input_valid"][start:end + 1].all():
                    self.samples.append(
                        (trial_index, end)
                )

        if statistics is None:
            if split != "train":
                raise ValueError(
                    "Validation dataset needs training statistics."
                )

            statistics = self._compute_statistics()

        if include_auxiliary and "auxiliary_mean" not in statistics:
            raise ValueError(
                "Variable-speed dataset needs auxiliary training statistics."
            )

        self.statistics = statistics

    def _auxiliary_target(
        self,
        trial: dict,
        end: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        future_indices = np.asarray([
            end + horizon
            for horizon in self.horizons
        ])
        future_rate = trial["motion_rate"][future_indices]
        future_valid = trial["motion_rate_mask"][future_indices]
        current_rate = float(trial["motion_rate"][end])
        current_valid = bool(trial["motion_rate_mask"][end])
        nominal_speed = float(trial["nominal_speed_m_s"])
        target = np.stack(
            (
                future_rate,
                future_rate - current_rate,
                np.full_like(future_rate, nominal_speed),
            ),
            axis=1,
        ).astype(np.float32)
        mask = np.stack(
            (
                future_valid,
                future_valid & current_valid,
                np.full_like(
                    future_valid,
                    np.isfinite(nominal_speed),
                ),
            ),
            axis=1,
        ).astype(bool)
        return target, mask

    def _compute_statistics(
        self,
    ) -> dict[str,np.ndarray]:
        inputs = np.concatenate([
            trial["input"][trial["input_valid"]]
            for trial in self.trials
        ])

        targets = np.concatenate([
            trial["target"]
            for trial in self.trials
        ])

        masks = np.concatenate([
            trial["target_mask"]
            for trial in self.trials
        ])

        input_mean = inputs.mean(axis=0)
        input_std = np.maximum(
            inputs.std(axis=0),
            1e-6,
        )

        counts = masks.sum(axis=0)

        if np.any(counts == 0):
            raise ValueError(
                "A target column has no valid training data."
            )
            
        target_mean = (
            (targets * masks).sum(axis=0)
            / counts
        )

        target_variance = (
            ((targets - target_mean) ** 2 * masks).sum(axis=0)
            / counts
        )

        target_std = np.maximum(
            np.sqrt(target_variance),
            1e-6,
        )

        result = {
            "input_mean": input_mean.astype(np.float32),
            "input_std": input_std.astype(np.float32),
            "target_mean": target_mean.astype(np.float32),
            "target_std": target_std.astype(np.float32),
        }

        if self.include_auxiliary:
            auxiliary = []
            auxiliary_masks = []

            for trial_index, end in self.samples:
                values, valid = self._auxiliary_target(
                    self.trials[trial_index],
                    end,
                )
                auxiliary.append(values)
                auxiliary_masks.append(valid)

            auxiliary_values = np.concatenate(auxiliary, axis=0)
            auxiliary_valid = np.concatenate(auxiliary_masks, axis=0)
            auxiliary_counts = auxiliary_valid.sum(axis=0)

            if np.any(auxiliary_counts == 0):
                raise ValueError("An auxiliary target has no valid training data.")

            auxiliary_mean = (
                np.where(auxiliary_valid, auxiliary_values, 0.0).sum(axis=0)
                / auxiliary_counts
            )
            auxiliary_variance = (
                np.where(
                    auxiliary_valid,
                    (auxiliary_values - auxiliary_mean) ** 2,
                    0.0,
                ).sum(axis=0)
                / auxiliary_counts
            )
            start_stop_delta = []

            for trial_index, end in self.samples:
                trial = self.trials[trial_index]

                if trial["activity"] != "start_stop":
                    continue

                values, valid = self._auxiliary_target(trial, end)

                if valid[-1, 1]:
                    start_stop_delta.append(float(values[-1, 1]))

            if start_stop_delta:
                lower, upper = np.quantile(
                    start_stop_delta,
                    (0.2, 0.8),
                )
            else:
                lower, upper = -0.1, 0.1

            result.update({
                "auxiliary_mean": auxiliary_mean.astype(np.float32),
                "auxiliary_std": np.maximum(
                    np.sqrt(auxiliary_variance),
                    1e-6,
                ).astype(np.float32),
                "motion_rate_delta_lower": float(lower),
                "motion_rate_delta_upper": float(upper),
                "motion_rate_stop_threshold": 0.15,
            })

        return result

    def transition_label(
        self,
        trial_index: int,
        end: int,
    ) -> str:
        trial = self.trials[trial_index]

        if trial["activity"] != "start_stop":
            return "fixed_speed"

        values, valid = self._auxiliary_target(trial, end)

        if not valid[-1, 1]:
            return "unknown"

        current_rate = float(trial["motion_rate"][end])
        future_rate = float(values[-1, 0])
        stop_threshold = float(
            self.statistics["motion_rate_stop_threshold"]
        )

        if max(current_rate, future_rate) < stop_threshold:
            return "stopped"

        delta = float(values[-1, 1])

        if delta <= float(self.statistics["motion_rate_delta_lower"]):
            return "decelerating"

        if delta >= float(self.statistics["motion_rate_delta_upper"]):
            return "accelerating"

        return "steady"

    def balanced_sample_weights(self) -> np.ndarray:
        """平衡 fixed/start-stop、速度/阶段、condition 和 trial。"""

        if not self.include_auxiliary:
            return np.ones(len(self), dtype=np.float64)

        records = []

        for trial_index, end in self.samples:
            trial = self.trials[trial_index]

            if trial["activity"] == "fixed_speed_walk":
                subgroup = (
                    f"{trial['nominal_speed_m_s']:.1f}",
                    trial["assist_condition"],
                )
            else:
                subgroup = (
                    self.transition_label(trial_index, end),
                    trial["assist_condition"],
                )

            records.append((
                trial["activity"],
                subgroup,
                trial_index,
            ))

        activities = sorted({record[0] for record in records})
        groups_by_activity = {
            activity: sorted({
                record[1]
                for record in records
                if record[0] == activity
            })
            for activity in activities
        }
        trials_by_group = {}
        samples_by_trial_group = {}

        for activity, subgroup, trial_index in records:
            group = (activity, subgroup)
            trials_by_group.setdefault(group, set()).add(trial_index)
            key = (activity, subgroup, trial_index)
            samples_by_trial_group[key] = (
                samples_by_trial_group.get(key, 0) + 1
            )

        weights = np.empty(len(records), dtype=np.float64)

        for index, (activity, subgroup, trial_index) in enumerate(records):
            group = (activity, subgroup)
            key = (activity, subgroup, trial_index)
            weights[index] = (
                1.0 / len(activities)
                / len(groups_by_activity[activity])
                / len(trials_by_group[group])
                / samples_by_trial_group[key]
            )

        return weights * (len(weights) / weights.sum())
        
    def __len__(self) -> int:
        return len(self.samples)
    
    def __getitem__(
        self,
        index:int,
    ) -> tuple[torch.Tensor,torch.Tensor,torch.Tensor]:
        trial_index,end = self.samples[index]
        trial = self.trials[trial_index]
        
        start = end - self.history + 1
        
        inputs = trial["input"][start:end + 1]
        
        future_indices = [
            end + horizon
            for horizon in self.horizons
        ]
        
        targets = trial["target"][future_indices]
        target_mask = trial["target_mask"][future_indices]
        
        inputs = (
            inputs - self.statistics["input_mean"]
        ) / self.statistics["input_std"]
        
        targets = (
            targets - self.statistics["target_mean"]
        ) / self.statistics["target_std"]
        
        targets = np.where(
            target_mask,
            targets,
            0.0,
        )
        
        inputs = inputs.T.astype(
            np.float32,
            copy=False,
        )
        
        sample = (
            torch.from_numpy(inputs.copy()),
            torch.from_numpy(targets.astype(np.float32)),
            torch.from_numpy(target_mask)
        )

        if not self.include_auxiliary:
            return sample

        auxiliary, auxiliary_mask = self._auxiliary_target(trial, end)
        auxiliary = (
            auxiliary - self.statistics["auxiliary_mean"]
        ) / self.statistics["auxiliary_std"]
        auxiliary = np.where(auxiliary_mask, auxiliary, 0.0)
        return sample + (
            torch.from_numpy(auxiliary.astype(np.float32)),
            torch.from_numpy(auxiliary_mask),
        )
        
def main() -> None:
    data_root = os.environ.get("GEXO_DATA_ROOT")
    
    if not data_root:
        raise RuntimeError("Set GEXO_DATA_ROOT.")
    
    root = Path(data_root) / "processed/tcn50"
    
    train_dataset = TCNDataset(
        root,
        "train",
    )
    
    validation_dataset = TCNDataset(
        root,
        "validation",
        statistics = train_dataset.statistics,
    )
    
    inputs, targets, mask = train_dataset[0]

    print("train samples:", len(train_dataset))
    print("validation samples:", len(validation_dataset))
    print("input shape:", tuple(inputs.shape))
    print("target shape:", tuple(targets.shape))
    print("mask shape:", tuple(mask.shape))
    print("input finite:", bool(torch.isfinite(inputs).all()))
    print("target finite:", bool(torch.isfinite(targets).all()))

if __name__ == "__main__":
    main()
