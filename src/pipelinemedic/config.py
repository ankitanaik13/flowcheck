import os
from pathlib import Path

ROOT = Path(os.environ.get("PIPELINEMEDIC_HOME", Path(__file__).resolve().parents[2])).resolve()
DATA = ROOT / "data" / "processed"
ARTIFACTS = ROOT / "artifacts"
MAX_STEPS = 12
SOURCE_URL = "https://archive.ics.uci.edu/static/public/352/online+retail.zip"
DATASET_URL = "https://archive.ics.uci.edu/dataset/352/online+retail"
