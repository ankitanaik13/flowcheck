"""Download once, preserve original records, assign stable source-row identities."""

import hashlib
import json
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pipelinemedic.config import SOURCE_URL  # noqa: E402


def main():
    raw = ROOT / "data/raw"
    out = ROOT / "data/processed"
    raw.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    archive = raw / "online-retail.zip"
    if not archive.exists():
        urlretrieve(SOURCE_URL, archive)
    expected_hash = "f5385cbb54bbebf7196389109c6b0621faab0c304e3702548165e71c84aede8b"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected_hash:
        raise ValueError(
            "Source archive checksum differs from the pinned dataset; review it before ingestion"
        )
    with zipfile.ZipFile(archive) as z:
        with z.open("Online Retail.xlsx") as f:
            frame = pd.read_excel(f, dtype={"InvoiceNo": str, "StockCode": str, "CustomerID": str})
    frame = frame.rename(
        columns={
            "InvoiceNo": "invoice_no",
            "StockCode": "stock_code",
            "Description": "description",
            "Quantity": "quantity",
            "InvoiceDate": "invoice_date",
            "UnitPrice": "unit_price",
            "CustomerID": "customer_id",
            "Country": "country",
        }
    )
    frame.insert(0, "source_row_id", range(1, len(frame) + 1))
    frame["batch_date"] = frame.invoice_date.dt.strftime("%Y-%m-%d")
    path = out / "retail.parquet"
    with duckdb.connect() as con:
        con.register("frame", frame)
        con.execute("COPY frame TO ? (FORMAT PARQUET, COMPRESSION ZSTD)", [str(path)])
    manifest = {
        "name": "UCI Online Retail",
        "citation": "Chen, D. (2015). Online Retail. UCI Machine Learning Repository. doi:10.24432/C5BW33",
        "license": "CC BY 4.0",
        "source_url": SOURCE_URL,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "parquet_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "rows": len(frame),
        "columns": list(frame.columns),
        "start": str(frame.invoice_date.min()),
        "end": str(frame.invoice_date.max()),
        "countries": int(frame.country.nunique()),
        "invoices": int(frame.invoice_no.nunique()),
        "null_customer_ids": int(frame.customer_id.isna().sum()),
        "negative_quantities": int((frame.quantity < 0).sum()),
        "note": "All source rows retained. source_row_id is positional provenance, not a business transaction key. Customer nulls and returns are valid source characteristics.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
