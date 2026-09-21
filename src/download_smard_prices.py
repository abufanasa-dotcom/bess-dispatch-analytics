"""SMARD Day-Ahead Electricity Market Price Data Ingestion and Validation.

Acquires and validates hourly wholesale electricity prices for the German/Luxembourg
(DE-LU) market bidding zone (Filter 4169, Region DE) aligned with German market
delivery days in calendar year 2024 (Europe/Berlin).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import requests

SMARD_BASE_URL = "https://www.smard.de/app/chart_data"
FILTER_ID = "4169"
REGION = "DE"
RESOLUTION = "hour"

INDEX_URL = f"{SMARD_BASE_URL}/{FILTER_ID}/{REGION}/index_{RESOLUTION}.json"
CHUNK_URL_PATTERN = f"{SMARD_BASE_URL}/{FILTER_ID}/{REGION}/{FILTER_ID}_{REGION}_{RESOLUTION}_{{timestamp}}.json"

# German market year 2024: 2024-01-01 00:00 CET to 2025-01-01 00:00 CET
START_UTC = pd.Timestamp("2023-12-31 23:00:00", tz="UTC")
END_UTC = pd.Timestamp("2024-12-31 23:00:00", tz="UTC")
EXPECTED_ROW_COUNT = 8784  # 366 German delivery days (364*24 + 23 + 25)
EXPECTED_DELIVERY_DAYS = 366


def get_smard_session() -> requests.Session:
    """Create a configured requests session with a standard User-Agent."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 BESS-Dispatch-Analytics/1.0"
            ),
            "Accept": "application/json",
        }
    )
    return session


def fetch_hourly_index(session: requests.Session, timeout: float = 30.0) -> list[int]:
    """Retrieve all available chunk start timestamps from the SMARD index endpoint.

    Returns:
        Sorted list of integer millisecond timestamps.
    """
    response = session.get(INDEX_URL, timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict) and "timestamps" in payload:
        timestamps = payload["timestamps"]
    elif isinstance(payload, list):
        timestamps = payload
    else:
        raise ValueError(f"Unexpected SMARD index structure: {type(payload)}")

    return sorted(int(ts) for ts in timestamps)


def select_chunks_for_interval(
    all_chunk_timestamps: list[int],
    start_utc: pd.Timestamp = START_UTC,
    end_utc: pd.Timestamp = END_UTC,
) -> list[int]:
    """Identify chunk timestamps required to cover [start_utc, end_utc).

    Includes neighboring boundary chunks to ensure no boundary hours are missed.
    """
    if not all_chunk_timestamps:
        raise ValueError("No chunk timestamps provided by SMARD index.")

    chunk_dts = pd.to_datetime(all_chunk_timestamps, unit="ms", utc=True)

    # Locate chunk before or at start_utc
    idx_start = max(0, int(chunk_dts.searchsorted(start_utc, side="right")) - 1)
    # Locate chunk covering or immediately after end_utc
    idx_end = min(len(chunk_dts) - 1, int(chunk_dts.searchsorted(end_utc, side="right")))

    # Include neighboring buffer chunks on both sides
    idx_start_buffered = max(0, idx_start - 1)
    idx_end_buffered = min(len(chunk_dts) - 1, idx_end + 1)

    selected = all_chunk_timestamps[idx_start_buffered : idx_end_buffered + 1]
    return selected


