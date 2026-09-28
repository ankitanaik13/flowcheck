import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pipelinemedic.agent import ollama_policy, probe_delivery, probe_dimension, probe_transform
from pipelinemedic.detection import observe
from pipelinemedic.pipeline import make_lab

lab = make_lab("2011-10-05", "join_fanout")
state = {
    "alert": observe(lab)[0],
    "evidence": {
        "inspect_delivery": probe_delivery(lab),
        "inspect_dimension": probe_dimension(lab),
        "inspect_transform": probe_transform(lab),
    },
}
print(json.dumps(ollama_policy(state).model_dump(), indent=2))
