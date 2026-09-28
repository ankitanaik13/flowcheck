import pandas as pd
import pytest

from pipelinemedic.pipeline import Lab


@pytest.fixture
def tiny_lab():
    source = pd.DataFrame(
        {
            "source_row_id": [1, 2, 3, 4],
            "invoice_no": ["100", "100", "C101", "102"],
            "stock_code": ["A", "A", "B", "C"],
            "description": ["Item A", "Item A", "Item B", "Item C"],
            "quantity": [2, 2, -1, 3],
            "invoice_date": pd.to_datetime(["2011-10-05"] * 4),
            "unit_price": [2.5, 2.5, 4.0, 0.0],
            "customer_id": ["12", "12", None, None],
            "country": ["UK"] * 4,
            "batch_date": ["2011-10-05"] * 4,
        }
    )
    dimension = (
        source[["stock_code", "description"]]
        .drop_duplicates("stock_code")
        .rename(columns={"description": "product_description"})
    )
    return Lab(source.copy(), source.copy(), dimension.copy())