def download_chunk(
    session: requests.Session,
    chunk_ts: int,
    raw_dir: Path,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Download a single SMARD timeseries chunk or load from local cache if present."""
    raw_file = raw_dir / f"{FILTER_ID}_{REGION}_{RESOLUTION}_{chunk_ts}.json"
    if raw_file.exists():
        with open(raw_file, "r", encoding="utf-8") as f:
            return json.load(f)

    url = CHUNK_URL_PATTERN.format(timestamp=chunk_ts)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()

    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(data, f)

    return data


def process_and_validate_series(
    chunk_payloads: list[dict[str, Any]],
    start_utc: pd.Timestamp = START_UTC,
    end_utc: pd.Timestamp = END_UTC,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Extract, concatenate, deduplicate, filter, and validate SMARD price series.

    Enforces all validation rules from PROJECT_SPEC.md for German delivery days.
    """
    all_observations: list[list[Any]] = []
    for payload in chunk_payloads:
        series = payload.get("series", [])
        all_observations.extend(series)

    if not all_observations:
        raise ValueError("No price series observations retrieved across chunks.")

    # Build initial dataframe
    df_raw = pd.DataFrame(all_observations, columns=["timestamp_ms", "price_eur_per_mwh"])
    df_raw["timestamp_utc"] = pd.to_datetime(df_raw["timestamp_ms"], unit="ms", utc=True)
    df_raw["price_eur_per_mwh"] = pd.to_numeric(df_raw["price_eur_per_mwh"], errors="coerce")

    # Step 7: Check for duplicate timestamps with conflicting price values
    price_conflicts = df_raw.groupby("timestamp_utc")["price_eur_per_mwh"].nunique()
    conflicting = price_conflicts[price_conflicts > 1]
    if not conflicting.empty:
        raise ValueError(
            f"Validation Failure: Conflicting price values found for duplicate timestamps: "
            f"{conflicting.index.tolist()[:10]}"
        )

    # Track duplicate count
    duplicate_count = int(df_raw.duplicated(subset=["timestamp_utc"]).sum())

    # Step 7 & 8: Deduplicate and sort chronologically
    df_dedup = df_raw.drop_duplicates(subset=["timestamp_utc"]).sort_values("timestamp_utc").reset_index(drop=True)

    # Step 9: Filter strictly to German market year [start_utc, end_utc)
    mask = (df_dedup["timestamp_utc"] >= start_utc) & (df_dedup["timestamp_utc"] < end_utc)
    df_2024 = df_dedup.loc[mask, ["timestamp_utc", "price_eur_per_mwh"]].copy().reset_index(drop=True)

    # Validation Checks
    final_rows = len(df_2024)
    if final_rows != EXPECTED_ROW_COUNT:
        raise ValueError(
            f"Validation Failure: Expected exactly {EXPECTED_ROW_COUNT} rows for German 2024 delivery year, got {final_rows}."
        )

    first_ts = df_2024["timestamp_utc"].iloc[0]
    expected_first_ts = start_utc
    if first_ts != expected_first_ts:
        raise ValueError(f"Validation Failure: Expected first UTC timestamp {expected_first_ts}, got {first_ts}.")

    last_ts = df_2024["timestamp_utc"].iloc[-1]
    expected_last_ts = end_utc - pd.Timedelta(hours=1)
    if last_ts != expected_last_ts:
        raise ValueError(f"Validation Failure: Expected last UTC timestamp {expected_last_ts}, got {last_ts}.")

    # Step-spacing check: must be strictly 1-hour spacing in UTC
    diffs = df_2024["timestamp_utc"].diff()[1:]
    missing_intervals = int((diffs != pd.Timedelta(hours=1)).sum())
    if missing_intervals > 0:
        gap_indices = df_2024[1:][diffs != pd.Timedelta(hours=1)].index.tolist()
        raise ValueError(f"Validation Failure: Detected {missing_intervals} gaps/irregular intervals at indices {gap_indices}.")

    # Null / Non-numeric price checks
    null_count = int(df_2024["price_eur_per_mwh"].isna().sum())
    if null_count > 0:
        raise ValueError(f"Validation Failure: Dataset contains {null_count} null price values.")

    # Market delivery days and DST validation
    df_2024["timestamp_europe_berlin"] = df_2024["timestamp_utc"].dt.tz_convert("Europe/Berlin")
    df_2024["delivery_date"] = df_2024["timestamp_europe_berlin"].dt.date.astype(str)

    # Verify all local timestamps fall strictly in calendar year 2024
    if not (df_2024["timestamp_europe_berlin"].dt.year == 2024).all():
        raise ValueError("Validation Failure: Some local timestamps fall outside calendar year 2024.")

    day_counts = df_2024.groupby("delivery_date").size()
    if len(day_counts) != EXPECTED_DELIVERY_DAYS:
        raise ValueError(
            f"Validation Failure: Expected {EXPECTED_DELIVERY_DAYS} local delivery dates, got {len(day_counts)}."
        )

    march_31_count = int(day_counts.get("2024-03-31", 0))
    if march_31_count != 23:
        raise ValueError(f"Validation Failure: Expected 23 hours on 2024-03-31 (spring DST), got {march_31_count}.")

    oct_27_count = int(day_counts.get("2024-10-27", 0))
    if oct_27_count != 25:
        raise ValueError(f"Validation Failure: Expected 25 hours on 2024-10-27 (autumn DST), got {oct_27_count}.")

    other_days = day_counts.drop(["2024-03-31", "2024-10-27"])
    irregular_days = other_days[other_days != 24]
    if not irregular_days.empty:
        raise ValueError(f"Validation Failure: Standard delivery days with != 24 hours: {irregular_days.to_dict()}")

    if day_counts.sum() != EXPECTED_ROW_COUNT:
        raise ValueError(f"Validation Failure: Total delivery-day sum ({day_counts.sum()}) != {EXPECTED_ROW_COUNT}.")

    # Step 10: Negative prices preserved exactly
    neg_count = int((df_2024["price_eur_per_mwh"] < 0).sum())
    zero_count = int((df_2024["price_eur_per_mwh"] == 0).sum())

    min_price = float(df_2024["price_eur_per_mwh"].min())
    max_price = float(df_2024["price_eur_per_mwh"].max())
    mean_price = float(df_2024["price_eur_per_mwh"].mean())
    median_price = float(df_2024["price_eur_per_mwh"].median())
    std_price = float(df_2024["price_eur_per_mwh"].std())

    first_local = df_2024["timestamp_europe_berlin"].iloc[0].isoformat()
    last_local = df_2024["timestamp_europe_berlin"].iloc[-1].isoformat()

    metrics: dict[str, Any] = {
        "source": "SMARD / Bundesnetzagentur",
        "filter": FILTER_ID,
        "region": REGION,
        "resolution": RESOLUTION,
        "requested_analysis_period": (
            "2024-01-01 00:00:00 Europe/Berlin inclusive to 2025-01-01 00:00:00 Europe/Berlin exclusive "
            f"({start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')} to {end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')} UTC)"
        ),
        "number_of_final_rows": final_rows,
        "first_timestamp_utc": first_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_timestamp_utc": last_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "first_timestamp_local": first_local,
        "last_timestamp_local": last_local,
        "total_delivery_dates": len(day_counts),
        "march_31_row_count": march_31_count,
        "october_27_row_count": oct_27_count,
        "standard_24h_delivery_days": len(other_days),
        "duplicate_timestamp_count": duplicate_count,
        "missing_hourly_interval_count": missing_intervals,
        "null_price_count": null_count,
        "non_numeric_price_count": 0,
        "negative_price_hour_count": neg_count,
        "zero_price_hour_count": zero_count,
        "minimum_price": min_price,
        "maximum_price": max_price,
        "mean_price": mean_price,
        "median_price": median_price,
        "standard_deviation": std_price,
        "number_of_downloaded_api_chunks": len(chunk_payloads),
    }

    return df_2024, metrics


def save_processed_csv(df: pd.DataFrame, output_csv: Path) -> None:
    """Save processed dataset to CSV with ISO-8601 UTC and local timezone-aware timestamps."""
    df_out = df.copy()
    df_out["timestamp_utc"] = df_out["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    df_out["timestamp_europe_berlin"] = df_out["timestamp_europe_berlin"].apply(lambda ts: ts.isoformat())
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(
        output_csv,
        index=False,
        columns=["timestamp_utc", "price_eur_per_mwh", "timestamp_europe_berlin", "delivery_date"],
    )


def write_validation_report(metrics: dict[str, Any], output_txt: Path) -> None:
    """Write comprehensive validation report to text file."""
    output_txt.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "=" * 60,
        "SMARD MARKET PRICE DATA VALIDATION REPORT",
        "=" * 60,
        f"source: {metrics['source']}",
        f"filter: {metrics['filter']}",
        f"region: {metrics['region']}",
        f"resolution: {metrics['resolution']}",
        f"requested analysis period: {metrics['requested_analysis_period']}",
        f"number of final rows: {metrics['number_of_final_rows']}",
        f"first timestamp: {metrics['first_timestamp_utc']}",
        f"last timestamp: {metrics['last_timestamp_utc']}",
        f"first local timestamp: {metrics['first_timestamp_local']}",
        f"last local timestamp: {metrics['last_timestamp_local']}",
        f"total local delivery dates: {metrics['total_delivery_dates']}",
        f"March 31 row count (spring DST): {metrics['march_31_row_count']}",
        f"October 27 row count (autumn DST): {metrics['october_27_row_count']}",
        f"standard 24h delivery days: {metrics['standard_24h_delivery_days']}",
        f"duplicate timestamp count: {metrics['duplicate_timestamp_count']}",
        f"missing hourly interval count: {metrics['missing_hourly_interval_count']}",
        f"null price count: {metrics['null_price_count']}",
        f"non-numeric price count: {metrics['non_numeric_price_count']}",
        f"negative-price hour count: {metrics['negative_price_hour_count']}",
        f"zero-price hour count: {metrics['zero_price_hour_count']}",
        f"minimum price: {metrics['minimum_price']:.2f} EUR/MWh",
        f"maximum price: {metrics['maximum_price']:.2f} EUR/MWh",
        f"mean price: {metrics['mean_price']:.4f} EUR/MWh",
        f"median price: {metrics['median_price']:.4f} EUR/MWh",
        f"standard deviation: {metrics['standard_deviation']:.4f} EUR/MWh",
        f"number of downloaded API chunks: {metrics['number_of_downloaded_api_chunks']}",
        "=" * 60,
        "STATUS: PASSED - All German market-day validation rules strictly satisfied.",
        "=" * 60,
    ]
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run_pipeline(project_root: Path | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Execute complete SMARD 2024 day-ahead price download and validation pipeline."""
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent

    raw_dir = project_root / "data" / "raw" / f"smard_{FILTER_ID}_2024"
    processed_dir = project_root / "data" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    output_csv = processed_dir / "de_lu_day_ahead_prices_2024.csv"
    output_report = processed_dir / "price_data_validation.txt"

    session = get_smard_session()

    print("[1/4] Requesting SMARD hourly index...")
    all_chunks = fetch_hourly_index(session)
    print(f"      Retrieved {len(all_chunks)} total chunk timestamps from index.")

    print("[2/4] Selecting chunks covering German market delivery year 2024...")
    needed_chunks = select_chunks_for_interval(all_chunks)
    print(f"      Identified {len(needed_chunks)} chunks to cover interval.")

    print(f"[3/4] Ensuring {len(needed_chunks)} chunks are available in {raw_dir}...")
    chunk_payloads: list[dict[str, Any]] = []
    for i, chunk_ts in enumerate(needed_chunks, start=1):
        payload = download_chunk(session, chunk_ts, raw_dir)
        chunk_payloads.append(payload)
        if i % 10 == 0 or i == len(needed_chunks):
            print(f"      Loaded/Downloaded {i}/{len(needed_chunks)} chunks.")

    print("[4/4] Processing, deduplicating, filtering, and validating German market days...")
    df_2024, metrics = process_and_validate_series(chunk_payloads)

    save_processed_csv(df_2024, output_csv)
    print(f"      Saved processed CSV to {output_csv}")

    write_validation_report(metrics, output_report)
    print(f"      Saved validation report to {output_report}")

    print("\nExtraction & Validation complete!")
    print(f"Rows: {metrics['number_of_final_rows']}")
    print(f"UTC Range: {metrics['first_timestamp_utc']} to {metrics['last_timestamp_utc']}")
    print(f"Local Range: {metrics['first_timestamp_local']} to {metrics['last_timestamp_local']}")
    print(f"Delivery dates: {metrics['total_delivery_dates']} (March 31: {metrics['march_31_row_count']}h, Oct 27: {metrics['october_27_row_count']}h)")
    print(f"Negative-price hours: {metrics['negative_price_hour_count']}")
    print(f"Min: {metrics['minimum_price']:.2f}, Max: {metrics['maximum_price']:.2f}, Mean: {metrics['mean_price']:.2f} EUR/MWh")

    return df_2024, metrics


if __name__ == "__main__":
    run_pipeline()
