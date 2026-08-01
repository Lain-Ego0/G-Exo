#!/usr/bin/env python3
"""Thin shim so the spec'd path works without a colcon install:

    python scripts/mock_controller.py --scenario estop
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gexo_web_agent.mock_controller_node import main  # noqa: E402

if __name__ == "__main__":
    main()
