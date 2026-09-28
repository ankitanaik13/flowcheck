"""Executable fault laboratory. Ground truth stays outside the investigator's tools."""

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache

import duckdb
import numpy as np
import pandas as pd

from .config import DATA

SCENARIOS = {
    "clean": ("Healthy batch", "Untouched source data; no repair should be made."),
    "duplicate_ingestion": ("Retry duplication", "A retried ingestion appends some source rows twice."),
    "missing_partition": ("Incomplete delivery", "An ingestion job silently drops part of a daily batch."),
    "null_country": ("Field corruption", "An ingestion mapping replaces some countries with NULL."),
    "unit_scale": (
        "Price unit mismatch",
        "A parser converts a subset of GBP prices to pence without normalization.",
    ),
    "join_fanout": ("Join fan-out", "A product dimension gains duplicate keys, multiplying downstream rows."),
    "wrong_filter": (
        "Silent SQL regression",
        "A transformation unintentionally excludes valid transactions.",
    ),
    "schema_rename": ("Schema change", "The source adapter renames a required column."),
    "genuine_shift": (
        "Genuine business change",
        "Both source and ingestion contain higher quantities; do not repair the data.",
    ),
    "compound": ("Compound incident", "An ingestion retry and duplicate dimension keys occur together."),
}
REQUIRED = {
    "source_row_id",
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "unit_price",
    "customer_id",
    "country",
    "batch_date",
}
BASE_SQL = """SELECT r.source_row_id, r.invoice_no, r.stock_code, r.invoice_date,
       r.quantity, r.unit_price, r.customer_id, r.country,
       d.product_description,
       CAST(ROUND(r.quantity * r.unit_price, 2) AS DECIMAL(18,2)) AS revenue
FROM raw_batch r
LEFT JOIN dim_products d ON r.stock_code = d.stock_code"""
LINEAGE = [
    {"id": "landing", "label": "Immutable landing", "kind": "source"},
    {"id": "raw_batch", "label": "Ingestion adapter", "kind": "ingest"},
    {"id": "dim_products", "label": "Product dimension", "kind": "dimension"},
    {"id": "fact_sales", "label": "Sales facts", "kind": "transform"},
    {"id": "daily_metrics", "label": "Daily metrics", "kind": "mart"},
]


@lru_cache(maxsize=1)
def dataset():
    path = DATA / "retail.parquet"
    if not path.exists():
        raise FileNotFoundError("Dataset is not prepared. Run python scripts/prepare_data.py.")
    with duckdb.connect() as con:
        return con.execute("SELECT * FROM read_parquet(?)", [str(path)]).df()


def batch_dates():
    return sorted(dataset().batch_date.unique().tolist())


def fingerprint(frame):
    """Order independent, multiplicity preserving digest of all output fields."""
    if frame is None:
        return None
    normalized = frame.sort_values(list(frame.columns), na_position="first").reset_index(drop=True)
    return hashlib.sha256(normalized.to_json(orient="split", date_format="iso").encode()).hexdigest()


def summarize(frame):
    if frame is None:
        return {"rows": 0, "revenue": 0, "unique_ids": 0}
    revenue = (
        frame.revenue.sum() if "revenue" in frame else (frame.quantity * frame.unit_price).round(2).sum()
    )
    return {
        "rows": len(frame),
        "revenue": round(float(revenue), 2),
        "unique_ids": int(frame.source_row_id.nunique()),
    }


@dataclass
class Lab:
    landing: pd.DataFrame
    raw: pd.DataFrame
    dimension: pd.DataFrame
    sql: str = BASE_SQL

    def execute(self):
        with duckdb.connect(config={"threads": "1", "memory_limit": "256MB"}) as con:
            con.register("raw_batch", self.raw)
            con.register("dim_products", self.dimension)
            return con.execute(self.sql).df()

    def copy(self):
        return Lab(
            self.landing.copy(deep=True), self.raw.copy(deep=True), self.dimension.copy(deep=True), self.sql
        )

    def source_manifest(self):
        return {
            "rows": len(self.landing),
            "schema": sorted(self.landing.columns),
            "batch_date": str(self.landing.batch_date.iloc[0]),
        }


