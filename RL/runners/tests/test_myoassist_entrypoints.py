"""Compatibility tests for the canonical MyoAssist G-Exo runners."""

import unittest

from RL.runners.evaluate_myoassist_exo import main as evaluate_exo_main
from RL.runners.evaluate_myoassist_gexo import main as evaluate_gexo_main
from RL.runners.train_myoassist_exo import main as train_exo_main
from RL.runners.train_myoassist_gexo import main as train_gexo_main


class MyoAssistEntrypointTest(unittest.TestCase):
    def test_train_entrypoint_delegates_without_copying_logic(self) -> None:
        self.assertIs(train_gexo_main, train_exo_main)

    def test_evaluate_entrypoint_delegates_without_copying_logic(self) -> None:
        self.assertIs(evaluate_gexo_main, evaluate_exo_main)


if __name__ == "__main__":
    unittest.main()
