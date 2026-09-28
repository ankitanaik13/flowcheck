"""Small live-provider integration sample, kept separate from the offline benchmark."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pipelinemedic.pipeline import make_lab
from pipelinemedic.service import evaluate

results = []
for scenario in ["join_fanout", "compound", "genuine_shift"]:
    result, _ = evaluate(make_lab("2011-10-05", scenario, 42, 0.3), "ollama")
    results.append({"scenario": scenario, **result})
    print(scenario, result["status"], result["investigation"]["diagnosis"], flush=True)
(ROOT / "artifacts/live-smoke.json").write_text(json.dumps(results, indent=2))
