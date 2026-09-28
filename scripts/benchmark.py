"""Held-out-date benchmark. Labels exist here, never in the agent context."""

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pipelinemedic.pipeline import SCENARIOS, batch_dates, make_lab
from pipelinemedic.service import evaluate

EXPECTED = {
    "duplicate_ingestion": {"ingestion_replay"},
    "missing_partition": {"incomplete_delivery"},
    "null_country": {"field_mapping"},
    "unit_scale": {"unit_conversion"},
    "join_fanout": {"dimension_keys"},
    "wrong_filter": {"transform_regression"},
    "schema_rename": {"schema_contract"},
    "compound": {"ingestion_replay", "dimension_keys"},
}


def metrics(rows, key):
    tp = sum(r[key] and r["positive"] for r in rows)
    fp = sum(r[key] and not r["positive"] for r in rows)
    fn = sum(not r[key] and r["positive"] for r in rows)
    precision, recall = tp / max(1, tp + fp), tp / max(1, tp + fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / max(1e-9, precision + recall),
    }


def run(mode="offline", count=12):
    dates = [d for d in batch_dates() if "2011-09-01" <= d <= "2011-11-30"]
    # Uniformly spaced unseen batches; scenario random seeds not used in policy development.
    selected = [dates[int(i * (len(dates) - 1) / (count - 1))] for i in range(count)]
    rows = []
    for i, day in enumerate(selected):
        for scenario in SCENARIOS:
            seed = 1009 + i * 97
            severity = [0.12, 0.37, 0.63][i % 3]
            result, _ = evaluate(make_lab(day, scenario, seed, severity), mode)
            roots = set(result["investigation"]["diagnosis"]["roots"])
            positive = scenario in EXPECTED
            correct = (
                roots == EXPECTED[scenario]
                if positive
                else roots <= {"healthy", "source_shift"} and bool(roots)
            )
            stat = result["alert"]["statistical"]
            rows.append(
                {
                    "date": day,
                    "scenario": scenario,
                    "seed": seed,
                    "severity": severity,
                    "positive": positive,
                    "correct": correct,
                    "proposed": bool(result["investigation"]["diagnosis"]["repairs"]),
                    "restored": result["verification"]["passed"],
                    "contracts": result["alert"]["failed_checks"] > 0,
                    "isolation_forest": stat.get("alert", False),
                    "robust_mad": stat.get("robust_alert", False),
                    "hybrid": result["alert"]["failed_checks"] > 0 or stat.get("alert", False),
                    "elapsed_ms": result["elapsed_ms"],
                    "roots": sorted(roots),
                }
            )
        print(f"{i + 1}/{count} dates evaluated", flush=True)
    positives = [r for r in rows if r["positive"]]
    report = {
        "available": True,
        "created": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "disclosure": "Controlled benchmark on real UCI source batches. Offline mode uses a deterministic LangGraph evidence policy, not an LLM. Known fault families; held-out dates, seeds, and severities. Source contracts are unusually strong in this laboratory.",
        "total_cases": len(rows),
        "fault_cases": len(positives),
        "root_accuracy": sum(r["correct"] for r in rows) / len(rows),
        "repair_success": sum(r["restored"] for r in positives) / len(positives),
        "unnecessary_repairs": sum(r["proposed"] for r in rows if not r["positive"]),
        "median_latency_ms": statistics.median(r["elapsed_ms"] for r in rows),
        "detectors": [
            {"name": title, **metrics(rows, key)}
            for title, key in [
                ("Explicit source + transformation contracts", "contracts"),
                ("Isolation Forest novelty", "isolation_forest"),
                ("Robust median absolute deviation", "robust_mad"),
                ("Contracts + Isolation Forest", "hybrid"),
            ]
        ],
        "by_scenario": [
            {
                "scenario": s,
                "cases": sum(r["scenario"] == s for r in rows),
                "correct": sum(r["correct"] for r in rows if r["scenario"] == s),
                "restored": sum(r["restored"] for r in rows if r["scenario"] == s),
                "proposed": sum(r["proposed"] for r in rows if r["scenario"] == s),
            }
            for s in SCENARIOS
        ],
        "limitations": "Known fault families and a trusted immutable source make this a bounded repair benchmark. Distribution anomalies are not corruption labels. No claim of unseen-fault generalization, real production MTTR reduction, or superiority of an LLM is supported.",
        "cases": rows,
    }
    path = ROOT / "artifacts" / ("benchmark.json" if mode == "offline" else "benchmark-ollama.json")
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k not in {"cases", "by_scenario"}}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["offline", "ollama"], default="offline")
    parser.add_argument("--dates", type=int, default=12)
    args = parser.parse_args()
    if not 2 <= args.dates <= 70:
        parser.error("--dates must be between 2 and 70")
    run(args.mode, args.dates)
