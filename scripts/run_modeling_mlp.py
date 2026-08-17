"""Run the tabular-modeling skill with an added MLPRegressor candidate."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from sklearn.neural_network import MLPRegressor

SKILL_SCRIPT = Path.home() / ".codex" / "skills" / "tabular-modeling" / "scripts" / "run_modeling.py"
if not SKILL_SCRIPT.exists():
    alt = os.environ.get("CODEX_HOME")
    if alt:
        SKILL_SCRIPT = Path(alt) / "skills" / "tabular-modeling" / "scripts" / "run_modeling.py"

spec = importlib.util.spec_from_file_location("tabular_modeling_mlp", SKILL_SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _mlp_factory():
    return MLPRegressor(random_state=42, early_stopping=False)


epochs = int(os.environ.get("MLP_EPOCHS", "100"))
module.MODEL_SPECS["mlp"] = {
    "factory": _mlp_factory,
    "params": [
        {"hidden_layer_sizes": (64, 32), "max_iter": epochs},
        {"hidden_layer_sizes": (128, 64), "max_iter": epochs},
    ],
}


if __name__ == "__main__":
    module.main(sys.argv[1:])
