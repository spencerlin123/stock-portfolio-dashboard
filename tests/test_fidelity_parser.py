import math
import pandas as pd
import pytest
from tools.fidelity_parser import parse_fidelity_csv, extract_action_type

RAW_BUY = (
    "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
    "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
    '10/19/2023,"YOU BOUGHT TESLA INC COM (TSLA) (Cash)",TSLA,"TESLA INC COM",'
    "Cash,219.04,15,,,,-3285.59,37.54,10/23/2023\n"
)

RAW_SELL = (
    "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
    "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
    '11/30/2023,"YOU SOLD GAMESTOP CORPORATION COM USD0.001 CL... (GME) (Cash)",'
    'GME,"GAMESTOP CORPORATION COM USD0.001 CLASS",Cash,14.91,-100,,0.02,,1491,1544.16,12/04/2023\n'
)

RAW_DIVIDEND = (
    "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
    "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
    '12/27/2024,"DIVIDEND RECEIVED META PLATFORMS INC CLASS A COMMON STOCK (META) (Cash)",'
    'META,"META PLATFORMS INC CLASS A COMMON STOCK",Cash,,0.000,,,,17.38,17.88,\n'
)

RAW_TRANSFER = (
    "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
    "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
    '10/20/2023,"Electronic Funds Transfer Received (Cash)", ,"No Description",Cash,,0.000,,,,3519,3556.54,\n'
)

RAW_WITH_BOM = "\ufeff\n" + RAW_BUY


def test_extract_action_type_buy():
    assert extract_action_type("YOU BOUGHT TESLA INC COM (TSLA) (Cash)") == "BUY"


def test_extract_action_type_sell():
    assert extract_action_type("YOU SOLD GAMESTOP CORPORATION (GME) (Cash)") == "SELL"


def test_extract_action_type_dividend():
    assert extract_action_type("DIVIDEND RECEIVED META PLATFORMS (META) (Cash)") == "DIVIDEND"


def test_extract_action_type_deposit():
    assert extract_action_type("Electronic Funds Transfer Received (Cash)") == "DEPOSIT"


def test_extract_action_type_unknown():
    assert extract_action_type("FOREIGN TAX WITHHELD (Cash)") is None


def test_parse_buy_row(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(RAW_BUY)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ticker"] == "TSLA"
    assert row["action"] == "BUY"
    assert row["shares"] == 15.0
    assert row["price"] == 219.04
    assert row["amount"] == -3285.59
    assert str(row["date"]) == "2023-10-19"


def test_parse_sell_row(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(RAW_SELL)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ticker"] == "GME"
    assert row["action"] == "SELL"
    assert row["shares"] == -100.0


def test_parse_dividend_row(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(RAW_DIVIDEND)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["action"] == "DIVIDEND"
    assert row["amount"] == 17.38


def test_transfer_rows_parsed_as_deposit(tmp_path):
    """Electronic Funds Transfer rows should be parsed as DEPOSIT with ticker=CASH."""
    f = tmp_path / "test.csv"
    f.write_text(RAW_TRANSFER)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["action"] == "DEPOSIT"
    assert row["ticker"] == "CASH"
    assert row["amount"] == 3519.0


def test_bom_and_blank_line_handled(tmp_path):
    f = tmp_path / "test.csv"
    f.write_text(RAW_WITH_BOM)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "TSLA"
    assert df.iloc[0]["action"] == "BUY"


def test_blank_quantity_and_price_on_dividend(tmp_path):
    raw = (
        "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
        "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
        '12/27/2024,"DIVIDEND RECEIVED META PLATFORMS INC CLASS A COMMON STOCK (META) (Cash)",'
        'META,"META PLATFORMS INC CLASS A COMMON STOCK",Cash,,,,,,17.38,17.88,\n'
    )
    f = tmp_path / "test.csv"
    f.write_text(raw)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    row = df.iloc[0]
    assert not math.isnan(row["shares"])
    assert row["shares"] == 0.0
    assert row["amount"] == 17.38


def test_reinvestment_action(tmp_path):
    raw = (
        "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
        "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
        '01/15/2024,"REINVESTMENT SOME FUND (VTI) (Cash)",'
        'VTI,"VANGUARD TOTAL STOCK ETF",Cash,200.00,0.5,,,,-100.00,500.00,01/17/2024\n'
    )
    f = tmp_path / "test.csv"
    f.write_text(raw)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 1
    assert df.iloc[0]["action"] == "REINVESTMENT"


def test_mixed_action_types_multi_row(tmp_path):
    raw = (
        "Run Date,Action,Symbol,Description,Type,Price ($),Quantity,"
        "Commission ($),Fees ($),Accrued Interest ($),Amount ($),Cash Balance ($),Settlement Date\n"
        '10/19/2023,"YOU BOUGHT TESLA INC COM (TSLA) (Cash)",TSLA,"TESLA INC COM",Cash,219.04,15,,,,-3285.59,37.54,10/23/2023\n'
        '10/20/2023,"Electronic Funds Transfer Received (Cash)", ,"No Description",Cash,,0.000,,,,3519,3556.54,\n'
        '12/27/2024,"DIVIDEND RECEIVED META PLATFORMS INC CLASS A COMMON STOCK (META) (Cash)",META,"META PLATFORMS INC CLASS A COMMON STOCK",Cash,,0.000,,,,17.38,17.88,\n'
    )
    f = tmp_path / "test.csv"
    f.write_text(raw)
    df = parse_fidelity_csv(str(f))
    assert len(df) == 3
    assert set(df["action"].tolist()) == {"BUY", "DIVIDEND", "DEPOSIT"}
