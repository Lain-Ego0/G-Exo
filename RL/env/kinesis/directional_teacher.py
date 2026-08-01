"""Load Kinesis' reference-free target-goal locomotion policy."""

from __future__ import annotations

import sys
from pathlib import Path

import torch
from hydra import compose, initialize_config_dir

from RL.env.kinesis.teacher import KINESIS_ROOT, KinesisPolicy


DIRECTIONAL_MODEL_DIR = (
    KINESIS_ROOT / "data/trained_models/legs/target-reach"
)
REQUIRED_ASSETS = (
    KINESIS_ROOT / "data/xml/legs/myolegs.xml",
    KINESIS_ROOT / "data/kit_test_motion_dict.pkl",
    KINESIS_ROOT / "data/initial_pose/legs/initial_pose_test.pkl",
    DIRECTIONAL_MODEL_DIR / "model.pth",
)

if str(KINESIS_ROOT) not in sys.path:
    sys.path.insert(0, str(KINESIS_ROOT))

from src.agents.agent_directional import AgentDirectional  # noqa: E402


def missing_directional_assets() -> list[Path]:
    """Return files required by the official target-goal checkpoint."""

    return [path for path in REQUIRED_ASSETS if not path.is_file()]


def make_directional_agent(*, render: bool = False):
    """Build the official Kinesis directional environment and policy."""

    missing = missing_directional_assets()
    if missing:
        formatted = "\n".join(f"  - {path}" for path in missing)
        raise FileNotFoundError(
            "Missing Kinesis directional assets:\n" + formatted
        )

    with initialize_config_dir(
        version_base=None,
        config_dir=str((KINESIS_ROOT / "cfg").resolve()),
    ):
        config = compose(
            config_name="config_legs",
            overrides=(
                "learning=directional",
                "run=eval_run_legs",
                "exp_name=target-reach",
            ),
        )

    config.output_dir = str(DIRECTIONAL_MODEL_DIR)
    config.epoch = -1
    config.no_log = True
    config.test = True
    config.headless = not render
    config.run.test = True
    config.run.im_eval = False
    config.run.headless = not render
    config.run.num_threads = 1
    config.run.control_mode = "PD"

    for key in (
        "xml_path",
        "motion_file",
        "smpl_data_dir",
        "initial_pose_file",
    ):
        path = Path(config.run[key])
        if not path.is_absolute():
            config.run[key] = str((KINESIS_ROOT / path).resolve())

    agent = AgentDirectional(
        config,
        torch.float32,
        torch.device("cpu"),
        training=False,
        checkpoint_epoch=-1,
    )
    agent.policy_net.eval()
    return agent


def make_directional_policy(agent) -> KinesisPolicy:
    """Expose the target-goal policy through the existing NumPy wrapper."""

    return KinesisPolicy(agent)
