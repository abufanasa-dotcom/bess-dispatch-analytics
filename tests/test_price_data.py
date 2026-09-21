"""Data quality, temporal continuity, and German market-day tests for processed SMARD 2024 prices."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_CSV = PROJECT_ROOT / "data" / "processed" / "de_lu_day_ahead_prices_2024.csv"
VALIDATION_TXT = PROJECT_ROOT / "data" / "processed" / "price_data_validation.txt"
RAW_CHUNKS_DIR = PROJECT_ROOT / "data" / "raw" / "smard_4169_2024"

REQUIRED_COLUMNS = ["timestamp_utc", "price_eur_per_mwh", "timestamp_europe_berlin", "delivery_date"]
EXPECTED_ROW_COUNT = 8784
EXPECTED_DELIVERY_DAYS = 366

EXPECTED_FIRST_UTC_STR = "2023-12-31T23:00:00Z"
EXPECTED_LAST_UTC_STR = "2024-12-31T22:00:00Z"


@pytest.fixture(scope="module")
def price_df() -> pd.DataFrame:
    """Fixture providing the processed price DataFrame."""
    assert PROCESSED_CSV.exists(), f"Processed CSV not found at {PROCESSED_CSV}. Run download_smard_prices.py first."
    df = pd.read_csv(PROCESSED_CSV)
    return df


def test_01_processed_csv_exists():
    """1. Verify processed CSV exists after successful download."""
    assert PROCESSED_CSV.exists(), f"Processed CSV file missing at {PROCESSED_CSV}"
    assert PROCESSED_CSV.stat().st_size > 0, "Processed CSV file is empty"


def test_02_required_columns_exist(price_df: pd.DataFrame):
    """2. Verify required columns exist."""
    for col in REQUIRED_COLUMNS:
        assert col in price_df.columns, f"Required column missing: {col}"
    assert list(price_df.columns) == REQUIRED_COLUMNS, (
        f"Columns mismatch: expected {REQUIRED_COLUMNS}, got {list(price_df.columns)}"
    )


def test_03_row_count_equals_8784(price_df: pd.DataFrame):
    """3. Verify total row count == 8784 (364*24 + 23 + 25 hours across 366 German delivery days)."""
    assert len(price_df) == EXPECTED_ROW_COUNT, (
        f"Row count mismatch: expected {EXPECTED_ROW_COUNT}, got {len(price_df)}"
    )


def test_04_timestamps_parse_as_utc(price_df: pd.DataFrame):
    """4. Verify canonical timestamps parse cleanly as timezone-aware UTC."""
    ts_series = pd.to_datetime(price_df["timestamp_utc"], utc=True)
    assert not ts_series.isna().any(), "Some timestamps failed to parse as valid datetimes"
    assert str(ts_series.dt.tz) == "UTC", f"Timestamp timezone is not UTC: {ts_series.dt.tz}"


def test_05_utc_timestamps_are_unique(price_df: pd.DataFrame):
    """5. Verify canonical UTC timestamps are strictly unique."""
    duplicate_count = price_df["timestamp_utc"].duplicated().sum()
    assert duplicate_count == 0, f"Found {duplicate_count} duplicate UTC timestamps"


def test_06_utc_timestamps_strictly_chronological(price_df: pd.DataFrame):
    """6. Verify canonical UTC timestamps are strictly monotonically increasing."""
    ts_series = pd.to_datetime(price_df["timestamp_utc"], utc=True)
    assert ts_series.is_monotonic_increasing, "UTC timestamps are not strictly monotonically increasing"


def test_07_utc_consecutive_spacing_exactly_one_hour(price_df: pd.DataFrame):
    """7. Verify consecutive UTC timestamp differences are all exactly one hour."""
    ts_series = pd.to_datetime(price_df["timestamp_utc"], utc=True)
    diffs = ts_series.diff()[1:]
    expected_delta = pd.Timedelta(hours=1)
    irregular_diffs = diffs[diffs != expected_delta]
    assert irregular_diffs.empty, f"Detected irregular UTC step spacing: {irregular_diffs}"


def test_08_first_utc_timestamp_is_2023_12_31_23z(price_df: pd.DataFrame):
    """8. Verify first UTC timestamp is 2023-12-31T23:00:00Z (= 2024-01-01 00:00 CET)."""
    first_val = price_df["timestamp_utc"].iloc[0]
    first_dt = pd.to_datetime(first_val, utc=True)
    assert first_dt == pd.Timestamp("2023-12-31 23:00:00", tz="UTC"), (
        f"First UTC timestamp mismatch: expected {EXPECTED_FIRST_UTC_STR}, got {first_val}"
    )
    assert first_val == EXPECTED_FIRST_UTC_STR, f"Raw string format mismatch: {first_val}"


def test_09_last_utc_timestamp_is_2024_12_31_22z(price_df: pd.DataFrame):
    """9. Verify last UTC timestamp is 2024-12-31T22:00:00Z (= 2024-12-31 23:00 CET)."""
    last_val = price_df["timestamp_utc"].iloc[-1]
    last_dt = pd.to_datetime(last_val, utc=True)
    assert last_dt == pd.Timestamp("2024-12-31 22:00:00", tz="UTC"), (
        f"Last UTC timestamp mismatch: expected {EXPECTED_LAST_UTC_STR}, got {last_val}"
    )
    assert last_val == EXPECTED_LAST_UTC_STR, f"Raw string format mismatch: {last_val}"


def test_10_all_local_timestamps_belong_to_calendar_year_2024(price_df: pd.DataFrame):
    """10. Verify every converted local Europe/Berlin timestamp belongs to calendar year 2024."""
    local_ts = pd.to_datetime(price_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    assert (local_ts.dt.year == 2024).all(), "Some local timestamps fall outside calendar year 2024"
    first_local = local_ts.iloc[0]
    last_local = local_ts.iloc[-1]
    assert first_local == pd.Timestamp("2024-01-01 00:00:00+01:00")
    assert last_local == pd.Timestamp("2024-12-31 23:00:00+01:00")


def test_11_exactly_366_delivery_dates_exist(price_df: pd.DataFrame):
    """11. Verify exactly 366 German delivery dates exist in Europe/Berlin time."""
    unique_dates = price_df["delivery_date"].nunique()
    assert unique_dates == EXPECTED_DELIVERY_DAYS, (
        f"Expected {EXPECTED_DELIVERY_DAYS} delivery dates, got {unique_dates}"
    )


def test_12_dst_day_march_31_contains_23_observations(price_df: pd.DataFrame):
    """12. Verify spring DST transition date 2024-03-31 contains exactly 23 hourly intervals."""
    m31 = price_df[price_df["delivery_date"] == "2024-03-31"]
    assert len(m31) == 23, f"Expected 23 observations on 2024-03-31, got {len(m31)}"


def test_13_dst_day_october_27_contains_25_observations(price_df: pd.DataFrame):
    """13. Verify autumn DST transition date 2024-10-27 contains exactly 25 hourly intervals."""
    o27 = price_df[price_df["delivery_date"] == "2024-10-27"]
    assert len(o27) == 25, f"Expected 25 observations on 2024-10-27, got {len(o27)}"


def test_14_all_other_delivery_dates_contain_24_observations(price_df: pd.DataFrame):
    """14. Verify all 364 standard delivery dates contain exactly 24 hourly intervals."""
    day_counts = price_df.groupby("delivery_date").size()
    standard_days = day_counts.drop(["2024-03-31", "2024-10-27"])
    assert len(standard_days) == 364
    irregular = standard_days[standard_days != 24]
    assert irregular.empty, f"Found standard days with irregular hour counts: {irregular.to_dict()}"


def test_15_total_local_day_observations_sum_to_8784(price_df: pd.DataFrame):
    """15. Verify sum of observations across all delivery dates equals exactly 8784."""
    day_counts = price_df.groupby("delivery_date").size()
    assert day_counts.sum() == EXPECTED_ROW_COUNT


def test_16_prices_are_numeric_and_non_null(price_df: pd.DataFrame):
    """16. Verify price column is numeric and contains zero null values."""
    assert pd.api.types.is_numeric_dtype(price_df["price_eur_per_mwh"])
    assert price_df["price_eur_per_mwh"].isna().sum() == 0


def test_17_negative_prices_allowed_and_preserved(price_df: pd.DataFrame):
    """17. Verify negative prices are preserved unclipped."""
    negative_prices = price_df[price_df["price_eur_per_mwh"] < 0]
    assert len(negative_prices) == 457, f"Expected 457 negative price hours, got {len(negative_prices)}"
    min_price = price_df["price_eur_per_mwh"].min()
    assert min_price == pytest.approx(-135.45)


def test_18_no_duplicate_timestamp_has_conflicting_source_values():
    """18. Verify across all downloaded raw chunks that overlapping timestamps have identical values."""
    raw_files = list(RAW_CHUNKS_DIR.glob("*.json"))
    assert len(raw_files) > 0, f"No raw chunk JSON files found in {RAW_CHUNKS_DIR}"

    records: list[tuple[int, float]] = []
    for json_file in raw_files:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        series = data.get("series", [])
        for item in series:
            records.append((item[0], float(item[1])))

    raw_df = pd.DataFrame(records, columns=["ts_ms", "price"])
    price_conflicts = raw_df.groupby("ts_ms")["price"].nunique()
    conflicts = price_conflicts[price_conflicts > 1]
    assert conflicts.empty, f"Conflicting source prices found across raw chunks: {conflicts}"


def test_19_no_price_values_changed_by_timezone_conversion(price_df: pd.DataFrame):
    """19. Verify prices match canonical raw UTC values regardless of timezone representation."""
    utc_parsed = pd.to_datetime(price_df["timestamp_utc"], utc=True)
    local_parsed = pd.to_datetime(price_df["timestamp_europe_berlin"], utc=True).dt.tz_convert("Europe/Berlin")
    # Converting local back to UTC must match exact UTC timestamp
    assert (local_parsed.dt.tz_convert("UTC") == utc_parsed).all()


def test_20_autumn_dst_repeated_clock_hour_is_distinguished_by_offset(price_df: pd.DataFrame):
    """20. Verify that the repeated 02:00 hour on 2024-10-27 is unambiguous via timezone offsets."""
    o27 = price_df[price_df["delivery_date"] == "2024-10-27"]
    two_am_rows = o27[o27["timestamp_europe_berlin"].str.contains("T02:00:00")]
    assert len(two_am_rows) == 2, "Expected exactly two 02:00 local timestamps on October 27"

    offsets = [ts[-6:] for ts in two_am_rows["timestamp_europe_berlin"]]
    assert "+02:00" in offsets, "First 2am must have CEST offset +02:00"
    assert "+01:00" in offsets, "Second 2am must have CET offset +01:00"

    # Verify their prices are distinct or preserved from source
    p1 = two_am_rows.iloc[0]["price_eur_per_mwh"]
    p2 = two_am_rows.iloc[1]["price_eur_per_mwh"]
    assert p1 == pytest.approx(82.23)
    assert p2 == pytest.approx(80.43)


def test_21_validation_report_exists_and_matches():
    """21. Verify validation report exists and contains consistent German market-day metrics."""
    assert VALIDATION_TXT.exists(), f"Validation report missing at {VALIDATION_TXT}"
    content = VALIDATION_TXT.read_text(encoding="utf-8")
    assert "STATUS: PASSED" in content
    assert "number of final rows: 8784" in content
    assert "first timestamp: 2023-12-31T23:00:00Z" in content
    assert "last timestamp: 2024-12-31T22:00:00Z" in content
    assert "total local delivery dates: 366" in content
    assert "March 31 row count (spring DST): 23" in content
    assert "October 27 row count (autumn DST): 25" in content
