"""Load the frozen Kinesis human policy used by exoskeleton simulations."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np
import torch
from omegaconf import OmegaConf


GEXO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = GEXO_ROOT.parent
KINESIS_ROOT = WORKSPACE_ROOT / "third_party/Kinesis"
MODEL_DIR = (
    KINESIS_ROOT
    / "data/trained_models/legs_abs/kinesis-moe-imitation"
)
CONFIG_PATH = MODEL_DIR / ".hydra/config.yaml"

# Kinesis imports its own package as top-level ``src``.
if str(KINESIS_ROOT) not in sys.path:
    sys.path.insert(0, str(KINESIS_ROOT))

from src.agents import agent_dict  # noqa: E402


class KinesisPolicy:
    """Expose the frozen 86-muscle policy as a NumPy callback."""

    def __init__(self, agent) -> None:
        self.agent = agent
        self.agent.policy_net.eval()

    def reset(self, seed: int) -> None:
        """Reset random generators used by Kinesis and its MoE policy."""

        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)

    def __call__(self, observation: np.ndarray) -> np.ndarray:
        """Map a Kinesis observation to its normalized muscle action."""

        state = self.agent.preprocess_obs(observation)
        state_tensor = torch.from_numpy(state).to(
            device=self.agent.device,
            dtype=self.agent.dtype,
        )

        with torch.no_grad():
            selected = self.agent.policy_net.select_action(
                state_tensor,
                True,
            )

        # MoE returns (action, expert_index), whereas the directional
        # Lattice policy returns the action tensor directly.
        action = selected[0] if isinstance(selected, tuple) else selected

        action = action[0].detach().cpu().numpy()
        return self.agent.preprocess_actions(action)


def make_agent(motion_id: int, *, render: bool = False):
    """Load one Kinesis motion and its frozen imitation checkpoint.

    Each PPO worker loads one motion once.  This avoids rebuilding the large
    Kinesis policy and motion cache at every environment reset.
    """

    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(
            f"Missing Kinesis config: {CONFIG_PATH}"
        )

    config = OmegaConf.load(CONFIG_PATH)

    config.output_dir = str(MODEL_DIR)
    config.epoch = -1
    config.no_log = True
    config.test = True
    config.headless = not render

    config.run.test = True
    config.run.im_eval = True
    config.run.headless = not render
    config.run.fast_forward = True
    config.run.motion_id = int(motion_id)
    config.run.num_threads = 1

    # The checkpoint stores project-relative asset paths.
    for key in (
        "xml_path",
        "motion_file",
        "smpl_data_dir",
        "initial_pose_file",
    ):
        path = Path(config.run[key])

        if not path.is_absolute():
            config.run[key] = str(
                (KINESIS_ROOT / path).resolve()
            )

    device = torch.device("cpu")
    dtype = torch.float32
    agent_class = agent_dict[config.learning.agent_name]
    agent = agent_class(
        config,
        dtype,
        device,
        training=False,
        checkpoint_epoch=-1,
    )

    environment = agent.env
    environment.start_eval(im_eval=True)
    environment.motion_start_idx = int(motion_id)

    # Only one motion is needed per worker, keeping startup and memory bounded.
    environment.motion_lib.load_motions(
        environment.motion_lib_cfg,
        shape_params=environment.gender_betas,
        random_sample=False,
        start_idx=int(motion_id),
        silent=False,
    )

    return agent
