"""
BLOCK-MANAGEMENT
================
Self-contained prototype for generating railway maintenance block requests,
generating timetable data, and merging compatible departmental requests.

The merge logic combines requests from different departments when they target
the same section on the same date. Departments can work in parallel, so the
joint block duration is the longest individual duration.

Usage:
    python main.py

Outputs:
    block_requests.csv
    timetable.csv
    merged_blocks.csv
    standalone_requests.csv
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEPARTMENTS = ("Engineering", "TRD", "S&T")
SECTIONS = tuple(f"SEC-{i}" for i in range(1, 6))
TRAIN_PRIORITIES = ("Rajdhani", "Express", "Passenger", "Freight")
DURATION_OPTIONS = (1, 2, 3, 4, 6, 8)
DEFAULT_START_DATE = "2026-09-10"

OUTPUT_DIR = Path(".")


# ---------------------------------------------------------------------------
# Data generation - BDMS / COA simulation
# ---------------------------------------------------------------------------


def _base_date(start_date: str) -> datetime:
    """Parse and validate the simulation start date."""
    try:
        return datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(
            f"start_date must use YYYY-MM-DD format; received {start_date!r}"
        ) from exc


def generate_block_requests(
    n: int = 15,
    seed: int | None = None,
    start_date: str = DEFAULT_START_DATE,
) -> pd.DataFrame:
    """Generate simulated BDMS maintenance block requests."""
    if n < 0:
        raise ValueError("n must be >= 0")

    base = _base_date(start_date)
    rng = random.Random(seed)

    rows = [
        {
            "request_id": f"REQ-{i + 1:03}",
            "department": rng.choice(DEPARTMENTS),
            "section_id": rng.choice(SECTIONS),
            "requested_date": (
                base + timedelta(days=rng.randint(0, 6))
            ).strftime("%Y-%m-%d"),
            "duration_hours": rng.choice(DURATION_OPTIONS),
            "safety_flag": rng.choice((0, 0, 0, 1)),
            "days_since_last_maintenance": rng.randint(5, 180),
        }
        for i in range(n)
    ]

    return pd.DataFrame(rows)


def generate_timetable(
    n: int = 40,
    seed: int | None = None,
    start_date: str = DEFAULT_START_DATE,
) -> pd.DataFrame:
    """Generate simulated COA timetable entries."""
    if n < 0:
        raise ValueError("n must be >= 0")

    base = _base_date(start_date)
    rng = random.Random(seed)

    rows = [
        {
            "train_id": f"TRN-{i + 1:03}",
            "section_id": rng.choice(SECTIONS),
            "date": (base + timedelta(days=rng.randint(0, 6))).strftime(
                "%Y-%m-%d"
            ),
            "train_priority": rng.choice(TRAIN_PRIORITIES),
        }
        for i in range(n)
    ]

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Department merge engine
# ---------------------------------------------------------------------------


def find_and_merge(
    scheduled_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Merge requests that share section + date and belong to 2+ departments.

    Expected input columns:
        request_id, department, section_id, requested_date,
        duration_hours, priority_score

    Returns:
        merged_df: joint blocks only.
        standalone_df: requests that did not qualify for a merge.
    """
    required = {
        "request_id",
        "department",
        "section_id",
        "requested_date",
        "duration_hours",
        "priority_score",
    }
    missing = required.difference(scheduled_df.columns)
    if missing:
        raise ValueError(
            "scheduled_df is missing required columns: "
            + ", ".join(sorted(missing))
        )

    if scheduled_df.empty:
        return (
            pd.DataFrame(
                columns=[
                    "section_id",
                    "date",
                    "departments_merged",
                    "num_requests_merged",
                    "original_request_ids",
                    "joint_duration_hours",
                    "sum_of_individual_hours",
                    "hours_saved",
                    "joint_priority_score",
                ]
            ),
            scheduled_df.copy(),
        )

    # One groupby replaces the original Python-level group iteration for most
    # aggregation work, while preserving the same explainable merge rule.
    grouped = scheduled_df.groupby(
        ["section_id", "requested_date"], sort=True, dropna=False
    )

    summary = grouped.agg(
        departments=("department", lambda s: tuple(sorted(set(s)))),
        num_requests_merged=("request_id", "size"),
        original_request_ids=("request_id", lambda s: ", ".join(map(str, s))),
        joint_duration_hours=("duration_hours", "max"),
        sum_of_individual_hours=("duration_hours", "sum"),
        joint_priority_score=("priority_score", "max"),
    ).reset_index()

    summary["num_departments"] = summary["departments"].map(len)
    merge_mask = summary["num_departments"] >= 2

    merged_df = summary.loc[merge_mask].copy()
    merged_df["date"] = merged_df["requested_date"]
    merged_df["departments_merged"] = merged_df["departments"].map(
        lambda d: ", ".join(d)
    )
    merged_df["hours_saved"] = (
        merged_df["sum_of_individual_hours"] - merged_df["joint_duration_hours"]
    )

    merged_df = merged_df[
        [
            "section_id",
            "date",
            "departments_merged",
            "num_requests_merged",
            "original_request_ids",
            "joint_duration_hours",
            "sum_of_individual_hours",
            "hours_saved",
            "joint_priority_score",
        ]
    ]

    # Identify merge-eligible (section, date) pairs without repeatedly
    # materialising Python dictionaries for every group.
    merge_keys = summary.loc[merge_mask, ["section_id", "requested_date"]]
    if merge_keys.empty:
        standalone_df = scheduled_df.copy()
    else:
        merge_index = pd.MultiIndex.from_frame(merge_keys)
        row_index = pd.MultiIndex.from_frame(
            scheduled_df[["section_id", "requested_date"]]
        )
        standalone_df = scheduled_df.loc[~row_index.isin(merge_index)].copy()

    return merged_df.reset_index(drop=True), standalone_df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Demo / pipeline
# ---------------------------------------------------------------------------


def run_demo(
    request_count: int = 15,
    timetable_count: int = 40,
    seed: int = 42,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """Run the available end-to-end prototype and save CSV outputs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    requests_df = generate_block_requests(request_count, seed=seed)
    timetable_df = generate_timetable(timetable_count, seed=seed)

    print("=== Sample Block Requests (BDMS) ===")
    print(requests_df.head(10).to_string(index=False))

    print("\n=== Sample Timetable (COA) ===")
    print(timetable_df.head(10).to_string(index=False))

    # The merge engine expects priority_score. The uploaded source files do
    # not contain the priority-scoring implementation, so the demo stops here
    # rather than inventing a scoring formula.
    requests_df.to_csv(output_dir / "block_requests.csv", index=False)
    timetable_df.to_csv(output_dir / "timetable.csv", index=False)

    print(f"\nSaved: {output_dir / 'block_requests.csv'}")
    print(f"Saved: {output_dir / 'timetable.csv'}")
    print(
        "\nNote: find_and_merge() is ready for a scheduled DataFrame containing "
        "priority_score. The original priority_scoring.py and scheduler.py "
        "implementations were not among the uploaded files."
    )


if __name__ == "__main__":
    run_demo()
