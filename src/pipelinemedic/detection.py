"""Temporal anomaly scoring and explicit, independently inspectable contracts."""

from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .pipeline import REQUIRED, dataset, summarize

FEATURES = ["rows", "revenue_abs", "mean_price", "mean_abs_quantity", "null_customer_rate", "return_rate"]
TRAIN_END = "2011-07-31"
CALIBRATION_END = "2011-08-31"


def features(frame):
    return {
        "rows": float(len(frame)),
        "revenue_abs": float((frame.quantity * frame.unit_price).abs().sum()),
        "mean_price": float(frame.unit_price.mean()) if len(frame) else 0.0,
        "mean_abs_quantity": float(frame.quantity.abs().mean()) if len(frame) else 0.0,
        "null_customer_rate": float(frame.customer_id.isna().mean()) if len(frame) else 0.0,
        "return_rate": float((frame.quantity < 0).mean()) if len(frame) else 0.0,
    }


@lru_cache(maxsize=1)
def daily_history():
    rows = []
    for date, frame in dataset().groupby("batch_date", sort=True):
        rows.append({"date": date, **features(frame), "revenue": summarize(frame)["revenue"]})
    return pd.DataFrame(rows)


def vector(frame):
    return np.log1p(np.maximum(frame[FEATURES].to_numpy(dtype=float), 0))


@lru_cache(maxsize=1)
def detector():
    history = daily_history()
    train = history[history.date <= TRAIN_END]
    calibration = history[(history.date > TRAIN_END) & (history.date <= CALIBRATION_END)]
    model = IsolationForest(n_estimators=150, random_state=73, contamination="auto", n_jobs=1)
    model.fit(vector(train))
    scores = -model.score_samples(vector(calibration))
    return model, scores, train


def score_batch(raw):
    if not REQUIRED.issubset(raw.columns):
        return {"available": False, "reason": "Required columns missing; schema contract takes precedence."}
    model, calibration, train = detector()
    point = pd.DataFrame([features(raw)])
    novelty = float(-model.score_samples(vector(point))[0])
    # Calibration rank is descriptive: temporal data need not be exchangeable.
    tail = float((1 + np.count_nonzero(calibration >= novelty)) / (1 + len(calibration)))
    med = train[FEATURES].median()
    mad = (train[FEATURES] - med).abs().median().replace(0, 1.0)
    robust = ((point.iloc[0] - med).abs() / (1.4826 * mad)).to_dict()
    return {
        "available": True,
        "novelty_score": round(novelty, 5),
        "calibration_tail_fraction": round(tail, 5),
        "alert": tail <= 0.1,
        "robust_alert": max(robust.values()) > 6,
        "robust_scores": {k: round(float(v), 3) for k, v in robust.items()},
        "features": {k: round(float(v), 4) for k, v in point.iloc[0].items()},
        "train_batches": len(train),
        "calibration_batches": len(calibration),
        "note": "Distribution alert is not proof of corruption. Calibration is descriptive, not a clinical or probabilistic guarantee.",
    }


def checks(lab, output=None, error=None):
    rows = []

    def add(name, passed, observed, expected, node):
        rows.append(
            {"name": name, "passed": bool(passed), "observed": observed, "expected": expected, "node": node}
        )

    missing = sorted(REQUIRED - set(lab.raw.columns))
    add(
        "Required schema",
        not missing,
        ", ".join(missing) or "All columns present",
        "10 canonical columns",
        "raw_batch",
    )
    dup = int(lab.raw.source_row_id.duplicated().sum())
    add("Source-row uniqueness", dup == 0, dup, 0, "raw_batch")
    received = set(lab.raw.source_row_id)
    expected = set(lab.landing.source_row_id)
    add("Delivery completeness", received == expected, len(received), len(expected), "raw_batch")
    if not missing:
        left = lab.raw.drop_duplicates("source_row_id").set_index("source_row_id")
        right = lab.landing.set_index("source_row_id")
        common = left.index.intersection(right.index)
        changed = []
        for col in sorted(REQUIRED - {"source_row_id"}):
            a, b = left.loc[common, col], right.loc[common, col]
            equal = a.eq(b) | (a.isna() & b.isna())
            if not equal.all():
                changed.append(col)
        add(
            "Source value fidelity",
            not changed,
            ", ".join(changed) or "Exact match",
            "Unchanged source values",
            "raw_batch",
        )
    dimdup = int(lab.dimension.stock_code.duplicated().sum())
    add("Dimension key uniqueness", dimdup == 0, dimdup, 0, "dim_products")
    add(
        "Transformation execution",
        error is None,
        "Succeeded" if error is None else "SQL execution failed",
        "Succeeded",
        "fact_sales",
    )
    if output is not None:
        outids = set(output.source_row_id)
        add(
            "Fact row conservation",
            len(output) == len(lab.raw) and outids == received,
            len(output),
            len(lab.raw),
            "fact_sales",
        )
        add(
            "Fact key uniqueness",
            not output.source_row_id.duplicated().any(),
            int(output.source_row_id.duplicated().sum()),
            0,
            "fact_sales",
        )
    return rows


def observe(lab):
    error, output = None, None
    try:
        output = lab.execute()
    except Exception as exc:
        error = str(exc)[:1500]
    contracts = checks(lab, output, error)
    statistical = score_batch(lab.raw)
    return {
        "checks": contracts,
        "statistical": statistical,
        "failed_checks": sum(not c["passed"] for c in contracts),
        "before": summarize(output),
        "execution_error": error,
    }, output