def make_lab(date: str, scenario: str, seed: int = 42, severity: float = 0.3):
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario")
    source = dataset().loc[lambda d: d.batch_date == date].copy().reset_index(drop=True)
    if source.empty:
        raise ValueError("No records for this date")
    rng = np.random.default_rng(seed)
    n = max(1, int(len(source) * severity))
    selected = rng.choice(len(source), n, replace=False)
    if scenario == "genuine_shift":
        source.loc[selected, "quantity"] *= 4
    dimension = (
        source[["stock_code", "description"]]
        .drop_duplicates("stock_code")
        .rename(columns={"description": "product_description"})
        .reset_index(drop=True)
    )
    lab = Lab(source.copy(deep=True), source.copy(deep=True), dimension)
    if scenario in {"duplicate_ingestion", "compound"}:
        lab.raw = pd.concat([lab.raw, lab.raw.iloc[selected]], ignore_index=True)
    if scenario == "missing_partition":
        lab.raw = lab.raw.drop(index=selected).reset_index(drop=True)
    if scenario == "null_country":
        lab.raw.loc[selected, "country"] = None
    if scenario == "unit_scale":
        lab.raw.loc[selected, "unit_price"] *= 100
    if scenario in {"join_fanout", "compound"}:
        duplicates = lab.dimension.sample(frac=max(0.05, severity), random_state=seed)
        lab.dimension = pd.concat([lab.dimension, duplicates], ignore_index=True)
    if scenario == "wrong_filter":
        lab.sql += "\nWHERE r.quantity > " + str(1 + seed % 5)
    if scenario == "schema_rename":
        lab.raw = lab.raw.rename(columns={"unit_price": "price_gbp"})
    return lab


def reference_output(lab):
    """Evaluator-only oracle. Never exposed as an investigation tool."""
    dimension = (
        lab.landing[["stock_code", "description"]]
        .drop_duplicates("stock_code")
        .rename(columns={"description": "product_description"})
    )
    return Lab(lab.landing.copy(), lab.landing.copy(), dimension).execute()


REPAIRS = {
    "deduplicate_ingestion": {
        "label": "Deduplicate retry records by source-row identity",
        "sql": "SELECT * FROM raw_batch QUALIFY ROW_NUMBER() OVER (PARTITION BY source_row_id ORDER BY source_row_id) = 1",
        "reason": "Preserves distinct source rows, including legitimate identical business transactions.",
    },
    "replay_partition": {
        "label": "Replay the immutable landing batch",
        "sql": "REPLAY verified landing partition INTO raw_batch",
        "reason": "Restores the affected partition from the immutable delivery; never imputes missing transactions.",
    },
    "deduplicate_dimension": {
        "label": "Remove exact repeated dimension records",
        "sql": "SELECT DISTINCT stock_code, product_description FROM dim_products",
        "reason": "Only identical duplicates are removed. Conflicting values require human investigation.",
    },
    "restore_transform": {
        "label": "Restore the versioned transformation contract",
        "sql": BASE_SQL,
        "reason": "Restores the approved row-preserving transformation, including returns.",
    },
}


def apply_repair(lab, action):
    """Allowlisted operations only. Called on an isolated copy, never the source dataset."""
    if action == "deduplicate_ingestion":
        conflicting = lab.raw.groupby("source_row_id").nunique(dropna=False)
        if (conflicting > 1).any().any():
            raise ValueError("Conflicting repeated source IDs require manual review")
        lab.raw = lab.raw.drop_duplicates("source_row_id").reset_index(drop=True)
    elif action == "replay_partition":
        lab.raw = lab.landing.copy(deep=True)
    elif action == "deduplicate_dimension":
        distinct = lab.dimension.drop_duplicates()
        if distinct.stock_code.duplicated().any():
            raise ValueError("Conflicting product descriptions: cannot pick an arbitrary record")
        lab.dimension = distinct.reset_index(drop=True)
    elif action == "restore_transform":
        lab.sql = BASE_SQL
    else:
        raise ValueError("Repair is not allowlisted")


def save_lab(lab, directory):
    directory.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        for name, frame in [("landing", lab.landing), ("raw", lab.raw), ("dimension", lab.dimension)]:
            con.register("export_frame", frame)
            con.execute("COPY export_frame TO ? (FORMAT PARQUET)", [str(directory / f"{name}.parquet")])
    (directory / "transform.sql").write_text(lab.sql)


def load_lab(directory):
    with duckdb.connect() as con:
        tables = [
            con.execute("SELECT * FROM read_parquet(?)", [str(directory / f"{n}.parquet")]).df()
            for n in ["landing", "raw", "dimension"]
        ]
    return Lab(*tables, (directory / "transform.sql").read_text())


def manifest():
    return json.loads((DATA / "manifest.json").read_text())
