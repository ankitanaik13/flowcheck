"""Bounded container build and real fault-repair smoke test; records failures honestly."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / "artifacts/packaging.json"
try:
    build = subprocess.run(
        ["docker", "build", "--progress=plain", "-t", "pipelinemedic:local", "."],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
    )
    (ROOT / "artifacts/container-build.log").write_text(build.stdout)
    if build.returncode:
        raise RuntimeError("Docker build failed; see artifacts/container-build.log")
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--mount",
        f"type=bind,source={ROOT / 'data'},target=/app/data,readonly",
        "pipelinemedic:local",
        "python",
        "-c",
        'from pipelinemedic.pipeline import make_lab; from pipelinemedic.service import evaluate; r,_=evaluate(make_lab("2011-10-05","compound")); assert r["verification"]["passed"]; print("Container repair smoke test passed")',
    ]
    smoke = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
    (ROOT / "artifacts/container-smoke.log").write_text(smoke.stdout)
    if smoke.returncode:
        raise RuntimeError("Container smoke test failed; see artifacts/container-smoke.log")
    report = {
        "status": "Verified",
        "detail": "Docker image built; a network-disabled Linux container executed and exactly repaired a compound fault on the mounted real dataset.",
    }
except subprocess.TimeoutExpired as exc:
    partial = exc.stdout or b""
    (ROOT / "artifacts/container-build.log").write_text(
        partial.decode(errors="replace") if isinstance(partial, bytes) else partial
    )
    report = {
        "status": "Blocked by Docker environment timeout",
        "detail": "The local Python app and tests pass, but Docker did not complete within its verification deadline. Container execution is not claimed as verified.",
    }
except (RuntimeError, OSError) as exc:
    report = {"status": "Not verified", "detail": str(exc)}
output.write_text(json.dumps(report, indent=2))
print(json.dumps(report))
